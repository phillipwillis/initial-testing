"""Transcribe one video file and print what a producer would do with it (§15).

    python3 -m newscast.transcribe market.mp4
    python3 -m newscast.transcribe pkg.mp4 --trim --max-seconds 90
    python3 -m newscast.transcribe interview.mp4 --bite 20 --bites 2

**The video is deleted when this finishes** (§11.7). The agent does no editing;
it needs the words and the timestamps so an editor can find the clip, and
nothing else. `--keep-video` is a debugging escape hatch, not the normal case.

Nothing here reaches the wire. Getting the file off Newsource is still a manual
step — download it by hand and point this at it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ShowConfig
from .media import DEFAULT_ASR_MODEL, MediaError, transcribe_media
from .transcript import select_bite, timecode, trim_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newscast.transcribe", description=__doc__.splitlines()[0]
    )
    parser.add_argument("video", help="the video file to transcribe")
    parser.add_argument("--source", default="", help="the wire story number, for R15")
    parser.add_argument("--model", default=DEFAULT_ASR_MODEL, help="ASR model")
    parser.add_argument("--keep-video", action="store_true",
                        help="do not delete the video (§11.7 says delete it)")
    parser.add_argument("--trim", action="store_true",
                        help="trim it as a package: daypart open off the front")
    parser.add_argument("--max-seconds", type=float, default=None,
                        help="with --trim, also cut the tail down to this")
    parser.add_argument("--bite", type=float, default=None, metavar="SECONDS",
                        help="pick a soundbite of about this length")
    parser.add_argument("--bites", type=int, default=1,
                        help="how many different bites to pick (§3 caps a story at 2)")
    args = parser.parse_args(argv)

    path = Path(args.video)
    if not args.keep_video:
        print(f"note: {path.name} will be deleted once it is transcribed (§11.7)\n")

    try:
        transcript = transcribe_media(
            path,
            source_ref=args.source or path.stem,
            model_name=args.model,
            keep_video=args.keep_video,
        )
    except MediaError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    print(f"file duration    {timecode(transcript.media_duration)}  (ffprobe)")
    print(f"spoken content   {timecode(transcript.spoken_duration)}  "
          f"({len(transcript.sentences)} sentences)")
    gap = transcript.media_duration - transcript.spoken_duration
    print(f"gap              {timecode(gap)}  <- b-roll the wire's number counts (§11.23)")
    print()

    for s in transcript.sentences:
        print(f"  [{timecode(s.start)}–{timecode(s.end)}] {s.text}")
    print()

    if args.trim:
        trim = trim_package(transcript, ShowConfig().daypart_phrases,
                            max_seconds=args.max_seconds,
                            source_ref=args.source)
        print("--- trimmed as a package ---")
        print(f"  [PKG {timecode(trim.duration)}]")
        print(f"  [NOTE: {trim.editor_note()}]")
        for dropped in trim.dropped_head:
            print(f"  off the front: {dropped.text}")
        for dropped in trim.dropped_tail:
            print(f"  off the tail : {dropped.text}")
        print()

    if args.bite:
        used: list[int] = []
        print("--- soundbites ---")
        for n in range(max(1, args.bites)):
            clip = select_bite(transcript, target_seconds=args.bite,
                               max_seconds=args.bite * 1.5, exclude=used,
                               source_ref=args.source)
            if clip is None:
                print("  nothing else long enough")
                break
            used.extend(range(clip.first_sentence, clip.last_sentence + 1))
            print(f"  [SOT {timecode(clip.duration)}]")
            print(f"  [NOTE: {clip.editor_note()}]")
            print(f'  "{clip.text}"')
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
