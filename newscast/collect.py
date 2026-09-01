"""A full CNN collection run (§6 phases 0-4, build order §10.3).

    cd ~/Desktop/monkey_king/initial-testing-<branch>
    python3 -m newscast.collect --count 50

Collects story stubs off the wire, grades them against each other, culls to
what a noon show can use, pulls the full script for each survivor, assembles it
into §4 markup, validates it, and writes the lot to a text file — including the
keystroke plan, which is literally what the Inception writer will type.

Nothing is written to Inception. This run ends at a file.

Two honest limits, both marked in the output:

* Grading is `newscast.scoring`, a deterministic stand-in for the Opus grader
  §11.12 calls for. It ranks on what a stub carries, not on judgement.
* Copy is not rewritten. The wire's words go through unchanged, with an editor
  note wherever a human has to look.
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from newscast.assemble import Assembly, assemble_story
from newscast.browser import (
    LANDING,
    collapse_open_rows,
    expand_row,
    login,
    scroll_for_rows,
    wait_for_details,
    wait_for_rows,
)
from newscast.capture import DEFAULT_DEBUG_PORT, attach, scrub_html
from newscast.config import ShowConfig
from newscast.env import describe, load_env, require
from newscast.keystrokes import plan_keystrokes
from newscast.model import Block, Show
from newscast.scoring import Grade, compile_words, grade_pool, similarity
from newscast.timing import story_seconds
from newscast.validator import validate_show
from newscast.wires.cnn import parse_listing, parse_story_details
from newscast.wires.cnn_script import WireScript, parse_wire_script
from newscast.wires.stub import StoryStub

REQUIRED_KEYS = ("CNN_USER", "CNN_PASS")


def log(step: str, message: str = "", **extra) -> None:
    tail = ("  " + ", ".join(f"{k}={v}" for k, v in extra.items())) if extra else ""
    print(f"[{step:<9}] {message}{tail}", flush=True)


# --------------------------------------------------------------------------
# culling
# --------------------------------------------------------------------------


@dataclass
class Cull:
    kept: list[Grade] = field(default_factory=list)
    dropped: list[tuple[Grade, str]] = field(default_factory=list)


def cull(
    grades: list[Grade],
    keep: int = 8,
    max_packages: int = 2,
    duplicate_threshold: float = 0.45,
    config: ShowConfig | None = None,
) -> Cull:
    """Reduce a ranked pool to what a noon show can actually carry.

    Rank alone does not decide this. §5 R9 caps packages per block, §11.10 rules
    out sports, material with neither script nor video cannot be built into a
    story however well it scores — and, the one that bites hardest, **the same
    story arrives several times**.

    CNN files a soundbite per speaker, so one shooting turns up as three rows:
    the FBI on the reward, the attorney on the party, the FBI on the tips.
    §7 scores all three highly and identically, and corroboration scores them
    *up* for agreeing with each other. Ranked alone they take the top of the
    show and air the same story three times. So a story close enough to one
    already kept is dropped, and the note says which one it duplicates.
    """
    config = config or ShowConfig()
    result = Cull()
    packages = 0

    for grade in grades:
        stub = grade.stub

        if not stub.has_script and not stub.has_video:
            result.dropped.append((grade, "no script and no video — nothing to build from"))
            continue

        twin = next(
            (
                kept
                for kept in result.kept
                if similarity(stub, kept.stub) > duplicate_threshold
            ),
            None,
        )
        if twin is not None:
            result.dropped.append(
                (grade, f"same story as {twin.stub.slug[:44]!r}, which ranked higher")
            )
            continue

        if _is_sport(stub):
            result.dropped.append((grade, "sports — the noon show carries none (§11.10)"))
            continue

        if stub.footage_type.upper() in {"PKG", "DONUT", "LOOK LIVE"}:
            if packages >= max_packages:
                result.dropped.append(
                    (grade, f"package budget is {max_packages} per block (§5 R9)")
                )
                continue
            packages += 1

        if len(result.kept) >= keep:
            result.dropped.append((grade, f"below the cut — only {keep} slots"))
            continue

        result.kept.append(grade)

    return result


SPORT_WORDS = (
    "nfl", "nba", "mlb", "nhl", "touchdown", "quarterback", "playoff*",
    "world series", "super bowl", "olympic*", "rams", "yankees", "lakers",
)

# Matched on word boundaries. As a substring, "nfl" fires inside the Spanish
# word "conflicto" and culls a war story as sports.
_SPORT_RE = compile_words(SPORT_WORDS)


def _is_sport(stub: StoryStub) -> bool:
    return bool(_SPORT_RE.search(f"{stub.slug} {stub.teaser}"))


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


@dataclass
class Collected:
    stub: StoryStub
    grade: Grade
    wire: Optional[WireScript] = None
    assembly: Optional[Assembly] = None
    error: str = ""


def collect_stubs(driver, target: int) -> list[StoryStub]:
    driver.get(LANDING)
    rendered = wait_for_rows(driver)
    log("collect", "list rendered", rows=rendered)

    counts = scroll_for_rows(driver, target)
    log("collect", "scrolled", passes=len(counts), rows=counts[-1] if counts else 0)

    stubs = parse_listing(driver.page_source)
    log("collect", "parsed", stubs=len(stubs))
    return stubs[:target]


def fetch_script(driver, stub: StoryStub, index: int) -> tuple[Optional[WireScript], str]:
    """Expand one story and read its script (§6 phase 3)."""
    opened = expand_row(driver, index)
    if not opened.get("ok"):
        return None, f"could not expand row {index}: {opened}"

    if not wait_for_details(driver):
        collapse_open_rows(driver)
        return None, "the detail table never rendered"

    details = parse_story_details(driver.page_source)
    collapse_open_rows(driver)

    script_text = details.get("Script", "")
    if not script_text:
        return None, "expanded, but the story carries no script"

    wire = parse_wire_script(script_text)
    wire.title = wire.title or details.get("Title", "")
    wire.trt = wire.trt or details.get("TRT", "")
    wire.footage_type = wire.footage_type or details.get("Footage Type", "").upper()
    return wire, ""


def run(
    driver,
    count: int,
    keep: int,
    out_path: str,
    config: ShowConfig | None = None,
) -> str:
    config = config or ShowConfig()

    stubs = collect_stubs(driver, count)
    if not stubs:
        raise SystemExit("no stories collected — is the listing empty or the session out?")

    grades = grade_pool(stubs)
    log("grade", "ranked the pool", stories=len(grades), top=f"{grades[0].total:.2f}")

    culled = cull(grades, keep=keep, config=config)
    log("cull", "kept", kept=len(culled.kept), dropped=len(culled.dropped))

    # The listing order is what the row indices refer to.
    order = {id(s): i for i, s in enumerate(stubs)}
    collected: list[Collected] = []

    for position, grade in enumerate(culled.kept, start=1):
        stub = grade.stub
        index = order.get(id(stub), 0)
        log("expand", f"{position}/{len(culled.kept)}", story=stub.slug[:48])
        wire, error = fetch_script(driver, stub, index)
        item = Collected(stub=stub, grade=grade, wire=wire, error=error)

        if wire is not None:
            try:
                item.assembly = assemble_story(wire, stub, config=config)
            except Exception as exc:
                item.error = f"assembly failed: {type(exc).__name__}: {exc}"
        collected.append(item)
        time.sleep(0.8)

    text = write_report(collected, culled, stubs, out_path, config)
    return text


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def _rule(char: str = "=", width: int = 78) -> str:
    return char * width


def write_report(
    collected: list[Collected],
    culled: Cull,
    pool: list[StoryStub],
    out_path: str,
    config: ShowConfig,
) -> str:
    built = [c for c in collected if c.assembly]
    show = Show(blocks=[Block(half=1, label="A", stories=[c.assembly.story for c in built])])
    report = validate_show(show, config)

    lines: list[str] = []
    add = lines.append

    add(_rule())
    add("CNN NEWSOURCE COLLECTION RUN")
    add(f"{datetime.now():%Y-%m-%d %H:%M}")
    add(_rule())
    add("")
    add(f"collected   {len(pool)} stubs")
    add(f"kept        {len(culled.kept)}")
    add(f"dropped     {len(culled.dropped)}")
    add(f"assembled   {len(built)}")
    add("")
    add("Grading is newscast.scoring, a deterministic stand-in for the Opus grader")
    add("§11.12 calls for. Copy is not rewritten: the wire's words go through as")
    add("written, with an editor note wherever a human has to look.")
    add("")

    add(_rule())
    add("RANKING")
    add(_rule())
    for position, grade in enumerate(culled.kept, start=1):
        add(f"{position:>3}. {grade.total:6.2f}  {grade.stub.slug[:60]}")
        add(f"       {grade.explain()[8:]}")
        for note in grade.notes:
            add(f"       - {note}")
    add("")

    add(_rule())
    add("CULLED")
    add(_rule())
    for grade, reason in culled.dropped:
        add(f"  {grade.total:6.2f}  {grade.stub.slug[:52]}")
        add(f"          {reason}")
    add("")

    add(_rule())
    add("WHAT WOULD BE PASSED TO THE INCEPTION WRITER")
    add(_rule())
    add("")
    add("Each story below is the validated §4 markup, the CGs that go into")
    add("Inception's CG editor, and the keystroke plan the writer actually types.")
    add("Inception generates its own markup from shortcuts (§13.6), so the")
    add("keystrokes — not the markup — are what reaches the CMS.")
    add("")

    for position, item in enumerate(collected, start=1):
        add(_rule("-"))
        add(f"{position}. {item.stub.slug}")
        add(_rule("-"))
        add(f"story number : {item.stub.story_number or item.stub.id or '(none)'}")
        add(f"source       : {item.stub.source}")
        add(f"footage type : {item.stub.footage_type or '(wire article)'}")
        add(f"wire duration: {item.stub.wire_duration_seconds or '(none)'}  "
            "<- a sort key, never a TRT (§11.23)")
        if item.stub.embargo:
            add(f"EMBARGO      : {item.stub.embargo}")

        if item.error:
            add("")
            add(f"  NOT BUILT: {item.error}")
            add("")
            continue

        assembly = item.assembly
        add(f"read time    : {story_seconds(assembly.story, config):.1f}s")
        add("")
        add("  --- script (§4 markup, validated) ---")
        for line in assembly.markup.splitlines():
            add(f"  {line}")
        add("")
        add("  --- CGs to write into Inception ---")
        for cg in assembly.cgs:
            add(f"  [{len(cg):>2}] {cg}")
        add("")
        if assembly.notes:
            add("  --- editor notes ---")
            for note in assembly.notes:
                add(f"  * {note}")
            add("")
        plan = plan_keystrokes(assembly.story, config)
        add("  --- keystrokes the Inception writer types ---")
        for step in plan.steps:
            add(f"  {step}")
        if plan.warnings:
            add("")
            add("  --- keystroke warnings ---")
            for warning in plan.warnings:
                add(f"  ! {warning}")
        add("")

    add(_rule())
    add("VALIDATION (§5 rule engine, all kept stories as one block)")
    add(_rule())
    add(report.format(show_info=True))
    add("")
    add("Block-level rules (R10 bump, R12 anchor pattern, R14 budget) fire here")
    add("because these stories have not been slotted into a rundown yet — that is")
    add("§10.7, and it is not part of this run.")

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def run_offline(
    html_paths: list[str], keep: int, out_path: str, config: ShowConfig | None = None
) -> str:
    """The same pipeline over saved captures, with no browser.

    Grading, culling, assembly, validation and the report are all pure, so the
    only thing a browser adds is the fetching. Being able to run the rest
    against saved HTML means the pipeline is testable on any machine, and a run
    can be re-analysed without going back to the wire.

    A story's script is only available if its capture had that row expanded, so
    stories collected this way are often stubs without scripts.
    """
    config = config or ShowConfig()
    stubs: list[StoryStub] = []
    scripts: dict[str, WireScript] = {}

    for path in html_paths:
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        stubs.extend(parse_listing(html))
        details = parse_story_details(html)
        if details.get("Script") and details.get("Story Number"):
            wire = parse_wire_script(details["Script"])
            wire.title = wire.title or details.get("Title", "")
            wire.trt = wire.trt or details.get("TRT", "")
            wire.footage_type = wire.footage_type or details.get("Footage Type", "").upper()
            scripts[details["Story Number"]] = wire

    # Captures overlap, and the same story appears in several of them.
    unique: list[StoryStub] = []
    seen: set[tuple] = set()
    for stub in stubs:
        marker = (stub.story_number or stub.id or stub.slug, stub.timestamp_text)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(stub)

    log("offline", "loaded", captures=len(html_paths), stubs=len(unique),
        scripts=len(scripts))

    grades = grade_pool(unique)
    culled = cull(grades, keep=keep, config=config)
    log("cull", "kept", kept=len(culled.kept), dropped=len(culled.dropped))

    collected: list[Collected] = []
    for grade in culled.kept:
        stub = grade.stub
        wire = scripts.get(stub.story_number or "")
        item = Collected(stub=stub, grade=grade, wire=wire)
        if wire is None:
            item.error = "no script in the captures — this row was not expanded"
        else:
            try:
                item.assembly = assemble_story(wire, stub, config=config)
            except Exception as exc:
                item.error = f"assembly failed: {type(exc).__name__}: {exc}"
        collected.append(item)

    return write_report(collected, culled, unique, out_path, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newscast.collect", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--count", type=int, default=50, help="stubs to collect")
    parser.add_argument("--keep", type=int, default=8, help="stories to keep after culling")
    parser.add_argument("--out", help="output file (default: beside the .env)")
    parser.add_argument("--env-file")
    parser.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT)
    parser.add_argument(
        "--from-html",
        nargs="+",
        metavar="FILE",
        help="run the pipeline over saved captures instead of the live site",
    )
    args = parser.parse_args(argv)

    if args.from_html:
        out_path = args.out or "collection-run.txt"
        run_offline(args.from_html, args.keep, out_path)
        print(f"\nwrote {os.path.abspath(out_path)}\n")
        return 0

    values, env_path = load_env(args.env_file)
    log("env", f"read {env_path}" if env_path else "no .env found; using the environment")
    print(describe(values, REQUIRED_KEYS))
    missing = require(values, *REQUIRED_KEYS)
    if missing:
        raise SystemExit(f"\nMissing {', '.join(missing)} — put them in a .env.\n")

    out_path = args.out or (
        os.path.join(os.path.dirname(env_path), "collection-run.txt")
        if env_path
        else "collection-run.txt"
    )

    driver = attach(args.port)
    if not login(driver, values["CNN_USER"], values["CNN_PASS"]):
        raise SystemExit(
            "Could not sign in. If Newsource wants a second factor, sign in by hand\n"
            "in the open window and run this again."
        )

    run(driver, args.count, args.keep, out_path)
    print(f"\nwrote {os.path.abspath(out_path)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
