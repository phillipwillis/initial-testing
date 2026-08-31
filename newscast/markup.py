"""Parser and serializer for the script markup in CLAUDE.md §4.

parse_story()  : one story's script text -> Story
serialize_story(): Story -> script text (round-trips the §3 examples)
parse_show()   : a rundown file -> Show

The rundown file format (=== HALF 1 BLOCK A === / --- STORY: SLUG ---) is a
local interchange format for tests and fixtures. It is not an Inception format;
Inception structure arrives with the adapter in build order §10.6.
"""

from __future__ import annotations

import re
from typing import Optional

from newscast.model import (
    AnchorCue,
    Block,
    CameraCue,
    CGCue,
    Copy,
    CopyStyle,
    Element,
    MonitorCue,
    NoCGCue,
    NoteCue,
    OnCamCue,
    PKGCue,
    Segment,
    Show,
    ShotExceptionCue,
    SOTCue,
    SourceCue,
    Story,
    StoryKind,
    TeaseCue,
    VOCue,
)


class MarkupError(ValueError):
    """Malformed script markup. Carries the offending line number."""

    def __init__(self, message: str, line_no: int, line: str = ""):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.line = line


END_OF_STORY = "[#####]"
SEGMENT_BREAK_RE = re.compile(r"^\s*~~~\s*new segment\s*~~~\s*$", re.I)
BRACKET_RE = re.compile(r"^\s*\[(?P<inner>.*)\]\s*$")
BLOCK_HEADER_RE = re.compile(r"^\s*===\s*HALF\s*(\d)\s*BLOCK\s*([A-D])\s*===\s*$", re.I)
STORY_HEADER_RE = re.compile(
    r"^\s*---\s*(?P<kind>STORY|BUMP|WEATHER|OTHER)\s*:\s*(?P<slug>.*?)\s*---\s*$", re.I
)
NAT_SOUND_RE = re.compile(r"^\s*-[^-].*-\s*$")
DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2})(?:\.(\d+))?$")
CAMERA_RE = re.compile(
    r"^(?P<shot>CAM\s*\d+|[A-Z]{2,}\s*\d*)\s*(?P<monitor>OX\s*\d+)?\s*(?P<d>-\s*D)?$",
    re.I,
)
ANCHOR_RE = re.compile(r"^[A-Z][A-Z .'\-]*(?:\s*[/&]\s*[A-Z][A-Z .'\-]*)*$")

# Shots that are not a studio camera. The weather wall is one, and without this
# it parses as an anchor named "WX GFX" — it matches the anchor pattern, and
# nothing downstream notices because the rules exempt weather elements anyway.
NON_CAMERA_SHOT_RE = re.compile(r"^(?P<shot>WX\s+GFX)(?:\s*-\s*(?P<d>D))?$", re.I)

_ACCEPTED_RE = re.compile(r"\[(accepted|submitted)\]\s*$", re.I)

_STORY_KINDS = {
    "STORY": StoryKind.NEWS,
    "BUMP": StoryKind.BUMP,
    "WEATHER": StoryKind.WEATHER,
    "OTHER": StoryKind.OTHER,
}


def parse_duration(text: str) -> Optional[float]:
    """"1:25" -> 85.0, "0:13" -> 13.0, "13" -> 13.0. None if unparseable."""
    m = DURATION_RE.match(text.strip())
    if not m:
        return None
    minutes, seconds, frac = m.groups()
    total = float(seconds)
    if minutes:
        total += int(minutes) * 60
    if frac:
        total += float(f"0.{frac}")
    return total


def _parse_bracket(inner: str, line_no: int, raw: str) -> Element:
    text = inner.strip()
    upper = text.upper()

    def after_colon() -> str:
        return text.split(":", 1)[1].strip() if ":" in text else ""

    if upper.startswith("CG:"):
        return CGCue(line_no=line_no, raw=raw, text=after_colon())
    if upper.startswith("NO CG"):
        return NoCGCue(line_no=line_no, raw=raw, reason=after_colon())
    if upper.startswith("SOURCE:"):
        return SourceCue(line_no=line_no, raw=raw, text=after_colon())
    if upper.startswith("NOTE:"):
        return NoteCue(line_no=line_no, raw=raw, text=after_colon())
    if upper.startswith("SHOT EXCEPTION"):
        return ShotExceptionCue(line_no=line_no, raw=raw, reason=after_colon())
    if upper.startswith("TEASE") or upper.startswith("BUMP"):
        return TeaseCue(line_no=line_no, raw=raw, text=after_colon())
    if upper.startswith("MONITOR"):
        kind = "DUPE" if "DUPE" in upper else "PLACEHOLDER"
        return MonitorCue(line_no=line_no, raw=raw, kind=kind)
    if upper.startswith("ON CAM"):
        return OnCamCue(line_no=line_no, raw=raw, back_to_d="BACK TO D" in upper)
    if upper in ("VO",):
        return VOCue(line_no=line_no, raw=raw, cont=False)
    if upper in ("CONT VO", "CONTINUE VO"):
        return VOCue(line_no=line_no, raw=raw, cont=True)

    for keyword, cls in (("SOT", SOTCue), ("PKG", PKGCue)):
        if upper == keyword or upper.startswith(keyword + " "):
            duration_text = text[len(keyword) :].strip()
            seconds = parse_duration(duration_text) if duration_text else None
            return cls(
                line_no=line_no,
                raw=raw,
                seconds=seconds or 0.0,
                duration_text=duration_text,
            )

    shot_match = NON_CAMERA_SHOT_RE.match(text)
    if shot_match:
        return CameraCue(
            line_no=line_no,
            raw=raw,
            shot=" ".join(shot_match.group("shot").upper().split()),
            monitor=None,
            park_d=bool(shot_match.group("d")),
        )

    if upper.startswith("CAM"):
        m = CAMERA_RE.match(text)
        if not m:
            raise MarkupError(f"unparseable camera cue [{text}]", line_no, raw)
        shot = re.sub(r"\s+", "", m.group("shot")).upper()
        monitor = m.group("monitor")
        return CameraCue(
            line_no=line_no,
            raw=raw,
            shot=shot,
            monitor=re.sub(r"\s+", "", monitor).upper() if monitor else None,
            park_d=bool(m.group("d")),
        )

    if ANCHOR_RE.match(text):
        return AnchorCue(line_no=line_no, raw=raw, anchor=text)

    raise MarkupError(f"unrecognized cue [{text}]", line_no, raw)


def _copy_style(line: str) -> CopyStyle:
    stripped = line.strip()
    if NAT_SOUND_RE.match(stripped):
        return CopyStyle.NAT
    if stripped.startswith('"') or stripped.startswith("“"):
        return CopyStyle.SOUNDBITE
    return CopyStyle.ANCHOR


def parse_story(
    text: str,
    slug: str = "",
    kind: StoryKind = StoryKind.NEWS,
    first_line: int = 1,
) -> Story:
    """Parse one story's script. Raises MarkupError on malformed markup.

    A missing [#####] is *not* a parse error -- it is rule R3, reported by the
    validator, so a broken script still parses far enough to be diagnosed.
    """
    story = Story(slug=slug, kind=kind, line_no=first_line)
    segment = Segment(index=0)
    story.segments.append(segment)
    pending: Optional[Copy] = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            segment.elements.append(pending)
            pending = None

    for offset, raw in enumerate(text.splitlines()):
        line_no = first_line + offset
        line = raw.rstrip()
        if not line.strip():
            continue

        if line.strip() == END_OF_STORY:
            flush()
            story.terminated = True
            continue

        if story.terminated:
            raise MarkupError("content after [#####]", line_no, raw)

        if SEGMENT_BREAK_RE.match(line):
            flush()
            segment = Segment(index=len(story.segments))
            story.segments.append(segment)
            continue

        m = BRACKET_RE.match(line)
        if m:
            flush()
            segment.elements.append(_parse_bracket(m.group("inner"), line_no, raw))
            continue

        style = _copy_style(line)
        if pending is not None and pending.style is not style:
            flush()
        if pending is None:
            pending = Copy(line_no=line_no, raw=raw, lines=[], style=style)
        pending.lines.append(line.strip())

    flush()
    story.segments = [s for s in story.segments if s.elements] or [Segment(index=0)]
    for i, seg in enumerate(story.segments):
        seg.index = i
    return story


def serialize_story(story: Story) -> str:
    """Render a Story back to §4 markup."""
    out: list[str] = []
    for i, segment in enumerate(story.segments):
        if i:
            out.append("~~~New Segment~~~")
        for e in segment.elements:
            out.extend(_serialize_element(e))
    if story.terminated:
        out.append(END_OF_STORY)
    return "\n".join(out)


def _serialize_element(e: Element) -> list[str]:
    if isinstance(e, Copy):
        return list(e.lines)
    if isinstance(e, CameraCue):
        parts = [e.shot]
        if e.monitor:
            parts.append(e.monitor)
        body = " ".join(parts)
        if e.park_d:
            body += " - D"
        return [f"[{body}]"]
    if isinstance(e, OnCamCue):
        return ["[ON CAM - BACK TO D]" if e.back_to_d else "[ON CAM]"]
    if isinstance(e, AnchorCue):
        return [f"[{e.anchor}]"]
    if isinstance(e, CGCue):
        return [f"[CG: {e.text}]"]
    if isinstance(e, NoCGCue):
        return [f"[NO CG: {e.reason}]"]
    if isinstance(e, SourceCue):
        return [f"[SOURCE: {e.text}]"]
    if isinstance(e, NoteCue):
        return [f"[NOTE: {e.text}]"]
    if isinstance(e, ShotExceptionCue):
        return [f"[SHOT EXCEPTION: {e.reason}]"]
    if isinstance(e, MonitorCue):
        return [f"[MONITOR {e.kind}]"]
    if isinstance(e, TeaseCue):
        return [f"[TEASE: {e.text}]" if e.text else "[TEASE]"]
    if isinstance(e, VOCue):
        return ["[CONT VO]" if e.cont else "[VO]"]
    if isinstance(e, SOTCue):
        return [f"[SOT {e.duration_text}]" if e.duration_text else "[SOT]"]
    if isinstance(e, PKGCue):
        return [f"[PKG {e.duration_text}]" if e.duration_text else "[PKG]"]
    raise TypeError(f"cannot serialize {type(e).__name__}")


def parse_show(text: str, date: str = "") -> Show:
    """Parse a rundown file into a Show."""
    show = Show(date=date)
    block: Optional[Block] = None
    slug = ""
    kind = StoryKind.NEWS
    accepted = False
    submitted = False
    buffer: list[str] = []
    story_start = 1

    def close_story() -> None:
        nonlocal buffer
        if block is None or (not buffer and not slug):
            buffer = []
            return
        if not any(line.strip() for line in buffer):
            buffer = []
            return
        story = parse_story(
            "\n".join(buffer), slug=slug, kind=kind, first_line=story_start
        )
        story.accepted = accepted
        story.submitted = submitted or accepted
        block.stories.append(story)
        buffer = []

    for offset, raw in enumerate(text.splitlines()):
        line_no = offset + 1
        bm = BLOCK_HEADER_RE.match(raw)
        if bm:
            close_story()
            slug, kind, accepted, submitted = "", StoryKind.NEWS, False, False
            block = Block(half=int(bm.group(1)), label=bm.group(2).upper())
            show.blocks.append(block)
            continue

        sm = STORY_HEADER_RE.match(raw)
        if sm:
            close_story()
            if block is None:
                raise MarkupError("story before any block header", line_no, raw)
            header_slug = sm.group("slug")
            flag = _ACCEPTED_RE.search(header_slug)
            accepted = bool(flag and flag.group(1).lower() == "accepted")
            submitted = bool(flag)
            slug = _ACCEPTED_RE.sub("", header_slug).strip()
            kind = _STORY_KINDS[sm.group("kind").upper()]
            story_start = line_no + 1
            continue

        if raw.strip().startswith("#") and not raw.strip().startswith("[#"):
            continue  # comment line in a fixture

        buffer.append(raw)

    close_story()
    return show
