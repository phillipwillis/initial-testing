"""Shared test helpers."""

from __future__ import annotations

import os

from newscast.markup import parse_show, parse_story
from newscast.model import Block, Show, Story, StoryKind

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def fixture_show(name: str) -> Show:
    return parse_show(fixture(name))


def one_story_show(
    script: str,
    slug: str = "TEST",
    half: int = 1,
    label: str = "A",
    kind: StoryKind = StoryKind.NEWS,
) -> Show:
    """A one-block show holding a single story, for targeting one rule."""
    story = parse_story(script, slug=slug, kind=kind)
    return Show(blocks=[Block(half=half, label=label, stories=[story])])


def show_of(*stories: Story, half: int = 1, label: str = "A") -> Show:
    return Show(blocks=[Block(half=half, label=label, stories=list(stories))])


def codes(report) -> set[str]:
    return {v.code for v in report.violations}


def codes_at(report, severity) -> set[str]:
    return {v.code for v in report.violations if v.severity is severity}
