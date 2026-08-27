"""Show configuration.

Everything in CLAUDE.md §11 that is still an open question lives here as a
configurable value defaulting to UNSET. Rules that depend on an UNSET value
report an INFO ("not configured") instead of guessing a threshold — see §12,
"Don't guess at domain rules."
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


@dataclass(frozen=True)
class BlockConfig:
    """Per-block configuration.

    half:            1 or 2
    label:           "A".."D"
    purpose:         prose, from CLAUDE.md §2
    budget_seconds:  §11.1 — unanswered, so UNSET by default
    default_shot:    §11.3 — camera identifier, e.g. "CAM1"
    anchors:         §11.2 — the anchor(s) expected to read in this block
    read_mode:       §11.2 — "dual" or "solo", once the weather break-off is pinned
    max_pkgs:        §5 R9
    """

    half: int
    label: str
    purpose: str = ""
    budget_seconds: Any = UNSET
    default_shot: Any = UNSET
    anchors: Any = UNSET
    read_mode: Any = UNSET
    max_pkgs: int = 2

    @property
    def name(self) -> str:
        return f"{self.half}{self.label}"


def _default_blocks() -> tuple[BlockConfig, ...]:
    """Block layout from CLAUDE.md §2. Purposes are settled; budgets are not."""
    return (
        BlockConfig(1, "A", "Local lead; top regional/national sprinkled in."),
        BlockConfig(1, "B", "National quick hits."),
        BlockConfig(1, "C", "Trending / talkers. Uplifting. Leads into weather."),
        BlockConfig(1, "D", "Local overflow; default is fun local."),
        BlockConfig(2, "A", "Local."),
        BlockConfig(2, "B", "National quick hits."),
        BlockConfig(2, "C", "Flex. Interesting national, or local overflow."),
        BlockConfig(2, "D", "Entertainment, then optional talker to close."),
    )


@dataclass(frozen=True)
class ShowConfig:
    """Thresholds for the §5 rule engine.

    Values marked PROVISIONAL are read off the worked examples in CLAUDE.md §3
    rather than from Phil. They are wrong until confirmed; they are here, in one
    place, so confirming them is a one-line edit.
    """

    blocks: tuple[BlockConfig, ...] = field(default_factory=_default_blocks)

    # R5 / §11.9 — real on-air lower-third limit is unknown. The longest CG in
    # the §3 examples is 38 characters; the "far too long" counter-example is 94.
    cg_char_ceiling: Any = UNSET
    cg_char_ceiling_provisional: int = 45

    # R6 — "under ~15 seconds".
    rdr_max_seconds: float = 15.0

    # R7 — "typical length 20-45 seconds".
    vo_min_seconds: float = 20.0
    vo_max_seconds: float = 45.0

    # §3 PKG — 1:00 short, 2:00 normal, 3:00 needs to be stellar.
    pkg_normal_max_seconds: float = 120.0
    pkg_ceiling_seconds: float = 180.0

    # R14 — tolerance around a block budget, once budgets exist (§11.1).
    block_budget_tolerance_seconds: float = 10.0

    # Read rate for estimate_read_time(). PROVISIONAL: broadcast copy is usually
    # read at 150-180 wpm; this needs calibrating against real KIFI scripts
    # (build order §10.2).
    words_per_minute: float = 160.0

    # R13 — daypart phrases that do not belong in a noon show as written.
    # WARNINGs, not errors: "this morning" is legitimate past tense at noon,
    # but wire copy usually means it as "right now".
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
            return self.cg_char_ceiling_provisional, True
        return int(self.cg_char_ceiling), False
