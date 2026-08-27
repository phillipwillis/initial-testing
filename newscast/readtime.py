"""Read-time estimation (build order §10.2).

Every duration rule in §5 depends on this. It is deliberately simple and
deliberately calibratable: one rate constant in ShowConfig, plus explicit
handling for the tokens that break a naive word count (numbers, times, money,
initialisms). Calibrate against real KIFI scripts before trusting R6/R7/R14.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

from newscast.config import ShowConfig

_WORD_RE = re.compile(r"[A-Za-z0-9$%:.,'\-/]+")
_NAT_SOUND_RE = re.compile(r"^\s*-[^-].*-\s*$")

# Tokens read letter by letter: "F.B.I.", "I.F.". Anchor copy is ALL CAPS by
# convention (§4), so casing cannot tell an acronym from an ordinary word --
# only the dotted form is a reliable signal.
_INITIALISM_RE = re.compile(r"^(?:[A-Za-z]\.){2,}[A-Za-z]?\.?$")

_DIGIT_RE = re.compile(r"\d")


def _spoken_weight(token: str) -> float:
    """Roughly how many word-lengths a token takes to say out loud."""
    # Initialisms keep their dots -- strip the comma, not the periods.
    dotted = token.strip(",'-/")
    if _INITIALISM_RE.match(dotted):
        letters = len([c for c in dotted if c.isalpha()])
        return max(1.0, letters * 0.5)

    bare = token.strip(".,'-/")
    if not bare:
        return 0.0

    if _DIGIT_RE.search(bare):
        # "2:00" -> "two o'clock", "27" -> "twenty seven", "1,500" -> "fifteen
        # hundred", "$4.2" -> "four point two dollars". Digit count is a decent
        # proxy; separators add a word.
        digits = len(_DIGIT_RE.findall(bare))
        extra = 1.0 if any(c in bare for c in "$%/") else 0.0
        return max(1.0, digits * 0.75) + extra

    # words_per_minute already assumes an average word length, so only unusually
    # long words earn a bump.
    return max(1.0, len(bare) / 7.0)


def count_spoken_words(copy: str) -> float:
    """Weighted word count for a chunk of anchor copy."""
    total = 0.0
    for line in copy.splitlines() or [copy]:
        if _NAT_SOUND_RE.match(line):
            # -sounds of bustling- is not read; it is under the video.
            continue
        for token in _WORD_RE.findall(line):
            total += _spoken_weight(token)
    return total


def estimate_read_time(
    copy: str | Iterable[str], config: ShowConfig | None = None
) -> float:
    """Seconds of on-air time for `copy`, rounded up to the nearest tenth.

    Accepts a string or an iterable of lines.
    """
    config = config or ShowConfig()
    if not isinstance(copy, str):
        copy = "\n".join(copy)
    words = count_spoken_words(copy)
    if words <= 0:
        return 0.0
    seconds = words / config.words_per_minute * 60.0
    return math.ceil(seconds * 10.0) / 10.0
