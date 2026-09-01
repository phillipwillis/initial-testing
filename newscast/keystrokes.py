"""Turning a validated story into the keystrokes Inception expects (§13.6).

Inception is not typed into literally. It expands shortcuts: typing `[OX2` and
pressing ENTER creates a real production element, and Option+2 inserts MEGAN.
So `serialize_story()` is not what drives the CMS — the §4 markup is the
validated intermediate form, and this module is the translation at the end.

A plan is data, not actions. Nothing here touches Selenium, so the sequence
that will be typed into a live rundown can be asserted in a test, read in a
diff, and shown to a producer before it is ever sent.

Two known-fragile mechanics are modelled explicitly rather than hidden:

* Inception auto-appends `-D` to some shot cues and auto-fills `0:00` on a PKG.
  The previous implementation removed them with bare BACKSPACE and DELETE runs.
  Those are represented as `Correction` steps carrying what they expect to
  remove, so a checking adapter can verify rather than trust — see
  `docs/inception.md`, "What not to carry forward".
* Inserting a CG drops the editor out of SOT (green) mode, so a CG inside a
  package has to be followed by re-enabling it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from newscast.config import ShowConfig
from newscast.model import (
    AnchorCue,
    CameraCue,
    CGCue,
    Copy,
    CopyStyle,
    NoteCue,
    OnCamCue,
    PKGCue,
    SourceCue,
    SOTCue,
    Story,
    VideoCue,
    VOCue,
)

# §11.2 / docs/inception.md — Option+<key> inserts an anchor. Doug and Linda are
# the morning team; the noon show is Jeff and Megan.
ANCHOR_SHORTCUTS = {"DOUG": "1", "MEGAN": "2", "LINDA": "4", "JEFF": "5"}

CG_SHORTCUT = "s"
END_CHORD = ("alt", "command", "h")

# Shot cues Inception auto-appends "-D" to, which then has to come off.
SHOT_APPENDS_D = frozenset({"OX3", "OX4", "OX5"})

# How long Inception needs to expand a bracket shortcut before more typing.
EXPAND_PAUSE_SECONDS = 0.35


@dataclass(frozen=True)
class Keystroke:
    """One step of a plan.

    kind:
      text        type these characters
      key         press this key (ENTER, BACKSPACE, DELETE)
      chord       press these together (option+2, option+command+h)
      button      click a named toolbar control (the SOT toggle)
      wait        pause for `seconds`, so an expansion can complete
      correction  remove text Inception inserted by itself
    """

    kind: str
    value: str = ""
    count: int = 1
    seconds: float = 0.0
    expects: str = ""
    reason: str = ""

    def __str__(self) -> str:
        if self.kind == "wait":
            return f"wait {self.seconds}s ({self.reason})"
        if self.kind == "correction":
            return f"{self.value} x{self.count} — removes {self.expects!r}"
        if self.count > 1:
            return f"{self.kind} {self.value} x{self.count}"
        return f"{self.kind} {self.value}"


def text(value: str) -> Keystroke:
    return Keystroke("text", value)


def key(name: str, count: int = 1) -> Keystroke:
    return Keystroke("key", name, count=count)


def chord(*keys: str) -> Keystroke:
    return Keystroke("chord", "+".join(keys))


def wait(seconds: float, reason: str) -> Keystroke:
    return Keystroke("wait", seconds=seconds, reason=reason)


def correction(name: str, count: int, expects: str, reason: str) -> Keystroke:
    return Keystroke("correction", name, count=count, expects=expects, reason=reason)


def button(name: str, reason: str = "") -> Keystroke:
    return Keystroke("button", name, reason=reason)


@dataclass
class KeystrokePlan:
    steps: list[Keystroke] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, *steps: Keystroke) -> None:
        self.steps.extend(steps)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def typed_text(self) -> str:
        return "".join(s.value for s in self.steps if s.kind == "text")

    def describe(self) -> str:
        return "\n".join(str(step) for step in self.steps)


def _shot_token(cue: CameraCue) -> Optional[str]:
    """The bracket shortcut for a camera cue.

    Inception's shortcut is the over-shoulder, not the camera: `[OX2`. A cue
    with no monitor has no shortcut, which is why the weather wall and any
    monitorless shot fall through to a warning rather than a wrong keystroke.
    """
    return cue.monitor.upper() if cue.monitor else None


def _emit_shot(plan: KeystrokePlan, cue: CameraCue, restoring: bool = False) -> None:
    """Issue a shot cue.

    `restoring` marks a return to camera, which re-issues the same shortcut —
    with the appended -D kept, because a story coming back to a monitor parked
    in D wants it.
    """
    token = _shot_token(cue)
    if token is None:
        plan.warn(
            f"{cue.full_shot} has no over-shoulder, so it has no bracket shortcut; "
            "it needs setting by hand"
        )
        return

    plan.add(text(f"[{token}"), wait(EXPAND_PAUSE_SECONDS, f"{token} expands"), key("ENTER"))

    wants_d = cue.park_d or restoring
    if token in SHOT_APPENDS_D and not wants_d:
        plan.add(
            correction(
                "BACKSPACE",
                2,
                "-D",
                f"{token} expands with -D appended, and this story does not park "
                "the monitor in D",
            )
        )
    elif wants_d and token not in SHOT_APPENDS_D:
        # The story needs the monitor in D (§5 R2) but this shot does not expand
        # with -D, and how a producer adds it by hand is not recorded anywhere.
        plan.warn(
            f"{token} must park the monitor in D, but only "
            f"{', '.join(sorted(SHOT_APPENDS_D))} expand with -D — how to add it "
            "to this shot is not known, so a human has to"
        )


def _emit_anchor(plan: KeystrokePlan, cue: AnchorCue, config: ShowConfig) -> None:
    for name in cue.names:
        shortcut = ANCHOR_SHORTCUTS.get(name.upper())
        if shortcut is None:
            plan.warn(f"no Inception shortcut is known for anchor {name!r}")
            plan.add(text(f"[{name}]"))
            continue
        plan.add(chord("option", shortcut))


def _emit_video(plan: KeystrokePlan, cue: VideoCue) -> None:
    if isinstance(cue, PKGCue):
        plan.add(text("[PKG"), wait(EXPAND_PAUSE_SECONDS, "PKG expands"), key("ENTER"))
        plan.add(
            correction("BACKSPACE", 4, "- D", "a PKG expands with - D appended"),
            correction("DELETE", 4, "0:00", "a PKG expands with a placeholder 0:00"),
        )
        if cue.duration_text:
            plan.add(text(cue.duration_text))
        else:
            plan.warn("PKG has no duration, so the TRT field is left empty")
        plan.add(button("SOT", "green on: the reporter track is not anchor copy"))
        return

    if isinstance(cue, SOTCue):
        # A soundbite is typed inside SOT (green) mode rather than expanded from
        # a bracket shortcut. Green marks text the anchor does not read, so it
        # does not scroll on the prompter.
        plan.add(button("SOT", "green on for the soundbite"))
        return


def plan_keystrokes(story: Story, config: ShowConfig | None = None) -> KeystrokePlan:
    """Translate one validated story into the keystrokes that produce it.

    Expects a story that already passes the §5 rule engine: this converts, it
    does not check. Anything it cannot express becomes a warning rather than a
    silently wrong keystroke.
    """
    config = config or ShowConfig()
    plan = KeystrokePlan()
    green = False
    current_shot: Optional[CameraCue] = None

    for segment in story.segments:
        for element in segment.elements:
            if isinstance(element, CameraCue):
                current_shot = element
                _emit_shot(plan, element)

            elif isinstance(element, OnCamCue):
                if green:
                    plan.add(button("SOT", "turn green off before returning to camera"))
                    green = False
                if current_shot is None:
                    plan.warn(
                        "the story returns to camera before any camera cue, so there "
                        "is no shot to restore"
                    )
                else:
                    # Returning to camera re-issues the shot rather than typing
                    # anything: the previous implementation's tag block emits the
                    # shot token again. When the monitor was parked in D the
                    # appended -D is wanted, so it is kept.
                    _emit_shot(plan, current_shot, restoring=element.back_to_d)

            elif isinstance(element, AnchorCue):
                _emit_anchor(plan, element, config)

            elif isinstance(element, CGCue):
                plan.add(chord("option", CG_SHORTCUT))
                if green:
                    # Inserting a CG drops the editor out of green.
                    plan.add(button("SOT", "a CG drops out of green; turn it back on"))

            elif isinstance(element, VOCue):
                if green:
                    # [CONT VO] puts the anchor back on a live mic over new
                    # video. That copy is read, so it must leave green or it
                    # will not scroll on the prompter.
                    plan.add(button("SOT", "green off: the anchor reads again"))
                    green = False
                plan.add(
                    text("[VO"), wait(EXPAND_PAUSE_SECONDS, "VO expands"), key("ENTER")
                )

            elif isinstance(element, SOTCue):
                _emit_video(plan, element)
                green = True

            elif isinstance(element, PKGCue):
                _emit_video(plan, element)
                green = True

            elif isinstance(element, Copy):
                if element.style is CopyStyle.NAT:
                    continue  # natural sound is a note to the editor, not typed copy
                for line in element.lines:
                    plan.add(text(line), key("ENTER"))

            elif isinstance(element, (SourceCue, NoteCue)):
                # Source references and editor notes live in Inception's own
                # fields, not in the script body.
                continue

    if green:
        plan.add(button("SOT", "leave green before ending the story"))

    plan.add(chord(*END_CHORD))
    return plan
