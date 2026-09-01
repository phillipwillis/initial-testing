"""The Claude layer (§11.12).

Two jobs go to the model, and only two, because §11.12 budgets the whole show
at **under a dollar with a two-dollar hard ceiling** and that only works if tool
use collapses many decisions into one or two calls:

* **Grading** — rank the whole pool against itself (§7). Comparative by
  construction: the model sees the pool and orders it, rather than scoring
  stories in isolation and sorting afterward.
* **Slotting** — a primary block, a backup block and a heaviness weight for
  every story that survives the cull (§11.27).

Script writing is a third job, and it is not here yet.

**The ceiling is enforced, not hoped for.** §12 says anything checkable gets
checked in code, and a dollar limit is checkable: `Budget` refuses a call whose
worst case would take the show past the ceiling, counting `max_tokens` of output
because that is what the request actually authorises. A show that runs out of
budget falls back to the deterministic graders rather than stopping.

**The model is one setting.** Development runs on Haiku to keep experimentation
cheap (§11.12); production is a config change, not a rewrite.

**Nothing here is required.** The SDK may not be installed and the key may not
be in the `.env` yet. `producer()` returns None in that case and every caller
falls back to `newscast.scoring` and `newscast.slotting`, which is why those
exist as deterministic stand-ins rather than as scaffolding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .scoring import Grade, StoryGroup
from .slotting import Placement
from .wires.stub import StoryStub

# §11.12 — Haiku for development, Opus for production. One setting.
DEV_MODEL = "claude-haiku-4-5"
PROD_MODEL = "claude-opus-5"

# Dollars per million tokens, (input, output). Used for the ceiling, so these
# are the numbers to correct if pricing moves.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
}

API_KEY_NAME = "ANTHROPIC_API_KEY"


class LLMUnavailable(RuntimeError):
    """No SDK, or no key. Callers fall back rather than fail."""


class BudgetExceeded(RuntimeError):
    """The call would take the show past its ceiling (§11.12)."""


@dataclass
class Spend:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def dollars(self, model: str) -> float:
        rate_in, rate_out = PRICES.get(model, PRICES[DEV_MODEL])
        # Cache reads bill at roughly a tenth, writes at roughly 1.25x.
        billed_in = (
            self.input_tokens
            + 0.1 * self.cache_read_tokens
            + 1.25 * self.cache_write_tokens
        )
        return (billed_in * rate_in + self.output_tokens * rate_out) / 1_000_000


@dataclass
class Budget:
    """What this show is allowed to spend (§11.12).

    `ceiling` is the hard limit. `expected` is what a show should actually cost
    and is only reported, because a run that quietly costs $1.90 every day is a
    thing to know about before the ceiling stops it.
    """

    model: str = DEV_MODEL
    ceiling: float = 2.00
    expected: float = 1.00
    spend: Spend = field(default_factory=Spend)
    notes: list[str] = field(default_factory=list)

    @property
    def dollars(self) -> float:
        return self.spend.dollars(self.model)

    @property
    def remaining(self) -> float:
        return max(0.0, self.ceiling - self.dollars)

    def worst_case(self, input_tokens: int, max_tokens: int) -> float:
        """What the next call could cost if it runs to `max_tokens`.

        Not what it will cost — what the request authorises. A ceiling checked
        against an optimistic estimate is not a ceiling.
        """
        rate_in, rate_out = PRICES.get(self.model, PRICES[DEV_MODEL])
        return (input_tokens * rate_in + max_tokens * rate_out) / 1_000_000

    def check(self, input_tokens: int, max_tokens: int) -> None:
        cost = self.worst_case(input_tokens, max_tokens)
        if self.dollars + cost > self.ceiling:
            raise BudgetExceeded(
                f"this call could cost ${cost:.3f} on top of ${self.dollars:.3f} "
                f"already spent, and the ceiling is ${self.ceiling:.2f} (§11.12)"
            )

    def record(self, usage: Any) -> None:
        self.spend.calls += 1
        self.spend.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.spend.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.spend.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.spend.cache_write_tokens += (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        if self.dollars > self.expected and "over expected" not in " ".join(self.notes):
            self.notes.append(
                f"over expected: ${self.dollars:.3f} against ${self.expected:.2f} "
                f"(ceiling ${self.ceiling:.2f})"
            )

    def report(self) -> str:
        return (
            f"{self.spend.calls} call(s), "
            f"{self.spend.input_tokens} in / {self.spend.output_tokens} out, "
            f"${self.dollars:.3f} of ${self.ceiling:.2f} on {self.model}"
        )


# ---------------------------------------------------------------------------
# Tool schemas — how the model returns structured answers
# ---------------------------------------------------------------------------

# Structured output through a forced tool call rather than "reply with JSON":
# the schema is enforced by the API, and a malformed answer becomes a validation
# error instead of a parse that half-works.

GRADE_TOOL = {
    "name": "submit_ranking",
    "description": (
        "Submit the whole pool ranked against itself, best first. Score every "
        "story; do not omit any."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "the story's id, exactly as given"},
                        "viewer_impact": {"type": "number", "description": "0..1, dominant term: does this change what the viewer does today?"},
                        "magnitude": {"type": "number", "description": "0..1, significance in absolute terms"},
                        "visual_strength": {"type": "number", "description": "0..1, does this imply striking video?"},
                        "audio_available": {"type": "number", "description": "0..1, is there a usable soundbite?"},
                        "freshness": {"type": "number", "description": "0..1, new today vs an update to something already aired"},
                        "note": {"type": "string", "description": "one short line on why it ranks here"},
                    },
                    "required": ["id", "viewer_impact", "magnitude", "visual_strength",
                                 "audio_available", "freshness"],
                },
            }
        },
        "required": ["ranking"],
    },
}

PLACE_TOOL = {
    "name": "submit_placements",
    "description": "Place every story given. Do not omit any.",
    "input_schema": {
        "type": "object",
        "properties": {
            "placements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "the story's id, exactly as given"},
                        "primary": {"type": "string", "description": 'block name, e.g. "1A", "2D"'},
                        "backup": {"type": "string", "description": "where it goes if it loses that slot; must differ from primary"},
                        "heaviness": {"type": "number", "description": "0..1; a shooting is 0.9-1.0, a small business going under 0.6-0.7"},
                        "reason": {"type": "string", "description": "one short line"},
                    },
                    "required": ["id", "primary", "backup", "heaviness"],
                },
            }
        },
        "required": ["placements"],
    },
}

GRADE_SYSTEM = """\
You are the producer of the noon newscast at KIFI / Local News 8 in Idaho Falls, Idaho.

Rank this pool of wire stories against one another, best first. The dominant
criterion is "what's in it for the viewer?" — a local road closure beats an
Indonesian chemical plant explosion every time, because it changes what the
viewer does today. Eastern Idaho weights hardest, then the mountain west, then
national, then international.

Score comparatively. You are seeing the whole pool at once, so a 0.9 means
better than almost everything else here, not good in the abstract.

The noon show carries no sports.
"""

PLACE_SYSTEM = """\
You are the producer of the noon newscast at KIFI / Local News 8 in Idaho Falls, Idaho.

The show is two half hours of four blocks each:

  1A  local lead, the heaviest content of the show
  1B  national quick hits, short items
  1C  trending and talkers, uplifting, leads into weather
  1D  local overflow, default is fun local
  2A  local
  2B  national quick hits
  2C  flex — interesting national, or local overflow
  2D  entertainment, then an optional talker to close the show

There is no rule that a given kind of story belongs in a given block. A shooting
is hard news that usually lands in B, but it moves with the day. Decide from
what else is in this pool.

Give every story a primary block, a different backup block for when it loses
that slot, and a heaviness weight from 0 to 1 — a shooting is 0.9 to 1.0, a
small business going under is sad but lighter at 0.6 to 0.7. Heavier stories
run earlier within a block.
"""


def _stub_line(stub: StoryStub) -> str:
    bits = [f"id={stub.id or stub.story_number or stub.slug}", f"slug={stub.slug!r}"]
    if stub.source:
        bits.append(f"source={stub.source}")
    if stub.footage_type:
        bits.append(f"form={stub.footage_type}")
    if stub.timestamp_text:
        bits.append(f"filed={stub.timestamp_text}")
    if stub.version:
        bits.append(f"version={stub.version}")
    if stub.teaser:
        bits.append(f"teaser={stub.teaser[:200]!r}")
    return "  ".join(bits)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def load_client(env: Optional[dict[str, str]] = None):
    """An Anthropic client, or a reason there isn't one.

    The key lives in the same `.env` as the wire credentials (§14) and is never
    logged, printed, or written into a report.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable(
            "the anthropic SDK is not installed (pip install anthropic)"
        ) from exc

    key = (env or {}).get(API_KEY_NAME, "").strip()
    if not key:
        import os

        key = os.environ.get(API_KEY_NAME, "").strip()
    if not key:
        raise LLMUnavailable(f"{API_KEY_NAME} is not in the .env or the environment")

    return anthropic.Anthropic(api_key=key)


@dataclass
class Producer:
    """The two model calls a show makes, with the ceiling around them."""

    client: Any
    budget: Budget = field(default_factory=Budget)
    max_tokens: int = 8000

    def _ask(self, system: str, prompt: str, tool: dict) -> dict:
        """One forced-tool call, budget-checked before and recorded after."""
        messages = [{"role": "user", "content": prompt}]
        counted = self.client.messages.count_tokens(
            model=self.budget.model, system=system, messages=messages, tools=[tool]
        )
        self.budget.check(counted.input_tokens, self.max_tokens)

        response = self.client.messages.create(
            model=self.budget.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=messages,
        )
        self.budget.record(response.usage)

        for block in response.content:
            if getattr(block, "type", "") == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        raise LLMUnavailable(
            f"the model returned no {tool['name']} call "
            f"(stop_reason={getattr(response, 'stop_reason', '?')})"
        )

    def grade_pool(self, stubs: Sequence[StoryStub]) -> list[Grade]:
        """§7 — the whole pool ranked against itself in one call."""
        from .scoring import WEIGHTS

        by_id = {s.id or s.story_number or s.slug: s for s in stubs}
        prompt = "Stories in the pool:\n\n" + "\n".join(
            _stub_line(s) for s in stubs
        )
        answer = self._ask(GRADE_SYSTEM, prompt, GRADE_TOOL)

        grades: list[Grade] = []
        seen: set[str] = set()
        for row in answer.get("ranking", []):
            stub = by_id.get(str(row.get("id", "")))
            if stub is None or stub.id in seen:
                continue
            seen.add(stub.id)
            grade = Grade(
                stub=stub,
                viewer_impact=_clamp(row.get("viewer_impact")),
                magnitude=_clamp(row.get("magnitude")),
                visual_strength=_clamp(row.get("visual_strength")),
                audio_available=_clamp(row.get("audio_available")),
                freshness=_clamp(row.get("freshness")),
            )
            grade.total = sum(
                getattr(grade, name) * weight for name, weight in WEIGHTS.items()
            )
            if row.get("note"):
                grade.notes.append(str(row["note"]))
            grades.append(grade)

        # A story the model skipped is not a story that scored zero, so the
        # deterministic grader fills it in rather than the pool losing it.
        missed = [s for s in stubs if (s.id or s.story_number or s.slug) not in seen]
        if missed:
            from .scoring import grade_pool as heuristic_grade

            grades.extend(heuristic_grade(missed))
            self.budget.notes.append(
                f"{len(missed)} story(s) the model skipped were graded by the "
                "deterministic fallback"
            )
        return grades

    def place_pool(self, groups: Sequence[StoryGroup]) -> dict[str, Placement]:
        """§11.27 — primary, backup and heaviness for everything that survived.

        Returns placements keyed by slug, which is the shape
        `slotting.place_pool` takes as overrides: anything the model missed
        keeps the heuristic's answer.
        """
        by_id = {g.stub.id or g.stub.story_number or g.slug: g for g in groups}
        prompt = "Stories to place:\n\n" + "\n".join(
            _stub_line(g.stub) for g in groups
        )
        answer = self._ask(PLACE_SYSTEM, prompt, PLACE_TOOL)

        out: dict[str, Placement] = {}
        for row in answer.get("placements", []):
            group = by_id.get(str(row.get("id", "")))
            if group is None:
                continue
            primary = str(row.get("primary", "")).upper().strip()
            backup = str(row.get("backup", "")).upper().strip()
            if backup == primary:
                backup = ""
            out[group.slug] = Placement(
                group=group,
                primary=primary,
                backup=backup,
                heaviness=_clamp(row.get("heaviness"), default=0.5),
                reasons=[str(row["reason"])] if row.get("reason") else [],
            )
        return out


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def producer(
    env: Optional[dict[str, str]] = None,
    model: str = DEV_MODEL,
    ceiling: float = 2.00,
) -> tuple[Optional[Producer], str]:
    """A Producer, or None and the reason why.

    Never raises: a run with no key still has to produce a rundown, and the
    deterministic graders are what it produces it with.
    """
    try:
        client = load_client(env)
    except LLMUnavailable as exc:
        return None, str(exc)
    return Producer(client=client, budget=Budget(model=model, ceiling=ceiling)), ""
