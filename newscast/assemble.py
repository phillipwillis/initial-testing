"""Turning a wire script into a validated story (§6 phase 4, §8 assemble_story).

Input is a `WireScript` off CNN. Output is a `Story` in the §4 markup that the
rule engine checks and `plan_keystrokes` translates.

The markup is built as text and then parsed, so the assembler cannot emit
something the parser would reject: if it round-trips, it is real markup.

What this does **not** do is rewrite copy. §11.12 puts an Opus model on the
writing pass, and until that exists the wire's own words go through unchanged,
with an editor note wherever a human has to look — a CG that had to be trimmed,
daypart language written for a different show, a package whose duration cannot
be trusted (§11.23).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from newscast.config import ShowConfig
from newscast.markup import parse_story
from newscast.model import Story, StoryKind
from newscast.readtime import estimate_read_time
from newscast.transcript import Soundbite, Trim, timecode
from newscast.wires.cnn_script import WireScript
from newscast.wires.stub import StoryStub

# "Kelly/Seattle Resident: "I love Seattle so much.""
_SPEAKER_RE = re.compile(
    r"^\s*(?P<name>[A-Z][A-Za-z.'’\- ]{1,50})\s*/\s*(?P<title>[^:]{2,60})\s*:\s*(?P<quote>.+)$"
)

# "Nats of music", "-sounds of bustling-"
_NAT_RE = re.compile(r"^\s*-?\s*(?:nat|nats|natural sound|sounds? of)\b.*$", re.I)


@dataclass
class Assembly:
    """An assembled story and everything a human needs to check it."""

    story: Story
    markup: str
    notes: list[str] = field(default_factory=list)
    cgs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.story.slug


@dataclass
class Bite:
    """One soundbite, and the wire row it has to be pulled from.

    CNN files a row per speaker, so a story's second soundbite lives under a
    different story number from its first. Losing that mapping means an editor
    cannot find the clip, which is what §5 R15 exists to prevent.
    """

    wire: WireScript
    stub: StoryStub

    # §15 — when the video has been transcribed, the soundbite is a real span
    # of tape with a real length, and the wire's numbers stop being guesses.
    # `soundbite` may hold several clips: one SOT can be two or three cut
    # together, from one speaker or from different sources (§11.26).
    soundbite: Optional[Soundbite] = None

    @property
    def source_ref(self) -> str:
        return self.stub.story_number or self.stub.id or "CNN Newsource"


def shorten_cg(text: str, ceiling: int) -> tuple[str, bool]:
    """Fit a CG to the on-air ceiling (§11.9: 39 characters).

    Wire titles routinely run past it — "CA: RARE TRIPLETS/DOCTOR-ALL THE SAME
    SEX" is 41 — so this trims at a word boundary and reports whether it had to,
    because a machine-trimmed lower third is exactly the kind of thing a human
    should read before it goes on air.
    """
    clean = " ".join((text or "").split()).upper()
    if len(clean) <= ceiling:
        return clean, False

    words = clean.split(" ")
    out = ""
    for word in words:
        candidate = f"{out} {word}".strip()
        if len(candidate) > ceiling:
            break
        out = candidate
    return (out or clean[:ceiling]).rstrip(" ,-/"), True


def _copy_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _body_lines(text: str, cgs: list[str], ceiling: int, notes: list[str]) -> list[str]:
    """Convert a reporter track into §4 markup.

    The wire writes a soundbite inline as `Name/Title: "quote"`. In §4 that is a
    lower third followed by the quote in mixed case, so the speaker line becomes
    a CG and the quote stands on its own.
    """
    out: list[str] = []
    for line in _copy_lines(text):
        speaker = _SPEAKER_RE.match(line)
        if speaker:
            cg_text, trimmed = shorten_cg(
                f"{speaker.group('name')}, {speaker.group('title')}", ceiling
            )
            if trimmed:
                notes.append(f"CG trimmed to fit: {cg_text!r}")
            cgs.append(cg_text)
            out.append(f"[CG: {cg_text}]")
            quote = speaker.group("quote").strip()
            if not quote.startswith('"'):
                quote = f'"{quote.strip(chr(34))}"'
            out.append(quote)
            continue

        if _NAT_RE.match(line):
            out.append(f"-{line.strip('-').strip().lower()}-")
            continue

        out.append(line)
    return out


def _split_evenly(lines: list[str], parts: int) -> list[list[str]]:
    """Split voice-over copy into the runs that sit between soundbites."""
    if parts <= 1:
        return [lines]
    size = max(1, len(lines) // parts)
    chunks = [lines[i * size : (i + 1) * size] for i in range(parts)]
    leftover = lines[parts * size :]
    if leftover:
        chunks[-1] = chunks[-1] + leftover
    return chunks


def _daypart_notes(config: ShowConfig, *blocks: str) -> list[str]:
    """R13. Wire copy is written for whichever show ran it first."""
    found: list[str] = []
    haystack = " ".join(blocks).lower()
    for phrase in config.daypart_phrases:
        if phrase in haystack and phrase not in found:
            found.append(phrase)
    if not found:
        return []
    return [
        "daypart language written for another show: "
        + ", ".join(repr(p) for p in found)
        + " — rewrite for noon"
    ]


def assemble_story(
    wire: WireScript,
    stub: StoryStub,
    shot: str = "CAM3 OX2",
    anchor: str = "MEGAN",
    extra_bites: Sequence[tuple[WireScript, StoryStub]] = (),
    max_bites: int = 2,
    config: ShowConfig | None = None,
    soundbites: Optional[dict[str, Soundbite]] = None,
    trim: Optional[Trim] = None,
) -> Assembly:
    """Build a §4 story from a wire script, and any related soundbites.

    `extra_bites` are other rows the wire filed for the same story — CNN files
    one per speaker. They become additional SOT segments rather than separate
    stories, each carrying its own source, because they are the same story told
    by more than one person.

    `shot` and `anchor` come from the block the story is slotted into (§11.2,
    §11.3); slotting itself is §10.7 and not done here.
    """
    config = config or ShowConfig()
    ceiling, _ = config.effective_cg_ceiling()
    notes: list[str] = []
    cgs: list[str] = []

    headline = wire.title or stub.slug
    cg_text, trimmed = shorten_cg(headline, ceiling)
    if trimmed:
        notes.append(f"CG trimmed from the wire title to fit {ceiling} characters")
    cgs.append(cg_text)

    lead_in = _copy_lines(wire.lead_in) or _copy_lines(stub.teaser.upper())
    tag = _copy_lines(wire.tag)

    source_ref = stub.story_number or stub.id or "CNN Newsource"
    sources: list[str] = []
    lines: list[str] = []

    # Every row that actually carries a soundbite, the lead first. §3 caps the
    # form at VOSOTVOSOT, so no more than two are used.
    soundbites = soundbites or {}

    def _bite(w: WireScript, st: StoryStub) -> Bite:
        ref = st.story_number or st.id or "CNN Newsource"
        return Bite(w, st, soundbite=soundbites.get(ref))

    bites = [_bite(wire, stub)] if wire.sot_body else []
    bites.extend(
        _bite(extra_wire, extra_stub)
        for extra_wire, extra_stub in extra_bites
        if extra_wire.sot_body
    )
    if len(bites) > max_bites:
        dropped = [b.source_ref for b in bites[max_bites:]]
        notes.append(
            f"{len(bites)} soundbites available; used {max_bites} "
            f"(§3 caps the form at VOSOTVOSOT). Unused: {', '.join(dropped)}"
        )
        bites = bites[:max_bites]

    if wire.is_package:
        lines.append(f"[{shot}]")
        lines.append(f"[{anchor}]")
        lines.extend(lead_in)
        lines.append(f"[SOURCE: CNN Newsource {source_ref}]")
        sources.append(source_ref)
        if trim is not None:
            lines.append(f"[NOTE: {trim.editor_note()}]")
            lines.append(f"[PKG {timecode(trim.duration)}]")
        else:
            lines.append(
                "[NOTE: package as delivered; CNN's printed duration is not the "
                "running time (§11.23) — confirm the TRT before air]"
            )
            duration = wire.trt or _mmss(stub.wire_duration_seconds)
            lines.append(f"[PKG {duration}]" if duration else "[PKG]")
            if not duration:
                notes.append("no TRT anywhere — the package length is unknown")
            else:
                notes.append(
                    "the package length is the wire's number, not a running "
                    "time — transcribe it to get the real one (§15)"
                )
        lines.append(f"[CG: {cg_text}]")
        lines.extend(_body_lines(wire.pkg_body, cgs, ceiling, notes))
        if tag:
            lines.append("[ON CAM]")
            lines.append(f"[{anchor}]")
            lines.extend(tag)
        else:
            notes.append("no tag in the wire copy — R8 flags a package without one")

    elif bites:
        # §3 composite. One soundbite gives VOSOT; two give VOSOTVOSOT, which
        # §3 calls the largest form justifiable for a single story.
        lines.append(f"[{shot} - D]")
        lines.append(f"[{anchor}]")
        lines.extend(lead_in)
        lines.append("[VO]")
        lines.append(f"[CG: {cg_text}]")

        body = _copy_lines(wire.vo_script) or _copy_lines(wire.body)
        chunks = _split_evenly(body, len(bites))

        for position, bite in enumerate(bites):
            lines.extend(chunks[position])
            lines.append("~~~New Segment~~~")
            if bite.soundbite and bite.soundbite.clips:
                # §15 — every clip keeps its own source, because a SOT can be
                # cut from more than one of them (§11.26, R15).
                for clip_source in bite.soundbite.sources:
                    lines.append(f"[SOURCE: CNN Newsource {clip_source}]")
                    sources.append(clip_source)
                for editor_note in bite.soundbite.editor_notes():
                    lines.append(f"[NOTE: {editor_note}]")
                lines.append(f"[SOT {timecode(bite.soundbite.duration)}]")
            else:
                lines.append(f"[SOURCE: CNN Newsource {bite.source_ref}]")
                lines.append(
                    "[NOTE: pull the soundbite; take in and out points from the "
                    "transcript, not the wire script (§11.7)]"
                )
                sources.append(bite.source_ref)
                lines.append(f"[SOT {bite.wire.trt or '0:10'}]")
                notes.append(
                    f"{bite.source_ref} has no transcript, so its SOT length is "
                    "the wire's number and not a running time (§11.23)"
                )

            speaker = bite.wire.supers[0] if bite.wire.supers else None
            bite_cg, bite_trimmed = shorten_cg(
                f"{speaker.name}, {speaker.title}" if speaker else headline, ceiling
            )
            if bite_trimmed:
                notes.append(f"soundbite CG trimmed to fit: {bite_cg!r}")
            if speaker is None:
                notes.append(
                    f"no super on {bite.source_ref} — the soundbite CG is a "
                    "placeholder and needs a name and title"
                )
            cgs.append(bite_cg)
            lines.append(f"[CG: {bite_cg}]")

            # The transcript is the authoritative verbatim: a wire sometimes
            # ships an old script against a revamped package (§11.7).
            if bite.soundbite and bite.soundbite.text:
                lines.append(f'"{bite.soundbite.text}"')
            else:
                spoken = _copy_lines(bite.wire.sot_body)
                lines.append(f'"{" ".join(spoken)}"' if spoken else '"…"')

            if position + 1 < len(bites):
                lines.append("[CONT VO]")

        lines.append("[ON CAM - BACK TO D]")
        lines.append(f"[{anchor}]")
        lines.extend(tag or ["MORE ON THIS AS WE GET IT."])
        if not tag:
            notes.append("no tag in the wire copy — a placeholder tag was written")

    else:
        lines.append(f"[{shot}]")
        lines.append(f"[{anchor}]")
        lines.extend(lead_in)
        lines.append("[VO]")
        lines.append(f"[CG: {cg_text}]")
        body = _copy_lines(wire.vo_script) or _copy_lines(wire.body)
        lines.extend(body)
        if tag:
            lines.append("[ON CAM]")
            lines.extend(tag)

    lines.append("[#####]")
    markup = "\n".join(lines)

    notes.extend(
        _daypart_notes(config, wire.lead_in, wire.vo_script, wire.pkg_body, wire.tag)
    )
    if stub.embargo:
        notes.append(f"EMBARGO: {stub.embargo} — check before airing")

    story = parse_story(markup, slug=headline, kind=StoryKind.NEWS)
    return Assembly(
        story=story, markup=markup, notes=notes, cgs=cgs, sources=sources
    )


def _mmss(seconds: Optional[float]) -> str:
    if not seconds:
        return ""
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"
