"""Transcript-driven durations and clip selection (§11.7, §11.23, §11.26).

CNN's printed duration is not a running time — it counts the b-roll in the
video file, and packages are the worst offenders (§11.23). The wire's own
script is not reliable either: wires ship an old script against a revamped
package, so the words on the page are not always the words in the video.

The transcript is therefore the **authoritative verbatim**. Everything a
rundown needs about a video file — how long the part we actually use runs, and
where it starts and stops — comes from here.

Two jobs, both of them trimming:

* A **package** is trimmed at the front and back. A wire package that opens
  "this morning" does not belong in a noon show as written, and the fix is to
  cut the sentence rather than to rewrite it (§11.26).
* A **soundbite** is cut out of whatever the wire shipped. Sometimes that is a
  clean twenty seconds; sometimes it is a five-minute raw interview and we need
  two sentences out of the middle.

A SOT may hold **two or three clips**, from one speaker or from several people
across different sources (§11.26). `Soundbite` is therefore a list of `Clip`s,
each carrying its own source reference, because §5 R15 says an editor has to be
able to find every one of them.

This module is pure. Nothing here downloads, decodes, or runs a model — see
`newscast.media` for that, including the §11.7 requirement to delete the video
once the transcript exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence

# A sentence ends here, unless the token before it is an abbreviation.
SENT_END = re.compile(r"[.!?][\"')\]]*\s*$")
CLAUSE_END = (",", ";", ":", "—", "-")
CONJ = frozenset({
    "and", "but", "or", "so", "because", "which", "that", "while", "whereas",
    "although", "though", "since", "when", "where", "if", "then", "however",
})
ABBREV = frozenset({
    "mr", "mrs", "ms", "dr", "sgt", "lt", "gov", "sen", "rep", "st", "jr", "sr",
    "vs", "inc", "co", "corp", "dept", "no", "approx", "u.s", "d.c", "a.m", "p.m",
})

# A dotted acronym — F.B.I., I.S.P., U.S. News copy is full of them, and ASR
# punctuates them. Erring toward joining is the right side to err on: a
# sentence wrongly joined still cuts at a real boundary, while one wrongly
# split puts an in-point in the middle of somebody saying "F.B."
ACRONYM = re.compile(r"^(?:[a-z]\.)+[a-z]?$")

# What Whisper invents over silence, music, and wire slates. Broadcast video
# opens on a slate and closes on a logo sting, so both ends are exposed.
FILLER = re.compile(
    r"^\W*(thanks? (you )?for watching|thanks for listening|subtitles? by.*|"
    r"transcription by.*|subscribe.*|please subscribe.*|\[?music\]?|"
    r"\[?applause\]?|you|bye|okay|thank you)\W*$",
    re.I,
)


class TranscriptError(RuntimeError):
    """Raised instead of exiting, so this module stays importable."""


@dataclass(frozen=True)
class Word:
    """One word with its timestamps, as ASR reports it."""

    text: str
    start: float
    end: float


@dataclass
class Sentence:
    """A run of words with a start and an end.

    Sentences, not words, are the unit a clip is cut on. A producer never asks
    an editor for 4.82 seconds of somebody mid-phrase.
    """

    idx: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def timecode(seconds: float) -> str:
    """`0:13` — the §4 form, which is what a duration cue carries."""
    seconds = max(0.0, seconds)
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"


@dataclass(frozen=True)
class Clip:
    """One continuous span of a source video, cut on sentence boundaries.

    `source_ref` is what R15 needs: the wire story the file came from. Two
    clips in one soundbite can carry different ones (§11.26).
    """

    source_ref: str
    start: float
    end: float
    text: str
    speaker: str = ""
    first_sentence: int = -1
    last_sentence: int = -1

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def in_out(self) -> str:
        return f"{timecode(self.start)}–{timecode(self.end)}"

    def editor_note(self) -> str:
        """R15 — what the editor has to do, precisely enough to do it."""
        who = f"{self.speaker}, " if self.speaker else ""
        return (
            f"pull {who}{self.in_out} ({timecode(self.duration)}) from {self.source_ref}"
        )


@dataclass
class Soundbite:
    """One SOT, which may be several clips cut together (§11.26)."""

    clips: list[Clip] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    @property
    def speakers(self) -> list[str]:
        out: list[str] = []
        for c in self.clips:
            if c.speaker and c.speaker not in out:
                out.append(c.speaker)
        return out

    @property
    def sources(self) -> list[str]:
        out: list[str] = []
        for c in self.clips:
            if c.source_ref and c.source_ref not in out:
                out.append(c.source_ref)
        return out

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.clips if c.text)

    def editor_notes(self) -> list[str]:
        """One note per clip, in the order they are cut together.

        A single-clip bite reads as itself. A multi-clip bite is numbered,
        because "the second one" is ambiguous to an editor holding three files.
        """
        if len(self.clips) == 1:
            return [self.clips[0].editor_note()]
        return [
            f"clip {n} of {len(self.clips)}: {c.editor_note()}"
            for n, c in enumerate(self.clips, start=1)
        ]


@dataclass
class Transcript:
    """The authoritative verbatim of one video file.

    `media_duration` is the file's real length from ffprobe — kept because the
    gap between it and the spoken content is exactly the b-roll §11.23 warns
    the wire's printed number is counting.
    """

    source_ref: str = ""
    media_ref: str = ""
    media_duration: float = 0.0
    sentences: list[Sentence] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def spoken_start(self) -> float:
        return self.sentences[0].start if self.sentences else 0.0

    @property
    def spoken_end(self) -> float:
        return self.sentences[-1].end if self.sentences else 0.0

    @property
    def spoken_duration(self) -> float:
        return max(0.0, self.spoken_end - self.spoken_start)

    def clip(
        self,
        first: int,
        last: int,
        *,
        speaker: str = "",
        source_ref: str = "",
    ) -> Clip:
        """A clip spanning sentences `first`..`last` inclusive."""
        if not self.sentences:
            raise TranscriptError("no sentences to clip")
        first = max(0, min(first, len(self.sentences) - 1))
        last = max(first, min(last, len(self.sentences) - 1))
        span = self.sentences[first : last + 1]
        return Clip(
            source_ref=source_ref or self.source_ref,
            start=span[0].start,
            end=span[-1].end,
            text=" ".join(s.text for s in span),
            speaker=speaker,
            first_sentence=first,
            last_sentence=last,
        )


# ---------------------------------------------------------------------------
# Words to sentences
# ---------------------------------------------------------------------------


def _split_point(cur: Sequence[Word]) -> int:
    """When a sentence hits the char cap, cut at a clause boundary.

    Searching the back half only keeps the cut near the cap instead of halving
    every long sentence.
    """
    lo = max(len(cur) // 2, 1)
    for j in range(len(cur) - 1, lo - 1, -1):
        if cur[j].text.strip().endswith(CLAUSE_END):
            return j + 1
    for j in range(len(cur) - 1, lo - 1, -1):
        if cur[j].text.strip().lower() in CONJ:
            return j
    return len(cur)


def group_sentences(
    words: Iterable[Word],
    max_gap: float = 1.0,
    max_chars: int = 320,
    min_chars: int = 25,
) -> list[Sentence]:
    """Group ASR words into timestamped sentences.

    Three things end a sentence: terminal punctuation, a silence longer than
    `max_gap`, and running past `max_chars`. The gap rule matters more here
    than in a lecture — an interview subject pauses, and ASR punctuation over
    broadcast audio is not dependable.
    """
    words = [w for w in words if w.text.strip()]
    sents: list[Sentence] = []
    cur: list[Word] = []

    def text_of(ws: Sequence[Word]) -> str:
        return "".join(w.text for w in ws).strip()

    def emit(chunk: Sequence[Word]) -> None:
        t = text_of(chunk)
        if t:
            sents.append(Sentence(len(sents), chunk[0].start, chunk[-1].end, t))

    for w in words:
        if cur and (w.start - cur[-1].end) > max_gap and len(text_of(cur)) >= min_chars:
            emit(cur)
            cur = []
        cur.append(w)
        t = text_of(cur)
        if len(t) >= max_chars:
            p = _split_point(cur)
            emit(cur[:p])
            cur = list(cur[p:])
            continue
        if SENT_END.search(t) and len(t) >= min_chars:
            tail = re.sub(r"[^\w.]", "", t.split()[-1]).lower()
            if ACRONYM.match(tail):
                continue
            tail = tail.rstrip(".")
            if tail in ABBREV or (len(tail) == 1 and tail.isalpha()):
                continue
            emit(cur)
            cur = []
    if cur:
        emit(cur)
    return sents


def drop_hallucinations(sentences: Sequence[Sentence]) -> list[Sentence]:
    """ASR invents filler over silence and can lock into repeat loops.

    Broadcast video is full of both: a slate at the head, nat sound under
    b-roll, a logo sting at the tail.
    """
    out: list[Sentence] = []
    prev = ""
    for s in sentences:
        t = s.text.strip()
        norm = re.sub(r"\W+", " ", t).strip().lower()
        toks = norm.split()
        looped = len(toks) >= 8 and len(set(toks)) <= max(2, len(toks) // 6)
        if FILLER.match(t) or (norm and norm == prev) or looped:
            continue
        prev = norm
        out.append(replace(s, idx=len(out)))
    return out


def build_transcript(
    words: Iterable[Word],
    *,
    source_ref: str = "",
    media_ref: str = "",
    media_duration: float = 0.0,
    **group_kwargs,
) -> Transcript:
    sentences = drop_hallucinations(group_sentences(words, **group_kwargs))
    return Transcript(
        source_ref=source_ref,
        media_ref=media_ref,
        media_duration=media_duration,
        sentences=sentences,
    )


# ---------------------------------------------------------------------------
# Finding a speaker's words in the transcript
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


@dataclass(frozen=True)
class Match:
    """Where a run of known text lands in the transcript.

    `score` is what makes a stale wire script visible instead of silent
    (§11.7): a package rebuilt since the script was written matches poorly, and
    a poor match is a flag for a human, not an in-point to trust.
    """

    first: int
    last: int
    score: float

    @property
    def confident(self) -> bool:
        return self.score >= 0.62


def locate(transcript: Transcript, quote: str, max_sentences: int = 6) -> Optional[Match]:
    """Find the sentence run that best matches `quote`.

    The wire script gives us the words; only the transcript knows when they
    were said. Runs are scored rather than a single sentence, because ASR
    splits a bite differently than a wire typist does.
    """
    if not transcript.sentences or not _norm(quote):
        return None
    best: Optional[Match] = None
    n = len(transcript.sentences)
    for i in range(n):
        for j in range(i, min(n, i + max_sentences)):
            span = " ".join(s.text for s in transcript.sentences[i : j + 1])
            score = similarity(span, quote)
            if best is None or score > best.score:
                best = Match(i, j, score)
    return best


def locate_bite(
    transcript: Transcript,
    quote: str,
    *,
    speaker: str = "",
    source_ref: str = "",
) -> Optional[Clip]:
    """A clip for a quote the wire attributes to somebody.

    Returns None when nothing in the transcript resembles the quote — which is
    the stale-script case, and the caller has to fall back to picking a bite
    from the transcript itself.
    """
    match = locate(transcript, quote)
    if match is None or not match.confident:
        return None
    return transcript.clip(
        match.first, match.last, speaker=speaker, source_ref=source_ref
    )


# ---------------------------------------------------------------------------
# Choosing a bite when the wire does not hand us one
# ---------------------------------------------------------------------------


def select_bite(
    transcript: Transcript,
    *,
    target_seconds: float = 12.0,
    max_seconds: float = 20.0,
    min_seconds: float = 4.0,
    exclude: Sequence[int] = (),
    speaker: str = "",
    source_ref: str = "",
) -> Optional[Clip]:
    """Pick one or two sentences that make a usable soundbite.

    This is the five-minute-raw-interview case (§11.26): nothing marks the good
    twenty seconds, so take the run closest to the target length, preferring
    the shorter of two equally close runs — a bite that runs long costs the
    whole block, and one that runs short costs only itself.

    `exclude` holds sentence indices already spoken for, so a second call
    returns a *different* bite for the second leg of a VOSOTVOSOT.
    """
    blocked = set(exclude)
    best: Optional[Clip] = None
    best_key: Optional[tuple[float, float]] = None
    n = len(transcript.sentences)
    for i in range(n):
        if i in blocked:
            continue
        for j in range(i, min(n, i + 3)):
            if j in blocked:
                break
            clip = transcript.clip(i, j, speaker=speaker, source_ref=source_ref)
            if clip.duration > max_seconds:
                break
            if clip.duration < min_seconds:
                continue
            key = (abs(clip.duration - target_seconds), clip.duration)
            if best_key is None or key < best_key:
                best, best_key = clip, key
    return best


def build_soundbite(
    picks: Sequence[Clip],
    *,
    max_clips: int = 3,
) -> Soundbite:
    """Cut up to three clips together into one SOT (§11.26).

    Beyond three the bite stops reading as a soundbite and starts reading as a
    package the anchor is not narrating, so the extras are dropped rather than
    silently stacked.
    """
    return Soundbite(clips=list(picks[:max_clips]))


# ---------------------------------------------------------------------------
# Trimming a package
# ---------------------------------------------------------------------------


@dataclass
class Trim:
    """A package cut down to what a noon show can run (§11.26).

    `clip` is what survives; `dropped_head` and `dropped_tail` are the
    sentences cut, kept so the editor note can say what came off and why.
    """

    clip: Clip
    dropped_head: list[Sentence] = field(default_factory=list)
    dropped_tail: list[Sentence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.clip.duration

    def editor_note(self) -> str:
        parts = [self.clip.editor_note()]
        parts.extend(self.reasons)
        return "; ".join(parts)


def trim_package(
    transcript: Transcript,
    daypart_phrases: Sequence[str],
    *,
    max_seconds: Optional[float] = None,
    source_ref: str = "",
) -> Trim:
    """Trim a package's head and tail for the noon show.

    Two cuts, in order:

    1. **Daypart.** A package that opens "this morning" is written for another
       show (§5 R13). Cutting the sentence is the producer's move — rewriting
       it is not possible, because the reporter's voice is in the file.
       Only leading sentences go: a "this morning" in the middle is the story,
       not the daypart of the newscast.
    2. **Length.** If the package still runs past `max_seconds`, drop whole
       sentences off the tail until it fits, because the front of a package
       carries the news and the back carries the wrap.
    """
    sentences = transcript.sentences
    if not sentences:
        raise TranscriptError("cannot trim a package with no transcript")

    phrases = [p.lower() for p in daypart_phrases]
    first, dropped_head, reasons = 0, [], []
    while first < len(sentences) - 1:
        lowered = sentences[first].text.lower()
        hit = next((p for p in phrases if p in lowered), None)
        if hit is None:
            break
        dropped_head.append(sentences[first])
        reasons.append(f'cut the opening line for daypart language ("{hit}")')
        first += 1

    last = len(sentences) - 1
    dropped_tail: list[Sentence] = []
    if max_seconds is not None:
        while last > first and (sentences[last].end - sentences[first].start) > max_seconds:
            dropped_tail.insert(0, sentences[last])
            last -= 1
        if dropped_tail:
            reasons.append(
                f"trimmed {len(dropped_tail)} sentence(s) off the tail to make "
                f"{timecode(max_seconds)}"
            )

    return Trim(
        clip=transcript.clip(first, last, source_ref=source_ref),
        dropped_head=dropped_head,
        dropped_tail=dropped_tail,
        reasons=reasons,
    )
