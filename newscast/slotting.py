"""Slotting — where a wire story goes and in what order (§6 phase 2, §11.27).

Two things settle this section, and they pull in opposite directions.

**Placement is tonal, not tabular.** There is no rule that says a shooting goes
in B. It usually does, but it moves with the day, and the right block depends on
what else is in the pool — which is a judgement, and therefore the model's, not
a lookup table's. What this module does is give the model a *shape* to fill:
every surviving story gets a **primary block**, a **backup block**, and a
**heaviness weight from 0 to 1**.

**Ordering is not a judgement.** Once heaviness exists, §2's "heavy to light" is
arithmetic: within a block, heavier runs first. That is checkable, so it is
checked here rather than hoped for in a prompt (§12).

The heuristic in this file plays the same role `newscast.scoring` does for
grading: a deterministic stand-in that runs with no network, keeps the pipeline
demonstrable, and is the thing the model's answers get compared against. When
the model supplies a placement, `place_pool` takes it; when it does not, the
heuristic fills in.

**Wire stories fill the gaps the human's local stories leave.** The human's
placements are fixed points (§6 phase 0). A `Hole` is what is left of a block
after them, and filling holes is the whole job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .config import ShowConfig
from .scoring import StoryGroup, compile_words
from .wires.stub import StoryStub

# §11.27's own examples, at the weights Phil gave them: a shooting is 0.9–1.0, a
# small business going under is sad but lighter at 0.6–0.7.
HEAVY_WORDS = (
    "shooting", "shooter", "shot", "kill*", "dead", "death*", "fatal*", "homicide",
    "murder*", "stabb*", "crash", "collision", "wreck", "fire", "explosion",
    "evacuat*", "flood*", "tornado", "hurricane", "earthquake", "war", "strike*",
    "attack*", "bomb*", "missile*", "arrest*", "charged", "indict*", "manhunt",
    "standoff", "overdose", "outbreak", "recall", "missing", "drown*",
)
MIDDLE_WORDS = (
    "closure", "closing", "closes", "bankrupt*", "layoff*", "laid off", "lawsuit",
    "sued", "protest*", "vote", "votes", "council", "commission", "budget",
    "tax*", "bond", "hearing", "trial", "sentenc*", "investigation", "shortage",
    "delay*", "outage", "construction", "detour", "road work",
)
LIGHT_WORDS = (
    "festival", "parade", "fair", "ribbon cutting", "grand opening", "reunion",
    "birthday", "puppy", "puppies", "kitten*", "dog", "zoo", "record-breaking",
    "viral", "adorable", "heartwarming", "surprise*", "reunited", "prom",
    "graduation", "award*", "premiere", "trailer", "box office", "concert",
    "auction", "celebrat*",
)
ENTERTAINMENT_WORDS = (
    "movie", "film", "premiere", "trailer", "box office", "album", "single",
    "tour", "concert", "netflix", "hulu", "disney", "grammy*", "oscar*", "emmy*",
    "celebrity", "actor", "actress", "singer", "rapper", "auction", "star",
)

_HEAVY_RE = compile_words(HEAVY_WORDS)
_MIDDLE_RE = compile_words(MIDDLE_WORDS)
_LIGHT_RE = compile_words(LIGHT_WORDS)
_ENTERTAINMENT_RE = compile_words(ENTERTAINMENT_WORDS)

# Where a story lands when nothing about it says otherwise. The C blocks are
# the flex, which is what §2 calls them.
DEFAULT_PRIMARY = "1C"

# §13.4-style assumptions. A story's real length comes from the copy once it is
# written (`estimate_read_time`) or from the transcript for a video file (§15) —
# neither of which exists yet at slotting time, so a hole is packed against a
# planned length by form. Invented, and due for tuning against real rundowns.
TARGET_SECONDS = {
    "RDR": 12.0,
    "VO": 30.0,
    "SOT": 45.0,
    "VOSOT": 45.0,
    "SOTVO": 45.0,
    "VOSOTVOSOT": 70.0,
    "PKG": 110.0,
}
DEFAULT_TARGET_SECONDS = 30.0


@dataclass
class Hole:
    """What is left of a block after the human's local stories.

    `seconds` is the gap the agent may fill, not the block's whole budget.
    """

    half: int
    label: str
    seconds: float
    max_pkgs: int = 2

    @property
    def name(self) -> str:
        return f"{self.half}{self.label}"


@dataclass
class Placement:
    """One story's slotting decision (§11.27).

    `primary` is where it should go, `backup` is where it goes if it loses that
    slot — so a bumped story has somewhere to fall rather than being re-graded
    from scratch. `heaviness` runs 0..1 and orders the block.
    """

    group: StoryGroup
    primary: str = DEFAULT_PRIMARY
    backup: str = ""
    heaviness: float = 0.5
    target_seconds: float = DEFAULT_TARGET_SECONDS
    reasons: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.group.slug

    @property
    def is_package(self) -> bool:
        return self.group.stub.footage_type.upper() in {"PKG", "DONUT", "LOOK LIVE"}

    def explain(self) -> str:
        where = f"{self.primary}→{self.backup}" if self.backup else self.primary
        return (
            f"{where:9} heaviness {self.heaviness:.2f}  "
            f"{self.target_seconds:5.0f}s  {self.slug}"
        )


# ---------------------------------------------------------------------------
# Heaviness
# ---------------------------------------------------------------------------


def _text_of(stub: StoryStub) -> str:
    return f"{stub.slug} {stub.teaser}".lower()


def heaviness(stub: StoryStub) -> tuple[float, list[str]]:
    """How hard the story is, 0..1 (§11.27).

    Heavy words dominate: a story that mentions a shooting is a shooting story
    however many festival words follow it. Light words only pull down a story
    nothing heavier is claiming.
    """
    text = _text_of(stub)
    reasons: list[str] = []

    heavy = len(_HEAVY_RE.findall(text))
    middle = len(_MIDDLE_RE.findall(text))
    light = len(_LIGHT_RE.findall(text))

    if heavy:
        weight = min(1.0, 0.85 + 0.05 * heavy)
        reasons.append(f"hard news ({heavy} marker(s))")
    elif middle:
        weight = min(0.75, 0.6 + 0.05 * middle)
        reasons.append(f"consequential but not hard ({middle} marker(s))")
    elif light:
        weight = max(0.15, 0.35 - 0.05 * light)
        reasons.append(f"talker ({light} marker(s))")
    else:
        weight = 0.5
        reasons.append("nothing in the slug says how heavy this is")

    return round(weight, 2), reasons


def is_entertainment(stub: StoryStub) -> bool:
    """§2 — the second D block is entertainment, which is a constraint.

    §6 phase 2: if no entertainment story ranks highly the block still needs
    one, so eligibility has to be knowable independently of rank.
    """
    return bool(_ENTERTAINMENT_RE.search(_text_of(stub)))


def target_seconds(stub: StoryStub) -> float:
    return TARGET_SECONDS.get(stub.footage_type.upper(), DEFAULT_TARGET_SECONDS)


# ---------------------------------------------------------------------------
# Primary and backup blocks
# ---------------------------------------------------------------------------


def _tonal_blocks(stub: StoryStub, weight: float) -> tuple[str, str, str]:
    """The stand-in for the model's judgement: primary, backup, and why.

    Read this as "where this story would go on an ordinary day", not as a rule.
    §11.27 is explicit that there is no rule — a shooting usually lands in B and
    moves with the day — so the model overrides this whenever it has a reason,
    and this only has to be defensible when the model has nothing to say.
    """
    local = _is_local(stub)

    if local and weight >= 0.6:
        return "1A", "2A", "local and hard — the A block is the local lead (§2)"
    if local:
        return "1D", "2C", "local, but light — the D block is fun local (§2)"
    if is_entertainment(stub):
        return "2D", "1C", "entertainment closes the show (§2)"
    if weight >= 0.85:
        return "1B", "2B", "hard national — B is national quick hits (§2)"
    if weight <= 0.35:
        return "1C", "2D", "a talker, and C is trending and uplifting (§2)"
    return "2B", "2C", "national, middling weight — B, with the flex block behind it"


def _is_local(stub: StoryStub) -> bool:
    """Reuses the grader's home-market list so the two agree on 'local'."""
    from .scoring import _HOME_RE

    return bool(_HOME_RE.search(_text_of(stub)))


def place_group(
    group: StoryGroup,
    override: Optional[Placement] = None,
) -> Placement:
    """One story's placement, heuristic unless the model supplied one."""
    stub = group.stub
    weight, reasons = heaviness(stub)
    primary, backup, why = _tonal_blocks(stub, weight)
    placement = Placement(
        group=group,
        primary=primary,
        backup=backup,
        heaviness=weight,
        target_seconds=target_seconds(stub),
        reasons=reasons + [why],
    )
    if override is None:
        return placement

    # A model answer wins on the judgement calls and inherits everything it did
    # not speak to, so a partial answer is still usable.
    return Placement(
        group=group,
        primary=override.primary or placement.primary,
        backup=override.backup or placement.backup,
        heaviness=override.heaviness if override.heaviness is not None else weight,
        target_seconds=override.target_seconds or placement.target_seconds,
        reasons=override.reasons or placement.reasons,
    )


def place_pool(
    groups: Sequence[StoryGroup],
    overrides: Optional[dict[str, Placement]] = None,
) -> list[Placement]:
    """Place every surviving story. Order in, order out — the pool is ranked."""
    overrides = overrides or {}
    return [place_group(g, overrides.get(g.slug)) for g in groups]


# ---------------------------------------------------------------------------
# Filling the holes
# ---------------------------------------------------------------------------


@dataclass
class Fill:
    """The result of packing placements into the holes the human left."""

    blocks: dict[str, list[Placement]] = field(default_factory=dict)
    unplaced: list[tuple[Placement, str]] = field(default_factory=list)
    used_seconds: dict[str, float] = field(default_factory=dict)

    def order(self, block: str) -> list[Placement]:
        return self.blocks.get(block, [])

    @property
    def placed_count(self) -> int:
        return sum(len(v) for v in self.blocks.values())


def fill_holes(
    placements: Sequence[Placement],
    holes: Sequence[Hole],
    config: Optional[ShowConfig] = None,
) -> Fill:
    """Pack ranked placements into the gaps, primary first, then backup.

    Ordering inside a block is not the packing order: stories go in wherever
    they fit and are then sorted heavy to light (§2), because a story that
    arrives late is not therefore a light story.
    """
    config = config or ShowConfig()
    by_name = {h.name: h for h in holes}
    fill = Fill(
        blocks={h.name: [] for h in holes},
        used_seconds={h.name: 0.0 for h in holes},
    )
    packages: dict[str, int] = {h.name: 0 for h in holes}

    def try_block(name: str, placement: Placement) -> Optional[str]:
        """Returns None on success, or why it did not fit."""
        hole = by_name.get(name)
        if hole is None:
            return f"{name} has no room left for the agent to fill"
        if placement.is_package and packages[name] >= hole.max_pkgs:
            return f"{name} is at its package budget of {hole.max_pkgs} (§5 R9)"
        if fill.used_seconds[name] + placement.target_seconds > hole.seconds:
            return (
                f"{name} has {hole.seconds - fill.used_seconds[name]:.0f}s left and "
                f"this needs {placement.target_seconds:.0f}s"
            )
        fill.blocks[name].append(placement)
        fill.used_seconds[name] += placement.target_seconds
        if placement.is_package:
            packages[name] += 1
        return None

    for placement in placements:
        why = try_block(placement.primary, placement)
        if why is None:
            continue
        if placement.backup:
            second = try_block(placement.backup, placement)
            if second is None:
                continue
            fill.unplaced.append((placement, f"{why}; and {second}"))
        else:
            fill.unplaced.append((placement, f"{why}; no backup block was set"))

    for name in fill.blocks:
        fill.blocks[name] = order_block(fill.blocks[name])
    return fill


def order_block(placements: Iterable[Placement]) -> list[Placement]:
    """Heavy to light (§2), ties broken by the grade that got it here."""
    return sorted(
        placements,
        key=lambda p: (-p.heaviness, -p.group.total, p.slug),
    )


def demo_holes(seconds_per_block: float = 150.0, config: Optional[ShowConfig] = None) -> list[Hole]:
    """Every block with the same gap in it — for demonstration runs only.

    The real holes come from the rundown: a block's budget minus what the human
    producer already put there. Neither number exists yet — the break and
    weather allowances are still deferred (§11.20) and there is no Inception
    adapter — so a run that wants to show the fill has to assume something, and
    an assumption stated in one function is better than one scattered through a
    report.
    """
    config = config or ShowConfig()
    return [
        Hole(b.half, b.label, seconds_per_block, max_pkgs=b.max_pkgs)
        for b in config.blocks
    ]
