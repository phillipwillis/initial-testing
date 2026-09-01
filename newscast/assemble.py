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
from typing import Optional

from newscast.config import ShowConfig
from newscast.markup import parse_story
from newscast.model import Story, StoryKind
from newscast.readtime import estimate_read_time
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

    @property
    def slug(self) -> str:
        return self.story.slug


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
    config: ShowConfig | None = None,
) -> Assembly:
    """Build a §4 story from a wire script.

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
    lines: list[str] = []

    if wire.is_package:
        lines.append(f"[{shot}]")
        lines.append(f"[{anchor}]")
        lines.extend(lead_in)
        lines.append(f"[SOURCE: CNN Newsource {source_ref}]")
        lines.append(
            f"[NOTE: package as delivered; CNN's printed duration is not the "
            f"running time (§11.23) — confirm the TRT before air]"
        )
        duration = wire.trt or _mmss(stub.wire_duration_seconds)
        lines.append(f"[PKG {duration}]" if duration else "[PKG]")
        if not duration:
            notes.append("no TRT anywhere — the package length is unknown")
        lines.append(f"[CG: {cg_text}]")
        lines.extend(_body_lines(wire.pkg_body, cgs, ceiling, notes))
        if tag:
            lines.append("[ON CAM]")
            lines.append(f"[{anchor}]")
            lines.extend(tag)
        else:
            notes.append("no tag in the wire copy — R8 flags a package without one")

    elif wire.sot_body:
        lines.append(f"[{shot} - D]")
        lines.append(f"[{anchor}]")
        lines.extend(lead_in)
        lines.append("[VO]")
        lines.append(f"[CG: {cg_text}]")
        lines.extend(_copy_lines(wire.vo_script))
        lines.append("~~~New Segment~~~")
        lines.append(f"[SOURCE: CNN Newsource {source_ref}]")
        lines.append(
            "[NOTE: pull the soundbite; take in and out points from the "
            "transcript, not the wire script (§11.7)]"
        )
        lines.append(f"[SOT {wire.trt or '0:10'}]")
        speaker = wire.supers[0] if wire.supers else None
        bite_cg, bite_trimmed = shorten_cg(
            f"{speaker.name}, {speaker.title}" if speaker else headline, ceiling
        )
        if bite_trimmed:
            notes.append(f"soundbite CG trimmed to fit: {bite_cg!r}")
        cgs.append(bite_cg)
        lines.append(f"[CG: {bite_cg}]")
        bite = _copy_lines(wire.sot_body)
        lines.append(f'"{" ".join(bite)}"' if bite else '"…"')
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
    return Assembly(story=story, markup=markup, notes=notes, cgs=cgs)


def _mmss(seconds: Optional[float]) -> str:
    if not seconds:
        return ""
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"
