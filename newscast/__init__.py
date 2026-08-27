"""Newscast producer agent — domain model, markup parser, and rule engine.

Milestone 1 of the build order in CLAUDE.md §10: no LLM, no network. Everything
here is deterministic and individually testable.
"""

from newscast.config import ShowConfig, UNSET
from newscast.model import (
    Show,
    Block,
    Story,
    Segment,
    SegmentMode,
    StoryKind,
)
from newscast.markup import parse_story, parse_show, serialize_story, MarkupError
from newscast.readtime import estimate_read_time
from newscast.validator import validate_show, Violation, Severity, ValidationReport

__all__ = [
    "ShowConfig",
    "UNSET",
    "Show",
    "Block",
    "Story",
    "Segment",
    "SegmentMode",
    "StoryKind",
    "parse_story",
    "parse_show",
    "serialize_story",
    "MarkupError",
    "estimate_read_time",
    "validate_show",
    "Violation",
    "Severity",
    "ValidationReport",
]
