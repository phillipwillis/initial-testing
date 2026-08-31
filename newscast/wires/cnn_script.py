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

# Section markers, in the spellings the wire actually uses.
LEAD_IN_MARKERS = ("--LEAD IN--", "--LEAD-IN--", "--LEADIN--", "LEAD IN", "LEAD-IN")
VO_SCRIPT_MARKERS = ("--VO SCRIPT--", "--VOSCRIPT--", "VO SCRIPT", "VO-SCRIPT")
PKG_MARKERS = ("--REPORTER PKG-AS FOLLOWS--", "--PKG SCRIPT--", "--PACKAGE SCRIPT--")
TAG_MARKERS = ("--TAG--", "--SUGGESTED TAG--")
SUPERS_MARKERS = ("--SUPERS--",)
END_MARKERS = (
    "-----END-----CNN.SCRIPT-----",
    "-----END-----",
    "--KEYWORD TAGS--",
    "--KEYWORDS--",
)

# Footage types that mean "a reporter package", not anchor copy.
PACKAGE_FOOTAGE_TYPES = frozenset({"PKG", "DONUT", "LOOK LIVE"})

_TIME_SPAN_RE = re.compile(r"(?:\d{1,2}:|:)\d{2}\s*-\s*(?:\d{1,2}:|:)\d{2}")


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
    tag: str = ""
    supers: list[Super] = field(default_factory=list)
    raw: str = ""

    @property
    def is_package(self) -> bool:
        return self.footage_type.upper() in PACKAGE_FOOTAGE_TYPES

    @property
    def body(self) -> str:
        """The main copy, whichever section the wire put it in."""
        return self.pkg_body if self.is_package else self.vo_script


def _normalise(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _line_field(text: str, label: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _between(text: str, start: str, end: str) -> str:
    pattern = re.compile(rf"(?is){re.escape(start)}\s*(.*?)\s*{re.escape(end)}")
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _between_any(
    text: str, starts: Iterable[str], ends: Iterable[str]
) -> str:
    """First non-empty section found across every spelling combination."""
    for start in starts:
        if start not in text.upper() and start not in text:
            continue
        for end in ends:
            found = _between(text, start, end)
            if found:
                return found
    return ""


def _after(text: str, starts: Iterable[str], ends: Iterable[str]) -> str:
    """A section that runs to an end marker, or to the end of the script."""
    for start in starts:
        match = re.search(re.escape(start), text, re.I)
        if not match:
            continue
        tail = text[match.end():].lstrip("\n")
        cut = len(tail)
        for end in ends:
            stop = re.search(re.escape(end), tail, re.I)
            if stop:
                cut = min(cut, stop.start())
        section = tail[:cut].strip()
        if section:
            return section
    return ""


def _is_timecode(line: str) -> bool:
    return bool(_TIME_SPAN_RE.search(line))


def _looks_like_a_name(line: str) -> bool:
    if any(ch.isdigit() for ch in line):
        return False
    if not (3 <= len(line) <= 60):
        return False
    if len(line.split()) < 2:
        return False
    return line[0].isalpha() and line[0].isupper()


def parse_supers(block: str) -> list[Super]:
    """Parse the SUPERS block into name / title / timecode triples.

    The block is a run of `:00-:06` timecodes, each followed by a name line and
    a title line. A name with no title after it is dropped — in real wire copy
    that pattern is a location or a slate, not a person.
    """
    lines = [line.strip() for line in _normalise(block).splitlines() if line.strip()]

    supers: list[Super] = []
    pending_name: Optional[str] = None
    pending_timecode = ""
    last_timecode = ""
    after_timecode = False

    for line in lines:
        if _is_timecode(line):
            pending_name = None
            last_timecode = line
            after_timecode = True
            continue

        if pending_name is not None:
            supers.append(
                Super(name=pending_name, title=line, timecode=pending_timecode)
            )
            pending_name = None
            after_timecode = False
            continue

        if after_timecode and _looks_like_a_name(line):
            pending_name = line
            pending_timecode = last_timecode
            after_timecode = False
            continue

        after_timecode = False

    return supers


def parse_wire_script(raw: str) -> WireScript:
    """Parse a CNN Newsource script into its sections."""
    text = _normalise(raw)

    lead_in_ends = VO_SCRIPT_MARKERS + PKG_MARKERS + TAG_MARKERS + END_MARKERS
    vo_ends = TAG_MARKERS + END_MARKERS

    script = WireScript(
        raw=raw,
        title=_line_field(text, "Title"),
        trt=_line_field(text, "TRT"),
        footage_type=_line_field(text, "Footage Type").upper(),
        lead_in=_between_any(text, LEAD_IN_MARKERS, lead_in_ends),
        vo_script=_after(text, VO_SCRIPT_MARKERS, vo_ends),
        pkg_body=_after(text, PKG_MARKERS, vo_ends),
        tag=_after(text, TAG_MARKERS, END_MARKERS),
        supers=parse_supers(_between_any(text, SUPERS_MARKERS, LEAD_IN_MARKERS + PKG_MARKERS + VO_SCRIPT_MARKERS)),
    )

    # Last resort: a script with no markers at all still has copy in it, and a
    # producer would rather see it than an empty story.
    if not script.lead_in and not script.vo_script and not script.pkg_body:
        match = re.search(r"(?is)\bScript:\s*(.+)$", text)
        script.vo_script = (match.group(1) if match else text).strip()

    return script
