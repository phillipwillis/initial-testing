"""Parser for the CNN Newsource script format.

The wire ships a plain-text script with section markers. This turns one into
fields the story assembler can use (§6 phase 3, §8 `wire_expand`).

Marker vocabulary and field names are lifted from the previous working
implementation, so unlike the DOM selectors these are confirmed against real
wire copy rather than inferred from screenshots. The markers vary — CNN writes
`--LEAD IN--`, `--LEAD-IN--` and `--LEADIN--` for the same thing — so every
section accepts a list of spellings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Section markers. Real wire copy is inconsistent about spacing inside and
# around the dashes — one story carries "--TAG--" and the next "--TAG --" — so
# these are matched as patterns that tolerate whitespace anywhere a human might
# have left one, not as literal strings.
LEAD_IN_MARKERS = ("LEAD IN", "LEAD-IN", "LEADIN")
VO_SCRIPT_MARKERS = ("VO SCRIPT", "VOSCRIPT", "VO-SCRIPT")
PKG_MARKERS = ("REPORTER PKG-AS FOLLOWS", "PKG SCRIPT", "PACKAGE SCRIPT")
SOT_MARKERS = ("SOT",)
TAG_MARKERS = ("TAG", "SUGGESTED TAG")
SUPERS_MARKERS = ("SUPERS",)
END_MARKERS = ("END", "KEYWORD TAGS", "KEYWORDS")

# Footage types that mean "a reporter package", not anchor copy.
PACKAGE_FOOTAGE_TYPES = frozenset({"PKG", "DONUT", "LOOK LIVE"})

_TIME_SPAN_RE = re.compile(r"(?:\d{1,2}:|:)\d{2}\s*-\s*(?:\d{1,2}:|:)\d{2}")


def _marker_pattern(name: str) -> str:
    """A marker as a pattern: dashes, optional spaces, the name, more dashes.

    Matches `--TAG--`, `--TAG --`, `-- TAG --` and `-----END-----` alike, with
    the words inside separated by any whitespace.
    """
    words = r"[\s-]*".join(re.escape(word) for word in name.split())
    return rf"-{{2,}}\s*{words}\s*-*"


def _find_marker(text: str, name: str, start: int = 0):
    return re.compile(_marker_pattern(name), re.I).search(text, start)


@dataclass
class Super:
    """One lower-third from the wire's SUPERS block.

    `timecode` is the wire's own marker for where the person speaks. Useful as
    a hint, but §11.7 makes the ASR transcript authoritative for in/out points:
    wires sometimes ship an old script against a revamped package, so these
    numbers can point at the wrong moment. Trust them for *who and what*, not
    for *when*.
    """

    name: str = ""
    title: str = ""
    timecode: str = ""


@dataclass
class WireScript:
    title: str = ""
    trt: str = ""
    footage_type: str = ""
    lead_in: str = ""
    vo_script: str = ""
    pkg_body: str = ""
    sot_body: str = ""    # the transcript of a soundbite, under "--SOT--"
    tag: str = ""
    supers: list[Super] = field(default_factory=list)
    raw: str = ""

    @property
    def is_package(self) -> bool:
        """A package either says so, or carries a reporter track.

        The expanded panel on the listing has no `Footage Type:` line — that
        appears in the search result the previous implementation read — so the
        presence of the reporter section has to count on its own.
        """
        return bool(self.pkg_body) or self.footage_type.upper() in PACKAGE_FOOTAGE_TYPES

    @property
    def body(self) -> str:
        """The main copy, whichever section the wire put it in."""
        if self.is_package:
            return self.pkg_body or self.vo_script
        return self.vo_script or self.pkg_body


def _normalise(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _line_field(text: str, label: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _section(text: str, starts: Iterable[str], ends: Iterable[str]) -> str:
    """The text between the first of `starts` and the nearest following end.

    Runs to the end of the script when no end marker follows, which is what a
    truncated or unterminated section needs.
    """
    for name in starts:
        opening = _find_marker(text, name)
        if not opening:
            continue
        tail = text[opening.end():].lstrip("\n")
        cut = len(tail)
        for end_name in ends:
            closing = _find_marker(tail, end_name)
            if closing:
                cut = min(cut, closing.start())
        section = tail[:cut].strip()
        if section:
            return section
    return ""


def _is_timecode(line: str) -> bool:
    return bool(_TIME_SPAN_RE.search(line))


_DAYS = frozenset(
    "monday tuesday wednesday thursday friday saturday sunday".split()
)


def _strip_slate(lines: list[str]) -> list[str]:
    """Drop the leading day and location.

    A SUPERS block opens with a slate — the day the material was shot and where
    — before any supers:

        Sunday
        Los Angeles
        Dr. Quynh Vo-Hanser
        Kaiser Permanente South Bay

    The day is recognisable, and the line after it is the location.
    """
    if lines and lines[0].strip().lower() in _DAYS:
        return lines[2:] if len(lines) > 1 else []
    return lines


def parse_supers(block: str) -> list[Super]:
    """Parse the SUPERS block into name / title / timecode triples.

    Two shapes appear in real copy. A package times each super:

        Saturday · Seattle · :05 - :07 · Kelly · Seattle Resident

    while a single soundbite has no timecodes at all, because there is only one
    speaker:

        Sunday · Los Angeles · Dr. Quynh Vo-Hanser · Kaiser Permanente South Bay

    Where timecodes exist they identify the fields by position after them,
    rather than by a guess at what a name looks like — real supers include
    single-word names like "Kelly", which any such heuristic drops. Where there
    are none, the lines after the slate pair up as name and title.

    The pairing fallback is an inference from two samples. More SUPERS blocks
    without timecodes would confirm it.
    """
    lines = [line.strip() for line in _normalise(block).splitlines() if line.strip()]
    if not lines:
        return []

    if not any(_is_timecode(line) for line in lines):
        rest = _strip_slate(lines)
        return [
            Super(name=rest[i], title=rest[i + 1])
            for i in range(0, len(rest) - 1, 2)
        ]

    supers: list[Super] = []
    index = 0
    while index < len(lines):
        if not _is_timecode(lines[index]):
            index += 1
            continue

        timecode = lines[index]
        index += 1
        if index >= len(lines) or _is_timecode(lines[index]):
            continue

        name = lines[index]
        index += 1
        if index >= len(lines) or _is_timecode(lines[index]):
            continue  # a name with no title is a slate

        supers.append(Super(name=name, title=lines[index], timecode=timecode))
        index += 1

    return supers


def parse_wire_script(raw: str) -> WireScript:
    """Parse a CNN Newsource script into its sections."""
    text = _normalise(raw)

    body_starts = VO_SCRIPT_MARKERS + PKG_MARKERS + SOT_MARKERS
    lead_in_ends = body_starts + TAG_MARKERS + END_MARKERS
    # A body section ends where a soundbite section starts. The ordinary VOSOT
    # shape is --VO SCRIPT-- copy --SOT-- bite --TAG--, and without SOT here the
    # bite bleeds into the anchor's copy and gets read on air.
    body_ends = SOT_MARKERS + TAG_MARKERS + END_MARKERS
    supers_ends = LEAD_IN_MARKERS + body_starts

    script = WireScript(
        raw=raw,
        title=_line_field(text, "Title"),
        trt=_line_field(text, "TRT"),
        footage_type=_line_field(text, "Footage Type").upper(),
        lead_in=_section(text, LEAD_IN_MARKERS, lead_in_ends),
        vo_script=_section(text, VO_SCRIPT_MARKERS, body_ends),
        pkg_body=_section(text, PKG_MARKERS, body_ends),
        sot_body=_section(text, SOT_MARKERS, VO_SCRIPT_MARKERS + TAG_MARKERS + END_MARKERS),
        tag=_section(text, TAG_MARKERS, END_MARKERS),
        supers=parse_supers(_section(text, SUPERS_MARKERS, supers_ends)),
    )

    # Last resort: a script with no markers at all still has copy in it, and a
    # producer would rather see it than an empty story.
    if not script.lead_in and not script.vo_script and not script.pkg_body:
        match = re.search(r"(?is)\bScript:\s*(.+)$", text)
        script.vo_script = (match.group(1) if match else text).strip()

    return script
