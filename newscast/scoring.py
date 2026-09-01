"""Comparative grading of a pool of stubs (§7).

§7 is explicit that grading is **comparative and batched** — the model sees the
pool and ranks within it — and §11.12 settles that an Opus model does the
grading. This module is not that model.

It is a deterministic stand-in that scores the §7 fields from what a stub
actually carries, so the pipeline downstream of grading can be built, run and
argued about before a single token is spent. Every term is a documented
heuristic, and every score is normalised **within the pool**, which keeps the
"comparative, not absolute" property that §7 insists on.

Swapping in the real grader means replacing `grade_pool`. The `Grade` shape is
what the rest of the pipeline consumes, so nothing else has to change.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional, Sequence

from newscast.wires.stub import ContentType, StoryStub

# §7 weights. viewer_impact is the dominant term by §0: "what's in it for the
# viewer?" is the single dominant ranking criterion.
WEIGHTS = {
    "viewer_impact": 3.0,
    "magnitude": 2.0,
    "visual_strength": 1.5,
    "audio_available": 1.0,
    "corroboration": 1.0,
    "freshness": 1.5,
}

# Eastern Idaho and the markets a KIFI viewer plausibly cares about. A story out
# of Idaho Falls is worth more to this show than one out of Miami, which is the
# whole of §0's road-closure-beats-Indonesia argument.
HOME_MARKETS = (
    "idaho", "boise", "pocatello", "twin falls", "jackson", "wyoming",
    "utah", "salt lake", "montana", "spokane", "eastern idaho",
)

# Word lists are matched on word boundaries, never as substrings. A trailing *
# marks a stem, so "evacuat*" catches evacuate, evacuated and evacuation while
# "war" does not catch "toward", "warm" or "award".
#
# This matters more than it looks. A substring match for "nfl" fired inside the
# Spanish word "conflicto" and culled a story about US and Iran trading attacks
# as sports. That is §0's warning exactly — a rule that reads fine as prose and
# breaks on air.

# Words that mark a story as changing what a viewer does today.
IMPACT_WORDS = (
    "closure*", "closed", "closes", "evacuat*", "recall", "warning", "watch",
    "outage", "boil order", "shelter", "delay", "cancel*", "detour", "shutdown",
    "storm", "flood", "fire", "snow", "heat", "wind", "tornado", "quake",
    "school", "highway", "interstate", "bridge", "gas price", "tax", "refund",
)

# Words that mark absolute significance, whether or not it touches the viewer.
MAGNITUDE_WORDS = (
    "dead", "killed", "died", "death", "shooting", "arrest", "charged",
    "crash", "collision", "explosion", "attack", "strike", "war", "missing",
    "rescue", "verdict", "indict*", "resign", "president", "senate",
    "supreme court", "election", "hostage", "outbreak",
)

# Forms the wire ships that imply strong pictures.
VISUAL_FOOTAGE = {"PKG": 1.0, "DONUT": 0.9, "LOOK LIVE": 0.8, "RAW": 0.7,
                  "VO": 0.6, "VO/SIL": 0.55, "SIL": 0.4}

# Forms that carry usable sound.
AUDIO_FOOTAGE = {"SOT": 1.0, "CUT SOUND": 1.0, "VOSOT": 0.9, "VO/SOT": 0.9,
                 "PKG": 0.8, "DONUT": 0.8, "LOOK LIVE": 0.6}

_WORD_RE = re.compile(r"[a-z0-9']+")

# Common inflections, so a whole-word entry still catches its plural and tense.
_SUFFIXES = r"(?:s|es|ed|ing)?"


def compile_words(words: Iterable[str]) -> re.Pattern:
    """Compile a word list into one boundary-anchored pattern.

    A trailing `*` marks a stem, matched from a word boundary with any ending.
    Everything else is a whole word, allowing a plural or tense.
    """
    parts = []
    for word in words:
        if word.endswith("*"):
            parts.append(rf"\b{re.escape(word[:-1])}\w*")
        else:
            parts.append(rf"\b{re.escape(word)}{_SUFFIXES}\b")
    return re.compile("|".join(parts), re.I)


_IMPACT_RE = compile_words(IMPACT_WORDS)
_MAGNITUDE_RE = compile_words(MAGNITUDE_WORDS)
_HOME_RE = compile_words(HOME_MARKETS)


@dataclass
class Grade:
    """One stub's scores. Every term runs 0..1; `total` is the weighted sum."""

    stub: StoryStub
    viewer_impact: float = 0.0
    magnitude: float = 0.0
    visual_strength: float = 0.0
    audio_available: float = 0.0
    corroboration: float = 0.0
    freshness: float = 0.0
    total: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.stub.slug

    def explain(self) -> str:
        parts = [
            f"{name}={getattr(self, name):.2f}"
            for name in WEIGHTS
        ]
        return f"{self.total:6.2f}  " + " ".join(parts)


def _text_of(stub: StoryStub) -> str:
    return f"{stub.slug} {stub.teaser}".lower()


def _hits(text: str, pattern: re.Pattern) -> int:
    """Distinct matches, so one word repeated is not three signals."""
    return len({m.group(0).lower() for m in pattern.finditer(text)})


def _saturate(count: int, half: float = 2.0) -> float:
    """0..1, rising fast then flattening. Two hits is most of the signal."""
    return count / (count + half) if count else 0.0


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 3}


def _viewer_impact(stub: StoryStub) -> tuple[float, list[str]]:
    text = _text_of(stub)
    notes: list[str] = []

    score = _saturate(_hits(text, _IMPACT_RE))

    haystack = f"{stub.embargo} {stub.source} {text}".lower()
    if _HOME_RE.search(haystack):
        score = min(1.0, score + 0.45)
        notes.append("mentions a home-region market")

    # A wire article with no video still matters if it changes someone's day,
    # but material we cannot show is worth less to a television newscast.
    if not stub.has_video and not stub.has_script:
        score *= 0.5
        notes.append("no video and no script")

    return score, notes


def _freshness(stub: StoryStub, now: datetime) -> tuple[float, list[str]]:
    notes: list[str] = []
    if stub.timestamp is None:
        return 0.3, ["no timestamp"]

    hours = max(0.0, (now - stub.timestamp).total_seconds() / 3600.0)
    recency = math.exp(-hours / 6.0)  # half-life of about four hours

    if stub.is_update:
        # §7 distinguishes new-today from an update to something already aired.
        # A high version means the wire keeps returning to it, which is a signal
        # of importance and of staleness at once; treat it as mildly positive.
        recency = min(1.0, recency + 0.1)
        notes.append(f"version {stub.version} — the wire keeps rewriting it")

    return recency, notes


# Affiliate slugs follow CNN's own convention: "CA: MASS SHOOTING ARREST/FBI-$20K
# REWARD" is state, story, then the speaker. The wire files one row per speaker,
# so the part before the slash identifies the story and the part after does not.
_AFFILIATE_SLUG_RE = re.compile(r"^\s*[A-Z]{2}\s*:\s*(?P<story>[^/]{3,})/")


def story_key(stub: StoryStub) -> str:
    """The story a stub belongs to, where the slug says so."""
    match = _AFFILIATE_SLUG_RE.match(stub.slug or "")
    return " ".join(match.group("story").lower().split()) if match else ""


def similarity(left: StoryStub, right: StoryStub) -> float:
    """How much two stubs look like the same story, 0..1.

    Where both slugs carry CNN's `STATE: STORY/SPEAKER` shape, the story halves
    decide it — that is the wire telling us directly. CNN truncates the field
    ("ARREST" becomes "ARRES" on a longer slug), so those halves are compared
    by overlap rather than equality.
    """
    left_key, right_key = story_key(left), story_key(right)
    if left_key and right_key:
        shorter, longer = sorted((left_key, right_key), key=len)
        if longer.startswith(shorter):
            return 1.0
        left_words, right_words = set(left_key.split()), set(right_key.split())
        return len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))

    mine, theirs = _tokens(_text_of(left)), _tokens(_text_of(right))
    if not mine or not theirs:
        return 0.0
    return len(mine & theirs) / max(1, min(len(mine), len(theirs)))


def _corroboration(stub: StoryStub, pool: Sequence[StoryStub]) -> float:
    """How many other stubs look like the same story.

    §7 calls this a heuristic for importance: the same event arriving from
    several wires at once is the wires agreeing it matters.
    """
    mine = _tokens(_text_of(stub))
    if not mine:
        return 0.0
    matches = sum(
        1 for other in pool if other is not stub and similarity(stub, other) > 0.4
    )
    return _saturate(matches, half=1.5)


def grade_pool(
    stubs: Sequence[StoryStub], now: Optional[datetime] = None
) -> list[Grade]:
    """Grade every stub against the others, best first.

    Comparative by construction: corroboration is measured against the pool,
    and the returned order is a ranking within it. Grading a stub on its own
    would give a number with nothing to compare it to, which §7 forbids.
    """
    if not stubs:
        return []
    now = now or max((s.timestamp for s in stubs if s.timestamp), default=datetime.now())

    grades: list[Grade] = []
    for stub in stubs:
        text = _text_of(stub)
        impact, impact_notes = _viewer_impact(stub)
        fresh, fresh_notes = _freshness(stub, now)

        grade = Grade(
            stub=stub,
            viewer_impact=impact,
            magnitude=_saturate(_hits(text, _MAGNITUDE_RE)),
            visual_strength=VISUAL_FOOTAGE.get(
                stub.footage_type.upper(), 0.5 if stub.has_video else 0.15
            ),
            audio_available=AUDIO_FOOTAGE.get(stub.footage_type.upper(), 0.0),
            corroboration=_corroboration(stub, stubs),
            freshness=fresh,
            notes=impact_notes + fresh_notes,
        )
        grade.total = sum(
            WEIGHTS[name] * getattr(grade, name) for name in WEIGHTS
        )
        grades.append(grade)

    grades.sort(key=lambda g: (-g.total, g.stub.slug))
    return grades
