"""Domain model: show / block / story / segment / element.

Structure follows CLAUDE.md §1-§3. Cue elements follow the §4 markup table.
Cues marked EXTENSION are not in §4 -- they exist because a §5 rule is not
checkable without them. Each is listed in CLAUDE.md §13 for Phil to confirm or
replace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Iterator, Optional


class SegmentMode(Enum):
    RDR = "RDR"
    VO = "VO"
    SOT = "SOT"
    SOTVO = "SOTVO"
    PKG = "PKG"


class StoryKind(Enum):
    NEWS = "NEWS"
    BUMP = "BUMP"
    WEATHER = "WEATHER"
    OTHER = "OTHER"


class CopyStyle(Enum):
    ANCHOR = "ANCHOR"        # read by an anchor, written ALL CAPS (§4)
    SOUNDBITE = "SOUNDBITE"  # transcription, mixed case in quotes (§4)
    NAT = "NAT"              # natural sound, -like this- (§4)


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------


@dataclass
class Element:
    line_no: int = field(default=0, compare=False)
    raw: str = field(default="", compare=False)


@dataclass
class CameraCue(Element):
    """[CAM1 OX1] / [CAM1 OX1 - D]"""

    shot: str = "CAM1"
    monitor: Optional[str] = None
    park_d: bool = False


@dataclass
class OnCamCue(Element):
    """[ON CAM] / [ON CAM - BACK TO D]"""

    back_to_d: bool = False


@dataclass
class AnchorCue(Element):
    """[MEGAN] -- and, for a dual read, [MEGAN/JAY]."""

    anchor: str = ""

    @property
    def names(self) -> list[str]:
        return [n.strip() for n in re.split(r"[/&]", self.anchor) if n.strip()]

    @property
    def is_dual(self) -> bool:
        return len(self.names) > 1


@dataclass
class CGCue(Element):
    """[CG: ...]"""

    text: str = ""


@dataclass
class NoCGCue(Element):
    """[NO CG: reason] -- EXTENSION. R4 allows exemptions "explicitly"; this is
    how a segment declares one."""

    reason: str = ""


@dataclass
class VOCue(Element):
    """[VO] / [CONT VO]"""

    cont: bool = False


@dataclass
class VideoCue(Element):
    """Base for cues that roll a video file (and therefore occupy D)."""

    seconds: float = 0.0
    duration_text: str = ""


@dataclass
class SOTCue(VideoCue):
    """[SOT 0:13]"""


@dataclass
class PKGCue(VideoCue):
    """[PKG 1:25]"""


@dataclass
class SourceCue(Element):
    """[SOURCE: ...] -- EXTENSION, required by R15."""

    text: str = ""


@dataclass
class NoteCue(Element):
    """[NOTE: ...] -- EXTENSION, the editor note required by R15."""

    text: str = ""


@dataclass
class ShotExceptionCue(Element):
    """[SHOT EXCEPTION: reason] -- EXTENSION. R11 permits breaking the block's
    shot only when flagged; this is the flag."""

    reason: str = ""


@dataclass
class MonitorCue(Element):
    """[MONITOR PLACEHOLDER] / [MONITOR DUPE] -- EXTENSION, the R1 mitigation
    for back-to-back D-channel stories."""

    kind: str = "PLACEHOLDER"


@dataclass
class TeaseCue(Element):
    """[TEASE: ...] -- EXTENSION. R10 needs a bump to be identifiable whether it
    is its own rundown element or appended to the last story (§11.11)."""

    text: str = ""


@dataclass
class Copy(Element):
    """A run of spoken lines."""

    lines: list[str] = field(default_factory=list)
    style: CopyStyle = CopyStyle.ANCHOR

    @property
    def text(self) -> str:
        return " ".join(self.lines)


# --------------------------------------------------------------------------
# Segment
# --------------------------------------------------------------------------


@dataclass
class Segment:
    """A run of elements with a single production mode (§1)."""

    elements: list[Element] = field(default_factory=list)
    index: int = 0

    def of_type(self, *types: type) -> list[Element]:
        return [e for e in self.elements if isinstance(e, types)]

    @property
    def video_cues(self) -> list[VideoCue]:
        return [e for e in self.elements if isinstance(e, VideoCue)]

    @property
    def cgs(self) -> list[CGCue]:
        return [e for e in self.elements if isinstance(e, CGCue)]

    @property
    def anchor_copy(self) -> list[Copy]:
        return [
            e
            for e in self.elements
            if isinstance(e, Copy) and e.style is CopyStyle.ANCHOR
        ]

    @property
    def anchors(self) -> list[str]:
        out: list[str] = []
        for e in self.elements:
            if isinstance(e, AnchorCue):
                out.extend(e.names)
        return out

    @property
    def mode(self) -> SegmentMode:
        """Production mode, derived from the cues present.

        A SOT segment that keeps talking over new video without returning to
        camera is a SOTVO (§3).
        """
        if any(isinstance(e, PKGCue) for e in self.elements):
            return SegmentMode.PKG
        if any(isinstance(e, SOTCue) for e in self.elements):
            sot_at = next(
                i for i, e in enumerate(self.elements) if isinstance(e, SOTCue)
            )
            tail = self.elements[sot_at + 1 :]
            if any(isinstance(e, VOCue) and e.cont for e in tail):
                return SegmentMode.SOTVO
            return SegmentMode.SOT
        if any(isinstance(e, VOCue) for e in self.elements):
            return SegmentMode.VO
        return SegmentMode.RDR

    @property
    def video_seconds(self) -> float:
        return sum(c.seconds for c in self.video_cues)

    @property
    def uses_d_channel(self) -> bool:
        """True if this segment rolls a video file, which lands in D (§1)."""
        return bool(self.video_cues)

    def returns_to_camera(self) -> bool:
        """True if the segment comes back on camera after rolling video."""
        seen_video = False
        for e in self.elements:
            if isinstance(e, VideoCue):
                seen_video = True
            elif isinstance(e, OnCamCue) and seen_video:
                return True
        return False


# --------------------------------------------------------------------------
# Story
# --------------------------------------------------------------------------


@dataclass
class Story:
    """One item in the rundown, composed of one or more segments (§1)."""

    slug: str = ""
    kind: StoryKind = StoryKind.NEWS
    segments: list[Segment] = field(default_factory=list)
    terminated: bool = False  # saw [#####]
    accepted: bool = False    # locked by the human producer (§6 phase 5)
    submitted: bool = False
    line_no: int = 0

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    @property
    def elements(self) -> list[Element]:
        out: list[Element] = []
        for s in self.segments:
            out.extend(s.elements)
        return out

    @property
    def modes(self) -> list[SegmentMode]:
        return [s.mode for s in self.segments]

    @property
    def form(self) -> str:
        """Composite form string, e.g. "VOSOT" (§3 composite forms).

        Derived from the element sequence rather than the segment split, because
        the §3 examples put composites both across and within segment breaks.
        """
        parts: list[str] = []
        for e in self.elements:
            if isinstance(e, VOCue):
                parts.append("VO")
            elif isinstance(e, SOTCue):
                parts.append("SOT")
            elif isinstance(e, PKGCue):
                parts.append("PKG")
        if not parts:
            return "RDR"
        collapsed: list[str] = []
        for p in parts:
            if not collapsed or collapsed[-1] != p:
                collapsed.append(p)
        return "".join(collapsed)

    @property
    def anchors(self) -> list[str]:
        seen: list[str] = []
        for a in (a for s in self.segments for a in s.anchors):
            if a not in seen:
                seen.append(a)
        return seen

    @property
    def shots(self) -> list[str]:
        return [
            e.shot for e in self.elements if isinstance(e, CameraCue)
        ]

    @property
    def video_seconds(self) -> float:
        return sum(s.video_seconds for s in self.segments)

    @property
    def uses_d_channel(self) -> bool:
        return any(s.uses_d_channel for s in self.segments)

    @property
    def pkg_count(self) -> int:
        return len([e for e in self.elements if isinstance(e, PKGCue)])

    @property
    def is_tease(self) -> bool:
        return self.kind is StoryKind.BUMP or any(
            isinstance(e, TeaseCue) for e in self.elements
        )


# --------------------------------------------------------------------------
# Block and show
# --------------------------------------------------------------------------


@dataclass
class Block:
    """A run of stories between breaks (§1)."""

    half: int
    label: str
    stories: list[Story] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.half}{self.label}"

    def __iter__(self) -> Iterator[Story]:
        return iter(self.stories)

    @property
    def pkg_count(self) -> int:
        return sum(s.pkg_count for s in self.stories)


@dataclass
class Show:
    """One newscast: two half hours, four blocks each (§2)."""

    blocks: list[Block] = field(default_factory=list)
    date: str = ""

    def __iter__(self) -> Iterator[Block]:
        return iter(self.blocks)

    def block(self, half: int, label: str) -> Block:
        for b in self.blocks:
            if b.half == half and b.label == label.upper():
                return b
        raise KeyError(f"no block {half}{label} in show")

    @property
    def stories(self) -> Iterable[Story]:
        for b in self.blocks:
            yield from b.stories
