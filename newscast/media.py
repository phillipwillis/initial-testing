"""The impure half of the transcript pipeline (§11.7).

Everything here shells out, downloads, or loads a model. It is deliberately
thin, for the same reason `newscast.browser` is thin: the machine that can
reach the wires is not the machine this code is written on (§14), so the part
that has to be debugged there stays small and fails loudly, and every decision
worth testing lives in `newscast.transcript` as a pure function.

§11.7 is a hard requirement, not a nicety: **the video is deleted once the
transcript exists.** The agent does no editing. It needs the words and the
timestamps so an editor can find the clip; it has no use for the file itself,
and leaving broadcast video on a work machine is somebody's problem later.
`transcribe_media` deletes in a `finally`, so a crash mid-transcription does
not leave the file behind.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .transcript import Transcript, TranscriptError, Word, build_transcript

# faster-whisper's small English model. Big enough for broadcast audio, small
# enough to run on a work machine's CPU before a noon show.
DEFAULT_ASR_MODEL = "small.en"


class MediaError(RuntimeError):
    """A tool was missing or a subprocess failed."""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(
            f"{cmd[0]} failed ({proc.returncode}):\n{proc.stderr.strip()[-2000:]}"
        )
    return proc


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def require(binary: str) -> None:
    if not have(binary):
        raise MediaError(
            f"{binary} is not on PATH — the transcript pipeline needs it "
            "(python3 -m newscast.capture doctor checks for it)"
        )


def probe_duration(path: os.PathLike | str) -> float:
    """The file's real length, which is not the wire's printed number (§11.23)."""
    require("ffprobe")
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ]).stdout.strip()
    try:
        return float(out)
    except ValueError as exc:
        raise MediaError(f"ffprobe gave no duration for {path}: {out!r}") from exc


def extract_audio(video: Path, wav: Path) -> Path:
    """16 kHz mono, which is what the ASR model wants anyway."""
    require("ffmpeg")
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", str(wav),
    ])
    return wav


def asr_words(wav: Path, model_name: str = DEFAULT_ASR_MODEL, language: str = "en") -> list[Word]:
    """Run ASR and return words with timestamps.

    Import is local so the rest of the package stays importable — and testable
    — on a machine with no faster-whisper and no model downloaded.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise MediaError(
            "faster-whisper is not installed (pip install faster-whisper)"
        ) from exc

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(wav),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
        # Broadcast video opens on a slate and runs nat sound under b-roll,
        # so the decode needs the guards against repetition loops.
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or ():
            if w.word.strip():
                words.append(Word(text=w.word, start=float(w.start), end=float(w.end)))
    return words


@contextmanager
def scratch_video(path: Path) -> Iterator[Path]:
    """Hold a video only as long as the transcript needs it (§11.7)."""
    try:
        yield path
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def transcribe_media(
    video: Path,
    *,
    source_ref: str = "",
    media_ref: str = "",
    model_name: str = DEFAULT_ASR_MODEL,
    keep_video: bool = False,
) -> Transcript:
    """Video in, transcript out, video gone.

    `keep_video` exists only for debugging on the work machine, and defaults
    off because §11.7 says the file does not stick around.
    """
    video = Path(video)
    if not video.exists():
        raise MediaError(f"no such file: {video}")

    workdir = Path(tempfile.mkdtemp(prefix="newscast-asr-"))
    wav = workdir / "audio16k.wav"
    try:
        duration = probe_duration(video)
        extract_audio(video, wav)
        words = asr_words(wav, model_name=model_name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if not keep_video:
            try:
                video.unlink(missing_ok=True)
            except OSError:
                pass

    return build_transcript(
        words,
        source_ref=source_ref,
        media_ref=media_ref or video.name,
        media_duration=duration,
    )
