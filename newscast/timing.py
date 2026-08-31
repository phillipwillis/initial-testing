"""Story and block timing.

Time on air is not the sum of everything written down. Copy under [VO] is read
live and counts; a reporter track inside a [PKG] is already inside the package's
declared duration and must not be counted twice; a soundbite plays with the
anchor mic off (§3), so only its cue duration counts.
"""

from __future__ import annotations

from dataclasses import dataclass

from newscast.config import ShowConfig
from newscast.model import (
    Block,
    Copy,
    CopyStyle,
    OnCamCue,
    PKGCue,
    Segment,
    SOTCue,
    Story,
    VideoCue,
    VOCue,
)
from newscast.readtime import estimate_read_time


@dataclass(frozen=True)
class Timing:
    read_seconds: float   # live anchor copy
    video_seconds: float  # declared SOT/PKG durations

    @property
    def total(self) -> float:
        return round(self.read_seconds + self.video_seconds, 1)


def story_timing(story: Story, config: ShowConfig | None = None) -> Timing:
    config = config or ShowConfig()
    read = 0.0
    video = 0.0
    inside_video = False

    for segment in story.segments:
        for e in segment.elements:
            if isinstance(e, VideoCue):
                video += e.seconds
                inside_video = True
            elif isinstance(e, OnCamCue):
                inside_video = False
            elif isinstance(e, VOCue):
                # [VO] and [CONT VO] both put the anchor back on live mic.
                inside_video = False
            elif isinstance(e, Copy) and e.style is CopyStyle.ANCHOR:
                if not inside_video:
                    read += estimate_read_time(e.lines, config)

    return Timing(read_seconds=round(read, 1), video_seconds=round(video, 1))


def story_seconds(story: Story, config: ShowConfig | None = None) -> float:
    return story_timing(story, config).total


def segment_read_seconds(segment: Segment, config: ShowConfig | None = None) -> float:
    """Live read time inside one segment, using the same in-video accounting."""
    config = config or ShowConfig()
    total = 0.0
    inside_video = False
    for e in segment.elements:
        if isinstance(e, (SOTCue, PKGCue)):
            inside_video = True
        elif isinstance(e, OnCamCue) or isinstance(e, VOCue):
            inside_video = False
        elif isinstance(e, Copy) and e.style is CopyStyle.ANCHOR and not inside_video:
            total += estimate_read_time(e.lines, config)
    return round(total, 1)


def block_seconds(block: Block, config: ShowConfig | None = None) -> float:
    return round(sum(story_seconds(s, config) for s in block.stories), 1)


def vo_stretches(story: Story, config: ShowConfig | None = None) -> list[float]:
    """Read time of each continuous voice-over stretch in the story.

    A stretch opens at [VO] or [CONT VO] and closes at the next video cue or
    [ON CAM].
    """
    config = config or ShowConfig()
    out: list[float] = []
    current: float | None = None
    for segment in story.segments:
        for e in segment.elements:
            if isinstance(e, VOCue):
                if current is not None:
                    out.append(round(current, 1))
                current = 0.0
            elif isinstance(e, (VideoCue, OnCamCue)):
                if current is not None:
                    out.append(round(current, 1))
                    current = None
            elif isinstance(e, Copy) and e.style is CopyStyle.ANCHOR:
                if current is not None:
                    current += estimate_read_time(e.lines, config)
    if current is not None:
        out.append(round(current, 1))
    return [s for s in out if s > 0]
