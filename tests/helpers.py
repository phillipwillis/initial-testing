"""Shared test helpers."""

from __future__ import annotations

import os

import dataclasses

from newscast.config import UNSET, ShowConfig
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


def bare_config(**kwargs) -> ShowConfig:
    """A config with the per-block pattern stripped out.

    Targeted rule tests use this so that a story written to exercise one rule
    does not also trip R11, R12 or R14 for being on the wrong shot, read by the
    wrong anchor, or in a block that is 4 minutes short.
    """
    base = ShowConfig(**kwargs)
    blocks = tuple(
        dataclasses.replace(
            b,
            default_shot=UNSET,
            open_shot=UNSET,
            anchors=UNSET,
            read_mode=UNSET,
            solo_anchor=UNSET,
            closing_anchor=UNSET,
            budget_range=UNSET,
        )
        for b in base.blocks
    )
    return dataclasses.replace(base, blocks=blocks)
