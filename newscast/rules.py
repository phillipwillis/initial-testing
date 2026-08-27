"""The rule engine: CLAUDE.md §5, plus a handful of X-checks derived from §3/§4.

Every rule is a function (Show, ShowConfig) -> list[Violation], registered by
code. They run against the assembled rundown, not against individual model
outputs (§5). Nothing here calls a model or the network: a violation is a fact
about the script, reproducible from the text alone.

Rule codes R1-R15 are Phil's, verbatim from §5. Codes beginning with X are
checks the §3/§4 prose implies but the §5 list does not name; they are separated
so the two can be argued about separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from newscast.config import UNSET, BlockConfig, ShowConfig
from newscast.model import (
    AnchorCue,
    Block,
    CameraCue,
    Copy,
    CopyStyle,
    MonitorCue,
    NoCGCue,
    NoteCue,
    OnCamCue,
    PKGCue,
    Show,
    ShotExceptionCue,
    SOTCue,
    SourceCue,
    Story,
    VideoCue,
)
from newscast.timing import block_seconds, story_seconds, vo_stretches


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    ERROR = 2


@dataclass(frozen=True)
class Violation:
    code: str
    severity: Severity
    message: str
    block: str = ""
    story: str = ""
    line_no: int = 0
    hint: str = ""

    def __str__(self) -> str:
        where = " ".join(p for p in (self.block, self.story) if p)
        line = f":{self.line_no}" if self.line_no else ""
        head = f"[{self.severity.name}] {self.code} {where}{line}"
        return f"{head}: {self.message}" + (f"\n    hint: {self.hint}" if self.hint else "")


RuleFn = Callable[[Show, ShowConfig], list[Violation]]

_REGISTRY: dict[str, "Rule"] = {}


@dataclass(frozen=True)
class Rule:
    code: str
    summary: str
    fn: RuleFn
    spec_ref: str = ""


def rule(code: str, summary: str, spec_ref: str = "") -> Callable[[RuleFn], RuleFn]:
    def wrap(fn: RuleFn) -> RuleFn:
        _REGISTRY[code] = Rule(code=code, summary=summary, fn=fn, spec_ref=spec_ref)
        return fn

    return wrap


def all_rules() -> list[Rule]:
    def sort_key(code: str) -> tuple[int, int, str]:
        family = 0 if code.startswith("R") else 1
        digits = "".join(c for c in code if c.isdigit())
        return (family, int(digits or 0), code)

    return [_REGISTRY[c] for c in sorted(_REGISTRY, key=lambda c: sort_key(c))]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _iter_stories(show: Show):
    for block in show.blocks:
        for i, story in enumerate(block.stories):
            yield block, i, story


def _label(story: Story, index: int) -> str:
    return story.slug or f"story #{index + 1}"


def _first_line(story: Story) -> int:
    els = story.elements
    return els[0].line_no if els else story.line_no


def _block_config(config: ShowConfig, block: Block) -> Optional[BlockConfig]:
    try:
        return config.block(block.half, block.label)
    except KeyError:
        return None


# --------------------------------------------------------------------------
# Playback / technical
# --------------------------------------------------------------------------


@rule("R1", "Two D-channel stories may not run back to back", "§5 R1")
def r1_back_to_back_d(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block in show.blocks:
        for i in range(1, len(block.stories)):
            prev, cur = block.stories[i - 1], block.stories[i]
            if not (prev.uses_d_channel and cur.uses_d_channel):
                continue

            elements = cur.elements
            first_video = next(
                (n for n, e in enumerate(elements) if isinstance(e, VideoCue)), None
            )
            if first_video is None:
                continue
            monitors = [
                (n, e) for n, e in enumerate(elements) if isinstance(e, MonitorCue)
            ]
            has_placeholder = any(
                n < first_video and e.kind == "PLACEHOLDER" for n, e in monitors
            )
            has_dupe = any(n > first_video and e.kind == "DUPE" for n, e in monitors)

            if has_placeholder and has_dupe:
                continue

            missing = []
            if not has_placeholder:
                missing.append("monitor video placeholder at the start")
            if not has_dupe:
                missing.append("duplicate monitor file at the end of the SOT")
            out.append(
                Violation(
                    code="R1",
                    severity=Severity.ERROR,
                    message=(
                        f"follows D-channel story '{_label(prev, i - 1)}' back to back "
                        f"without {' and '.join(missing)}"
                    ),
                    block=block.name,
                    story=_label(cur, i),
                    line_no=_first_line(cur),
                    hint=(
                        "loading this story overwrites the previous story's monitor "
                        "mid-tag and the monitor insta-swaps on air; either reorder the "
                        "block or add [MONITOR PLACEHOLDER] / [MONITOR DUPE]"
                    ),
                )
            )
    return out


@rule("R2", "SOT returning to camera needs - D and BACK TO D", "§5 R2")
def r2_d_channel_cues(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        if not any(isinstance(e, SOTCue) for e in story.elements):
            continue
        elements = story.elements
        first_sot = next(n for n, e in enumerate(elements) if isinstance(e, SOTCue))
        returns = [
            (n, e)
            for n, e in enumerate(elements)
            if isinstance(e, OnCamCue) and n > first_sot
        ]
        if not returns:
            continue  # never comes back to camera -- SOTVO with no tag, no D needed

        cameras = [e for e in elements if isinstance(e, CameraCue)]
        if cameras and not cameras[0].park_d:
            out.append(
                Violation(
                    code="R2",
                    severity=Severity.ERROR,
                    message="SOT returns to camera but the opening camera cue is missing '- D'",
                    block=block.name,
                    story=_label(story, i),
                    line_no=cameras[0].line_no,
                    hint=f"write [{cameras[0].shot}"
                    + (f" {cameras[0].monitor}" if cameras[0].monitor else "")
                    + " - D]",
                )
            )
        for _, ret in returns:
            if not ret.back_to_d:
                out.append(
                    Violation(
                        code="R2",
                        severity=Severity.ERROR,
                        message="return to camera after a SOT is missing 'BACK TO D'",
                        block=block.name,
                        story=_label(story, i),
                        line_no=ret.line_no,
                        hint="write [ON CAM - BACK TO D]",
                    )
                )
            break  # only the first return restores the monitor
    return out


@rule("R3", "Every story terminates with [#####]", "§5 R3")
def r3_terminator(show: Show, config: ShowConfig) -> list[Violation]:
    return [
        Violation(
            code="R3",
            severity=Severity.ERROR,
            message="story does not end with [#####]",
            block=block.name,
            story=_label(story, i),
            line_no=_first_line(story),
        )
        for block, i, story in _iter_stories(show)
        if not story.terminated
    ]


# --------------------------------------------------------------------------
# Editorial / format
# --------------------------------------------------------------------------


@rule("R4", "Every segment has a CG unless explicitly exempted", "§5 R4")
def r4_cg_present(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for segment in story.segments:
            if segment.cgs or segment.of_type(NoCGCue):
                continue
            out.append(
                Violation(
                    code="R4",
                    severity=Severity.ERROR,
                    message=f"segment {segment.index + 1} ({segment.mode.value}) has no CG",
                    block=block.name,
                    story=_label(story, i),
                    line_no=segment.elements[0].line_no if segment.elements else 0,
                    hint="add [CG: ...] or declare the exception with [NO CG: reason]",
                )
            )
    return out


@rule("R5", "CGs are short", "§5 R5, §11.9")
def r5_cg_length(show: Show, config: ShowConfig) -> list[Violation]:
    ceiling, provisional = config.effective_cg_ceiling()
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for cg in (c for s in story.segments for c in s.cgs):
            if len(cg.text) > ceiling:
                out.append(
                    Violation(
                        code="R5",
                        severity=Severity.ERROR,
                        message=(
                            f"CG is {len(cg.text)} characters, ceiling is {ceiling}"
                            + (" (PROVISIONAL -- §11.9 unanswered)" if provisional else "")
                        ),
                        block=block.name,
                        story=_label(story, i),
                        line_no=cg.line_no,
                        hint="a CG is a slug-length headline, not a sentence",
                    )
                )
            elif cg.text != cg.text.upper():
                out.append(
                    Violation(
                        code="R5",
                        severity=Severity.WARNING,
                        message="CG is not in ALL CAPS",
                        block=block.name,
                        story=_label(story, i),
                        line_no=cg.line_no,
                    )
                )
    return out


@rule("R6", "RDR only under ~15 seconds", "§5 R6")
def r6_rdr_length(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        if story.form != "RDR" or story.is_tease:
            continue
        seconds = story_seconds(story, config)
        if seconds > config.rdr_max_seconds:
            out.append(
                Violation(
                    code="R6",
                    severity=Severity.ERROR,
                    message=(
                        f"RDR runs {seconds:.1f}s, over the "
                        f"{config.rdr_max_seconds:.0f}s ceiling"
                    ),
                    block=block.name,
                    story=_label(story, i),
                    line_no=_first_line(story),
                    hint="a story this long wants a visual aid -- make it a VO",
                )
            )
    return out


@rule("R7", "VO runs 20-45 seconds", "§5 R7")
def r7_vo_length(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        if story.is_tease:
            continue
        if story.form == "VO":
            seconds = story_seconds(story, config)
            if seconds < config.vo_min_seconds or seconds > config.vo_max_seconds:
                out.append(
                    Violation(
                        code="R7",
                        severity=Severity.ERROR,
                        message=(
                            f"VO runs {seconds:.1f}s, outside "
                            f"{config.vo_min_seconds:.0f}-{config.vo_max_seconds:.0f}s"
                        ),
                        block=block.name,
                        story=_label(story, i),
                        line_no=_first_line(story),
                    )
                )
            continue
        # Inside a composite, an over-long single VO stretch is still a problem;
        # a short one is not, because the story continues.
        for stretch in vo_stretches(story, config):
            if stretch > config.vo_max_seconds:
                out.append(
                    Violation(
                        code="R7",
                        severity=Severity.WARNING,
                        message=(
                            f"voice-over stretch runs {stretch:.1f}s inside a "
                            f"{story.form}, over the {config.vo_max_seconds:.0f}s ceiling"
                        ),
                        block=block.name,
                        story=_label(story, i),
                        line_no=_first_line(story),
                    )
                )
    return out


@rule("R8", "Every PKG has an intro; flag any PKG without an outro", "§5 R8")
def r8_pkg_wrap(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        elements = story.elements
        for n, e in enumerate(elements):
            if not isinstance(e, PKGCue):
                continue
            before = elements[:n]
            has_intro = any(
                isinstance(x, Copy) and x.style is CopyStyle.ANCHOR for x in before
            )
            if not has_intro:
                out.append(
                    Violation(
                        code="R8",
                        severity=Severity.ERROR,
                        message="PKG has no anchor intro",
                        block=block.name,
                        story=_label(story, i),
                        line_no=e.line_no,
                        hint="every PKG is introduced by an RDR (§3)",
                    )
                )
            after = elements[n + 1 :]
            back_on_cam = next(
                (m for m, x in enumerate(after) if isinstance(x, OnCamCue)), None
            )
            has_outro = back_on_cam is not None and any(
                isinstance(x, Copy) and x.style is CopyStyle.ANCHOR
                for x in after[back_on_cam:]
            )
            if not has_outro:
                out.append(
                    Violation(
                        code="R8",
                        severity=Severity.WARNING,
                        message="PKG has no outro -- flagged for human review",
                        block=block.name,
                        story=_label(story, i),
                        line_no=e.line_no,
                    )
                )
    return out


@rule("R9", "Max 2 PKGs per block", "§5 R9")
def r9_pkg_budget(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block in show.blocks:
        bc = _block_config(config, block)
        cap = bc.max_pkgs if bc else 2
        count = block.pkg_count
        if count > cap:
            out.append(
                Violation(
                    code="R9",
                    severity=Severity.ERROR,
                    message=f"block carries {count} PKGs, budget is {cap}",
                    block=block.name,
                    hint="decompose one to a VO plus a B-roll editor note (§0.2)",
                )
            )
    return out


@rule("R10", "Every block ends with a bump/tease", "§5 R10")
def r10_block_bump(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block in show.blocks:
        if not block.stories:
            out.append(
                Violation(
                    code="R10",
                    severity=Severity.ERROR,
                    message="block is empty, so it cannot end with a bump",
                    block=block.name,
                )
            )
            continue
        if not block.stories[-1].is_tease:
            last = block.stories[-1]
            out.append(
                Violation(
                    code="R10",
                    severity=Severity.ERROR,
                    message="block does not end with a bump/tease",
                    block=block.name,
                    story=_label(last, len(block.stories) - 1),
                    line_no=_first_line(last),
                    hint="append [TEASE: ...] to the last story or add a BUMP element",
                )
            )
    return out


@rule("R11", "Camera shot is constant within a block", "§5 R11, §11.3")
def r11_shot_constant(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block in show.blocks:
        bc = _block_config(config, block)
        default = bc.default_shot if bc and bc.default_shot is not UNSET else None
        for i, story in enumerate(block.stories):
            shots = story.shots
            if not shots:
                continue
            if default is None:
                default = shots[0]
            flagged = any(isinstance(e, ShotExceptionCue) for e in story.elements)
            odd = [s for s in shots if s != default]
            if odd and not flagged:
                out.append(
                    Violation(
                        code="R11",
                        severity=Severity.ERROR,
                        message=(
                            f"uses {', '.join(sorted(set(odd)))} in a block shot on {default}"
                        ),
                        block=block.name,
                        story=_label(story, i),
                        line_no=_first_line(story),
                        hint="flag the exception with [SHOT EXCEPTION: reason]",
                    )
                )
    return out


@rule("R12", "Anchor assignment matches the block's anchor pattern", "§5 R12, §11.2")
def r12_anchor_pattern(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    unconfigured: list[str] = []
    for block in show.blocks:
        bc = _block_config(config, block)
        if bc is None or bc.anchors is UNSET:
            unconfigured.append(block.name)
            continue
        allowed = {a.upper() for a in bc.anchors}
        seen: list[str] = []
        for i, story in enumerate(block.stories):
            for anchor in story.anchors:
                if anchor.upper() not in allowed:
                    out.append(
                        Violation(
                            code="R12",
                            severity=Severity.ERROR,
                            message=(
                                f"{anchor} reads in this block, whose anchors are "
                                f"{', '.join(sorted(allowed))}"
                            ),
                            block=block.name,
                            story=_label(story, i),
                            line_no=_first_line(story),
                        )
                    )
                if anchor.upper() not in seen:
                    seen.append(anchor.upper())
        mode = getattr(bc, "read_mode", UNSET)
        if mode is not UNSET and block.stories:
            if mode == "solo" and len(seen) > 1:
                out.append(
                    Violation(
                        code="R12",
                        severity=Severity.ERROR,
                        message=f"solo block has {len(seen)} anchors reading: {', '.join(seen)}",
                        block=block.name,
                    )
                )
            elif mode == "dual" and len(seen) < 2:
                out.append(
                    Violation(
                        code="R12",
                        severity=Severity.ERROR,
                        message="dual-read block has only one anchor reading",
                        block=block.name,
                    )
                )
    if unconfigured:
        out.append(
            Violation(
                code="R12",
                severity=Severity.INFO,
                message=(
                    "anchor pattern not configured for "
                    f"{', '.join(unconfigured)}; R12 not enforced there"
                ),
                hint="CLAUDE.md §11.2 -- needs the anchor roster and the weather break-off",
            )
        )
    return out


@rule("R13", "Daypart language fits the noon show", "§5 R13")
def r13_daypart(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for segment in story.segments:
            for copy in segment.anchor_copy:
                lowered = copy.text.lower()
                for phrase in config.daypart_phrases:
                    if phrase in lowered:
                        out.append(
                            Violation(
                                code="R13",
                                severity=Severity.WARNING,
                                message=f'daypart language: "{phrase}" in a noon show',
                                block=block.name,
                                story=_label(story, i),
                                line_no=copy.line_no,
                                hint="rewrite for noon or mark for trim with an editor note",
                            )
                        )
    return out


@rule("R14", "Block runtime is within budget", "§5 R14, §11.1")
def r14_block_budget(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    unconfigured: list[str] = []
    for block in show.blocks:
        bc = _block_config(config, block)
        if bc is None or bc.budget_seconds is UNSET:
            unconfigured.append(block.name)
            continue
        actual = block_seconds(block, config)
        budget = float(bc.budget_seconds)
        tolerance = config.block_budget_tolerance_seconds
        if abs(actual - budget) > tolerance:
            over = actual > budget
            out.append(
                Violation(
                    code="R14",
                    severity=Severity.ERROR,
                    message=(
                        f"block runs {actual:.1f}s against a {budget:.0f}s budget "
                        f"(+/-{tolerance:.0f}s) -- {abs(actual - budget):.1f}s "
                        f"{'over' if over else 'under'}"
                    ),
                    block=block.name,
                    hint=(
                        "decompose a story to fit (§0.2)"
                        if over
                        else "compose a story up, or pull one forward from the pool"
                    ),
                )
            )
    if unconfigured:
        out.append(
            Violation(
                code="R14",
                severity=Severity.INFO,
                message=(
                    "block time budget not configured for "
                    f"{', '.join(unconfigured)}; R14 not enforced there"
                ),
                hint="CLAUDE.md §11.1 -- this blocks the whole fill algorithm",
            )
        )
    return out


# --------------------------------------------------------------------------
# Traceability
# --------------------------------------------------------------------------


@rule("R15", "Every SOT and PKG carries a source reference and an editor note", "§5 R15")
def r15_traceability(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for segment in story.segments:
            if not segment.uses_d_channel:
                continue
            missing = []
            if not segment.of_type(SourceCue):
                missing.append("[SOURCE: ...]")
            if not segment.of_type(NoteCue):
                missing.append("[NOTE: ...]")
            if not missing:
                continue
            cue = segment.video_cues[0]
            out.append(
                Violation(
                    code="R15",
                    severity=Severity.ERROR,
                    message=(
                        f"{cue.__class__.__name__.replace('Cue', '')} segment is missing "
                        f"{' and '.join(missing)}"
                    ),
                    block=block.name,
                    story=_label(story, i),
                    line_no=cue.line_no,
                    hint="the editor needs the source package and exactly what to pull",
                )
            )
    return out


# --------------------------------------------------------------------------
# X-checks: implied by §3/§4, not named in the §5 list
# --------------------------------------------------------------------------


@rule("X1", "Anchor copy is written in ALL CAPS", "§4")
def x1_caps(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for segment in story.segments:
            for copy in segment.anchor_copy:
                for n, line in enumerate(copy.lines):
                    if line != line.upper():
                        out.append(
                            Violation(
                                code="X1",
                                severity=Severity.WARNING,
                                message="anchor copy is not in ALL CAPS",
                                block=block.name,
                                story=_label(story, i),
                                line_no=copy.line_no + n,
                                hint=(
                                    "if this is a soundbite it needs quotes; if it is "
                                    "natural sound it needs -dashes-"
                                ),
                            )
                        )
    return out


@rule("X2", "Every SOT and PKG cue declares a duration", "§4")
def x2_durations(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for cue in (c for s in story.segments for c in s.video_cues):
            if cue.seconds > 0:
                continue
            out.append(
                Violation(
                    code="X2",
                    severity=Severity.ERROR,
                    message=(
                        f"{cue.__class__.__name__.replace('Cue', '')} cue has no usable "
                        f"duration ({cue.duration_text or 'blank'})"
                    ),
                    block=block.name,
                    story=_label(story, i),
                    line_no=cue.line_no,
                    hint="every duration rule needs this -- write [SOT 0:13] style",
                )
            )
    return out


@rule("X3", "Every story assigns a camera and an anchor", "§3, §4")
def x3_camera_and_anchor(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        elements = story.elements
        if not any(isinstance(e, CameraCue) for e in elements):
            out.append(
                Violation(
                    code="X3",
                    severity=Severity.ERROR,
                    message="story has no camera cue",
                    block=block.name,
                    story=_label(story, i),
                    line_no=_first_line(story),
                )
            )
        if not any(isinstance(e, AnchorCue) for e in elements):
            out.append(
                Violation(
                    code="X3",
                    severity=Severity.ERROR,
                    message="story has no anchor assignment",
                    block=block.name,
                    story=_label(story, i),
                    line_no=_first_line(story),
                )
            )
    return out


@rule("X4", "Every story assigns a monitor", "§3")
def x4_monitor(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        cameras = [e for e in story.elements if isinstance(e, CameraCue)]
        if not cameras:
            continue  # X3 already covers this
        if any(c.monitor for c in cameras):
            continue
        if any(isinstance(e, NoCGCue) for e in story.elements):
            continue
        out.append(
            Violation(
                code="X4",
                severity=Severity.WARNING,
                message="no over-shoulder monitor assigned",
                block=block.name,
                story=_label(story, i),
                line_no=cameras[0].line_no,
                hint="every segment should generally carry a monitor and a CG (§3)",
            )
        )
    return out


@rule("X5", "PKG length stays inside the §3 ceiling", "§3")
def x5_pkg_length(show: Show, config: ShowConfig) -> list[Violation]:
    out: list[Violation] = []
    for block, i, story in _iter_stories(show):
        for cue in story.elements:
            if not isinstance(cue, PKGCue) or cue.seconds <= 0:
                continue
            if cue.seconds > config.pkg_ceiling_seconds:
                severity, note = Severity.ERROR, "past the ceiling for anchors off camera"
            elif cue.seconds > config.pkg_normal_max_seconds:
                severity, note = Severity.WARNING, "needs to be stellar at this length"
            else:
                continue
            out.append(
                Violation(
                    code="X5",
                    severity=severity,
                    message=f"PKG runs {cue.seconds:.0f}s -- {note}",
                    block=block.name,
                    story=_label(story, i),
                    line_no=cue.line_no,
                )
            )
    return out
