"""Addressing frames by path instead of by switching.

Inception is nested iframes: a login dialog frame, one frame per open show, a
Running Order Manager frame, a story editor frame, a CKEditor wysiwyg frame
inside that, and a CG editor frame beside it. The previous implementation drove
this with stateful `switch_to.frame()` calls, and most of its complexity was the
consequence: functions that scan every iframe hunting for the one they need,
`switch_to.parent_frame()` in `finally` blocks, retry loops around stale
elements, and a `time.sleep(20)` waiting for an editor to appear.

The problem with `switch_to` is that it is a *move*, so every function has to
know where it currently is. Any failure mid-sequence leaves the driver somewhere
unknown, and the next function starts from a bad place.

The fix is to stop tracking position. A `FramePath` says where an operation
belongs, as a sequence of matchers from the document root, and every operation
re-walks that path from `default_content` before it runs. Re-walking is cheap
next to a network round trip, it is idempotent, and it cannot inherit a bad
context from a failure that happened somewhere else.

Everything in this module is pure: matchers are predicates over frame
descriptors, so the matching logic is unit tested without a browser. Only
`enter()` and `frame()` in the driver module touch Selenium.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence


@dataclass(frozen=True)
class FrameDescriptor:
    """What is known about one iframe, without switching into it.

    `title` requires a switch to read in a real browser, so it may be None for
    a cross-origin frame; matchers must tolerate that.
    """

    index: int = 0
    title: Optional[str] = None
    src: str = ""
    id: str = ""

    def __str__(self) -> str:
        bits = [f"#{self.index}"]
        if self.title:
            bits.append(repr(self.title))
        if self.id:
            bits.append(f"id={self.id}")
        if self.src:
            bits.append(f"src=…{self.src[-40:]}")
        return " ".join(bits)


@dataclass(frozen=True)
class FrameSpec:
    """A predicate over frame descriptors, with a name for error messages."""

    describe: str
    predicate: Callable[[FrameDescriptor], bool]
    # Higher wins when several frames match — lets "exact title" beat
    # "title contains" without a second pass.
    rank: Callable[[FrameDescriptor], int] = lambda d: 0

    def __str__(self) -> str:
        return self.describe


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").split()).casefold()


def by_title(
    title: str, *, exact: bool = False, startswith: bool = False
) -> FrameSpec:
    """Match a frame by document title.

    Inception names show frames by their air time — "5:00 AM 01/22/26" — so
    `startswith` is the useful mode for shows, and `exact` for the singletons
    like "Running Order Manager".
    """
    wanted = _norm(title)

    def predicate(d: FrameDescriptor) -> bool:
        actual = _norm(d.title)
        if not actual:
            return False
        if exact:
            return actual == wanted
        if startswith:
            return actual.startswith(wanted)
        return wanted in actual

    def rank(d: FrameDescriptor) -> int:
        actual = _norm(d.title)
        if actual == wanted:
            return 3
        if actual.startswith(wanted):
            return 2
        return 1

    mode = "exact" if exact else "startswith" if startswith else "contains"
    return FrameSpec(f"title {mode} {title!r}", predicate, rank)


def by_src(fragment: str) -> FrameSpec:
    """Match on a fragment of the frame's src.

    The most durable handle Inception offers, because the paths are server
    routes rather than generated markup: `User/Authentication/Dialog`,
    `RunningOrderManager`, `BroadcastStory/View.do`.
    """
    wanted = fragment.casefold()

    def predicate(d: FrameDescriptor) -> bool:
        return wanted in (d.src or "").casefold()

    return FrameSpec(f"src contains {fragment!r}", predicate)


def by_id_prefix(prefix: str) -> FrameSpec:
    """Match on an id prefix — the CG editor opens as `view-10`, `view-11`…"""
    wanted = prefix.casefold()

    def predicate(d: FrameDescriptor) -> bool:
        return (d.id or "").casefold().startswith(wanted)

    return FrameSpec(f"id starts with {prefix!r}", predicate)


def any_of(*specs: FrameSpec) -> FrameSpec:
    """Match if any of the given specs match. Ranks by the best match."""
    describe = " or ".join(str(s) for s in specs)

    def predicate(d: FrameDescriptor) -> bool:
        return any(s.predicate(d) for s in specs)

    def rank(d: FrameDescriptor) -> int:
        return max((s.rank(d) for s in specs if s.predicate(d)), default=0)

    return FrameSpec(f"({describe})", predicate, rank)


def matches(spec: FrameSpec, descriptor: FrameDescriptor) -> bool:
    return spec.predicate(descriptor)


def resolve(
    spec: FrameSpec, descriptors: Sequence[FrameDescriptor]
) -> Optional[FrameDescriptor]:
    """The best frame matching `spec`, or None.

    Ties break towards the better-ranked match, then the earlier frame, so
    resolution is deterministic when Inception has two frames open with similar
    titles — which happens whenever two shows are open at once.
    """
    candidates = [d for d in descriptors if spec.predicate(d)]
    if not candidates:
        return None
    return max(candidates, key=lambda d: (spec.rank(d), -d.index))


# A frame path is just an ordered sequence of specs, root first.
FramePath = tuple[FrameSpec, ...]


def path(*specs: FrameSpec) -> FramePath:
    return tuple(specs)


def describe_path(frame_path: FramePath) -> str:
    return " > ".join(str(s) for s in frame_path) or "(document root)"


# --------------------------------------------------------------------------
# Known Inception frames, from the previous working implementation
# --------------------------------------------------------------------------

LOGIN_DIALOG = by_src("User/Authentication/Dialog")
RUNNING_ORDER_MANAGER = any_of(
    by_src("RunningOrderManager"), by_title("Running Order Manager", exact=True)
)
STORY_EDITOR = by_src("BroadcastStory/View.do")
CG_EDITOR = by_id_prefix("view-")


def show_frame(show_label: str) -> FrameSpec:
    """The frame for one open show.

    Inception titles these by air time and date — "5:00 AM 01/22/26" — so the
    label matches as a prefix. Ranking means that when several shows are open,
    an exact title still wins over a prefix.
    """
    return by_title(show_label, startswith=True)
