"""Show configuration.

Most of CLAUDE.md §11 is answered and lives here as real values. What is still
open defaults to UNSET, and the rules that depend on an UNSET value report
"not configured" instead of guessing a threshold — see §12, "Don't guess at
domain rules."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class _Unset:
    """Sentinel for a domain value nobody has answered yet."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()

# §11.2 — the roster. Jeff doubles as the weather man.
MEGAN = "MEGAN"
JEFF = "JEFF"


@dataclass(frozen=True)
class BlockConfig:
    """Per-block configuration.

    half / label     1 or 2, "A".."D"
    purpose          prose, from §2
    budget_seconds   a fixed content budget, once break and weather allowances
                     are known (§11.1)
    budget_range     (min, max) seconds, where the budget is a range not a point
    default_shot     §11.3 — camera plus over-shoulder, e.g. "CAM2 OX3". The
                     over-shoulder is part of the shot (§11.17): the same
                     camera on a different monitor is a different shot.
    open_shot        the A blocks open on a different shot for the double read,
                     which is structure rather than an exception (§11.3)
    anchors          §11.2 — who may read in this block
    read_mode        "open_dual" | "solo" | "dual" (§11.2)
    solo_anchor      who carries the block once the other breaks for weather
    closing_anchor   who reads the block's closing bump, where that is fixed
    max_pkgs         §5 R9
    """

    half: int
    label: str
    purpose: str = ""
    budget_seconds: Any = UNSET
    budget_range: Any = UNSET
    default_shot: Any = UNSET
    open_shot: Any = UNSET
    anchors: Any = UNSET
    read_mode: Any = UNSET
    solo_anchor: Any = UNSET
    closing_anchor: Any = UNSET
    max_pkgs: int = 2

    @property
    def name(self) -> str:
        return f"{self.half}{self.label}"


def _default_blocks() -> tuple[BlockConfig, ...]:
    """§2 layout, §11.1 budgets, §11.2 anchor pattern, §11.3 shots.

    The anchor pattern is the same in both half hours: Jeff and Megan open the
    A block together, Jeff breaks off for a first look at weather and tosses to
    Megan, and he is not back until the weather tease closing the B block. The C
    block resumes double reads and hands Jeff into the main weather segment. The
    D block is double reads.
    """
    return (
        BlockConfig(
            1, "A", "Local lead; top regional/national sprinkled in.",
            budget_range=(300.0, 420.0),
            default_shot="CAM2 OX3", open_shot="CAM3 OX2",
            anchors=(JEFF, MEGAN), read_mode="open_dual", solo_anchor=MEGAN,
        ),
        BlockConfig(
            1, "B", "National quick hits.",
            default_shot="CAM3 OX5",
            anchors=(MEGAN, JEFF), read_mode="solo",
            solo_anchor=MEGAN, closing_anchor=JEFF,
        ),
        BlockConfig(
            1, "C", "Trending / talkers. Uplifting. Leads into weather.",
            default_shot="CAM3 OX2",
            anchors=(JEFF, MEGAN), read_mode="dual",
        ),
        BlockConfig(
            1, "D", "Local overflow; default is fun local.",
            default_shot="CAM3 OX2",
            anchors=(JEFF, MEGAN), read_mode="dual",
        ),
        BlockConfig(
            2, "A", "Local.",
            budget_range=(300.0, 420.0),
            default_shot="CAM2 OX3", open_shot="CAM1 OX4",
            anchors=(JEFF, MEGAN), read_mode="open_dual", solo_anchor=MEGAN,
        ),
        BlockConfig(
            2, "B", "National quick hits.",
            default_shot="CAM1 OX1",
            anchors=(MEGAN, JEFF), read_mode="solo",
            solo_anchor=MEGAN, closing_anchor=JEFF,
        ),
        BlockConfig(
            2, "C", "Flex. Interesting national, or local overflow.",
            default_shot="CAM3 OX2",
            anchors=(JEFF, MEGAN), read_mode="dual",
        ),
        BlockConfig(
            2, "D", "Entertainment, then optional talker to close.",
            default_shot="CAM3 OX2",
            anchors=(JEFF, MEGAN), read_mode="dual",
        ),
    )


@dataclass(frozen=True)
class ShowConfig:
    """Thresholds for the §5 rule engine."""

    blocks: tuple[BlockConfig, ...] = field(default_factory=_default_blocks)

    # §11.1 — wall clock for each half hour. Content, breaks and weather all
    # come out of these.
    half_budget_seconds: Any = field(default_factory=lambda: {1: 1675.0, 2: 1920.0})

    # §11.1 — still needed before a per-block budget can be derived for B and D.
    break_seconds: Any = UNSET
    weather_seconds: Any = UNSET

    # §11.1 — the C block is back-timed to start this far before the quarter
    # hour. Checkable once break and weather allowances are known.
    c_block_backtime_window: tuple[float, float] = (30.0, 60.0)

    # §11.9 — the real on-air limit for a lower third.
    cg_char_ceiling: Any = 39

    # §11.15 — a bump carries a bump CG, formatted differently from a lower
    # third; weather carries the weather anchor's prefilled name and title, so
    # it needs no CG written for it.
    bump_cg_char_ceiling: Any = UNSET

    # R6 — "under ~15 seconds", and §11.18: a reader must say why it is one.
    rdr_max_seconds: float = 15.0
    rdr_requires_justification: bool = True

    # R7 — a range, not a hard guideline (§11.16), so out-of-range is a
    # warning a human waves through.
    vo_min_seconds: float = 20.0
    vo_max_seconds: float = 45.0

    # §3 PKG — 1:00 short, 2:00 normal, 3:00 needs to be stellar.
    pkg_normal_max_seconds: float = 120.0
    pkg_ceiling_seconds: float = 180.0

    block_budget_tolerance_seconds: float = 10.0

    # §11.14 — the monitor must be parked in D when this many video files
    # play between the monitor being on screen and coming back.
    video_files_before_d: int = 2

    # §11.3 — weather is done on the weather wall, not a studio shot.
    weather_shot: str = "WX GFX"

    # Read rate for estimate_read_time(). PROVISIONAL and good enough for now
    # per §11.19; tweak as real scripts accumulate.
    words_per_minute: float = 160.0

    # R13 — daypart phrases that do not belong in a noon show as written.
    daypart_phrases: tuple[str, ...] = (
        "this morning",
        "tonight",
        "this evening",
        "earlier tonight",
        "later tonight",
        "good evening",
        "good morning",
        "at this hour tonight",
    )

    def block(self, half: int, label: str) -> BlockConfig:
        for b in self.blocks:
            if b.half == half and b.label == label.upper():
                return b
        raise KeyError(f"no block {half}{label} in config")

    def effective_cg_ceiling(self) -> tuple[int, bool]:
        """Return (ceiling, is_provisional)."""
        if self.cg_char_ceiling is UNSET:
            return 45, True
        return int(self.cg_char_ceiling), False
