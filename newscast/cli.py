"""Command line entry point, so milestone 1 is demonstrable on its own (§10).

    python3 -m newscast validate tests/fixtures/show_broken.txt
    python3 -m newscast summary  tests/fixtures/show_clean.txt
    python3 -m newscast rules
    python3 -m newscast readtime --text "VENDORS CLOSE UP SHOP AT TWO."

The §11 answers are baked into ShowConfig. These flags override them for a
what-if, without editing code:

    python3 -m newscast validate show.txt --budget 1B=300 --wpm 170
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from newscast.config import BlockConfig, ShowConfig
from newscast.markup import MarkupError, parse_show
from newscast.readtime import estimate_read_time
from newscast.rules import all_rules
from newscast.validator import show_summary, validate_show


def _apply_block_overrides(
    config: ShowConfig, field: str, assignments: list[str]
) -> ShowConfig:
    """--budget 1A=420 --anchors 1A=MEGAN,JAY --shot 1A=CAM2"""
    overrides: dict[str, str] = {}
    for item in assignments or []:
        if "=" not in item:
            raise SystemExit(f"expected BLOCK=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        overrides[name.strip().upper()] = value.strip()

    def updated(block: BlockConfig) -> BlockConfig:
        if block.name not in overrides:
            return block
        raw = overrides[block.name]
        if field == "budget_seconds":
            return dataclasses.replace(block, budget_seconds=float(raw))
        if field == "anchors":
            return dataclasses.replace(
                block, anchors=tuple(a.strip() for a in raw.split(",") if a.strip())
            )
        return dataclasses.replace(block, **{field: raw})

    return dataclasses.replace(config, blocks=tuple(updated(b) for b in config.blocks))


def _config_from_args(args: argparse.Namespace) -> ShowConfig:
    config = ShowConfig()
    if getattr(args, "wpm", None):
        config = dataclasses.replace(config, words_per_minute=args.wpm)
    if getattr(args, "cg_ceiling", None):
        config = dataclasses.replace(config, cg_char_ceiling=args.cg_ceiling)
    config = _apply_block_overrides(config, "budget_seconds", getattr(args, "budget", []))
    config = _apply_block_overrides(config, "anchors", getattr(args, "anchors", []))
    config = _apply_block_overrides(config, "default_shot", getattr(args, "shot", []))
    return config


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_show(path: str):
    try:
        return parse_show(_read(path))
    except MarkupError as exc:
        raise SystemExit(f"{path}: {exc}")


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wpm", type=float, help="anchor read rate (default 160)")
    parser.add_argument("--cg-ceiling", type=int, help="lower-third character limit (default 39)")
    parser.add_argument(
        "--budget", action="append", default=[], metavar="BLOCK=SECONDS",
        help="fixed block time budget, repeatable (§11.1)",
    )
    parser.add_argument(
        "--anchors", action="append", default=[], metavar="BLOCK=NAME,NAME",
        help="override the block anchor roster, repeatable (§11.2)",
    )
    parser.add_argument(
        "--shot", action="append", default=[], metavar="BLOCK=CAM",
        help="override the block default shot, e.g. 1B=CAM3 OX5 (§11.3)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newscast", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="run the §5 rule engine over a rundown")
    p_validate.add_argument("path", help="rundown file, or - for stdin")
    p_validate.add_argument("--only", nargs="+", metavar="CODE", help="run only these rules")
    p_validate.add_argument("--quiet", action="store_true", help="hide INFO lines")
    _add_config_args(p_validate)

    p_summary = sub.add_parser("summary", help="print the rundown with timings")
    p_summary.add_argument("path")
    _add_config_args(p_summary)

    sub.add_parser("rules", help="list the registered rules")

    p_readtime = sub.add_parser("readtime", help="estimate seconds of anchor copy")
    p_readtime.add_argument("--text", help="copy to estimate; omit to read stdin")
    p_readtime.add_argument("--wpm", type=float)

    args = parser.parse_args(argv)

    if args.command == "rules":
        for r in all_rules():
            print(f"{r.code:<4} {r.summary:<60} {r.spec_ref}")
        return 0

    if args.command == "readtime":
        copy = args.text if args.text is not None else sys.stdin.read()
        print(f"{estimate_read_time(copy, _config_from_args(args)):.1f}s")
        return 0

    config = _config_from_args(args)
    show = _load_show(args.path)

    if args.command == "summary":
        print(show_summary(show, config))
        return 0

    report = validate_show(show, config, only=args.only)
    print(report.format(show_info=not args.quiet))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
