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
from newscast.llm import DEV_MODEL, Producer, producer as make_producer
from newscast.model import Block, Show
from newscast.scoring import (
    Grade,
    StoryGroup,
    compile_words,
    grade_pool,
    group_related,
)
from newscast.slotting import demo_holes, fill_holes, place_pool
from newscast.timing import story_seconds
from newscast.validator import validate_show
from newscast.wires.cnn import parse_listing, parse_story_details
from newscast.wires.cnn_script import WireScript, parse_wire_script
from newscast.wires.stub import StoryStub

REQUIRED_KEYS = ("CNN_USER", "CNN_PASS")


# The gap the agent may fill in each block. An assumption, and labelled as one
# wherever it reaches a report — the real holes come from the rundown (§11.20).
DEMO_HOLE_SECONDS = 150.0


def graded(stubs: list[StoryStub], prod: Optional[Producer]) -> tuple[list, str]:
    """Grade the pool with the model if there is one, the heuristic if not.

    Never lets a grading failure end the run. A show goes on air at noon
    whatever the API did, so a model that is over budget, unreachable or
    returning nonsense falls back to `newscast.scoring` and the report says so.
    """
    if prod is None:
        return grade_pool(stubs), ""
    try:
        grades = prod.grade_pool(stubs)
        grades.sort(key=lambda g: g.total, reverse=True)
        return grades, ""
    except Exception as exc:
        return grade_pool(stubs), (
            f"the model grader failed ({type(exc).__name__}: {exc}) — "
            "graded with the deterministic fallback instead"
        )


def placed(groups: list[StoryGroup], prod: Optional[Producer]) -> tuple[dict, str]:
    """Model placements keyed by slug, or none and a reason (§11.27)."""
    if prod is None:
        return {}, ""
    try:
        return prod.place_pool(groups), ""
    except Exception as exc:
        return {}, (
            f"the model slotter failed ({type(exc).__name__}: {exc}) — "
            "placed with the deterministic fallback instead"
        )


def log(step: str, message: str = "", **extra) -> None:
    tail = ("  " + ", ".join(f"{k}={v}" for k, v in extra.items())) if extra else ""
    print(f"[{step:<9}] {message}{tail}", flush=True)


# --------------------------------------------------------------------------
# culling
# --------------------------------------------------------------------------


@dataclass
class Cull:
    kept: list[StoryGroup] = field(default_factory=list)
    dropped: list[tuple[StoryGroup, str]] = field(default_factory=list)


def cull(
    groups: list[StoryGroup],
    keep: int = 8,
    max_packages: int = 2,
    config: ShowConfig | None = None,
) -> Cull:
    """Reduce ranked story groups to what a noon show can carry.

    Rank alone does not decide this. §5 R9 caps packages per block, §11.10 rules
    out sports, and material with neither script nor video cannot be built into
    a story however well it scores.

    Duplicates are not handled here any more. CNN files a row per speaker, and
    those rows are the same story with different soundbites — so they are merged
    upstream by `group_related` and become one composite (§3 VOSOTVOSOT), with
    each soundbite keeping its own source. Dropping them lost material a
    producer would have used.
    """
    config = config or ShowConfig()
    result = Cull()
    packages = 0

    for group in groups:
        stub = group.stub

        if not stub.has_script and not stub.has_video:
            result.dropped.append((group, "no script and no video — nothing to build from"))
            continue

        if _is_sport(stub):
            result.dropped.append((group, "sports — the noon show carries none (§11.10)"))
            continue

        if stub.footage_type.upper() in {"PKG", "DONUT", "LOOK LIVE"}:
            if packages >= max_packages:
                result.dropped.append(
                    (group, f"package budget is {max_packages} per block (§5 R9)")
                )
                continue
            packages += 1

        if len(result.kept) >= keep:
            result.dropped.append((group, f"below the cut — only {keep} slots"))
            continue

        result.kept.append(group)

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
    group: StoryGroup
    wire: Optional[WireScript] = None
    extra_bites: list[tuple[WireScript, StoryStub]] = field(default_factory=list)
    assembly: Optional[Assembly] = None
    error: str = ""
    fetch_notes: list[str] = field(default_factory=list)

    @property
    def stub(self) -> StoryStub:
        return self.group.stub

    @property
    def grade(self) -> Grade:
        return self.group.lead


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
    prod: Optional[Producer] = None,
) -> str:
    config = config or ShowConfig()

    stubs = collect_stubs(driver, count)
    if not stubs:
        raise SystemExit("no stories collected — is the listing empty or the session out?")

    grades, grade_note = graded(stubs, prod)
    if grade_note:
        log("grade", grade_note)
    groups = group_related(grades)
    merged = sum(len(g.related) for g in groups)
    log("grade", "ranked and grouped", stories=len(groups), merged_rows=merged,
        top=f"{groups[0].total:.2f}")

    culled = cull(groups, keep=keep, config=config)
    log("cull", "kept", kept=len(culled.kept), dropped=len(culled.dropped))

    # The listing order is what the row indices refer to.
    order = {id(s): i for i, s in enumerate(stubs)}
    collected: list[Collected] = []

    for position, group in enumerate(culled.kept, start=1):
        log("expand", f"{position}/{len(culled.kept)}", story=group.slug[:44],
            rows=len(group.members))
        item = Collected(group=group)

        # Every row of the story is fetched, not just the lead: each carries a
        # different soundbite, and its own source for the editor.
        for member in group.members:
            stub = member.stub
            wire, error = fetch_script(driver, stub, order.get(id(stub), 0))
            if wire is None:
                item.fetch_notes.append(
                    f"{stub.story_number or stub.slug[:30]}: {error}"
                )
            elif item.wire is None:
                item.wire = wire
            else:
                item.extra_bites.append((wire, stub))
            time.sleep(0.8)

        if item.wire is None:
            item.error = "no script on any row of this story"
        else:
            try:
                item.assembly = assemble_story(
                    item.wire, group.stub, extra_bites=item.extra_bites, config=config
                )
            except Exception as exc:
                item.error = f"assembly failed: {type(exc).__name__}: {exc}"
        collected.append(item)

    overrides, place_note = placed(culled.kept, prod)
    if place_note:
        log("slot", place_note)

    return write_report(
        collected, culled, stubs, out_path, config,
        overrides=overrides, prod=prod,
        notes=[n for n in (grade_note, place_note) if n],
    )


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
    overrides: dict | None = None,
    prod: Optional[Producer] = None,
    notes: list[str] | None = None,
) -> str:
    built = [c for c in collected if c.assembly]
    placements = place_pool(culled.kept, overrides)
    fill = fill_holes(placements, demo_holes(DEMO_HOLE_SECONDS, config), config)
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
    if prod is not None:
        add(f"grading and slotting ran on {prod.budget.model} (§11.12)")
        add(f"cost        {prod.budget.report()}")
        for note in prod.budget.notes:
            add(f"            ! {note}")
    else:
        add("No model ran. Grading is newscast.scoring and slotting is")
        add("newscast.slotting — deterministic stand-ins for the calls §11.12")
        add("describes, which is why they exist rather than scaffolding.")
    for note in notes or []:
        add(f"            ! {note}")
    add("")
    add("Copy is not rewritten either way: the wire's words go through as")
    add("written, with an editor note wherever a human has to look.")
    add("")

    add(_rule())
    add("RANKING")
    add(_rule())
    for position, group in enumerate(culled.kept, start=1):
        add(f"{position:>3}. {group.total:6.2f}  {group.slug[:60]}")
        add(f"       {group.lead.explain()[8:]}")
        for note in group.lead.notes:
            add(f"       - {note}")
        for related in group.related:
            add(f"       + merged: {related.slug[:56]}")
            add(f"                 {related.stub.story_number or '(no story number)'}")
    add("")

    add(_rule())
    add("CULLED")
    add(_rule())
    for group, reason in culled.dropped:
        add(f"  {group.total:6.2f}  {group.slug[:52]}")
        add(f"          {reason}")
    add("")

    add(_rule())
    add("SLOTTING (§6 phase 2, §11.27)")
    add(_rule())
    add("")
    add("Placement is tonal, not tabular: there is no rule that says a shooting")
    add("goes in B. Every surviving story gets a primary block, a backup block —")
    add("so a story that loses its slot has somewhere to go — and a heaviness")
    add("weight from 0 to 1. Within a block, heavier runs first, which is §2's")
    add('"heavy to light" made numeric.')
    add("")
    add(f"The holes are assumed at {DEMO_HOLE_SECONDS:.0f}s a block. The real ones are the")
    add("rundown's budget minus what the human producer already placed, and")
    add("neither number exists yet (§11.20, and no Inception adapter).")
    add("")
    for placement in placements:
        add(f"  {placement.explain()[:74]}")
        for reason in placement.reasons:
            add(f"      - {reason}")
    add("")
    add("  --- the show these would make ---")
    for block in config.blocks:
        ordered = fill.order(block.name)
        used = fill.used_seconds.get(block.name, 0.0)
        add(f"  {block.name}  {used:5.0f}s  {block.purpose}")
        for position, placement in enumerate(ordered, start=1):
            add(f"       {position}. [{placement.heaviness:.2f}] "
                f"{placement.slug[:52]}")
        if not ordered:
            add("       (nothing slotted here)")
    if fill.unplaced:
        add("")
        add("  --- fit nowhere ---")
        for placement, why in fill.unplaced:
            add(f"  {placement.slug[:50]}")
            add(f"      {why}")
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
        if item.group.related:
            add(f"merged rows  : {len(item.group.members)} rows of this story")
            for member in item.group.related:
                add(f"               {member.stub.story_number or '(no number)':<10} "
                    f"{member.slug[:48]}")
        add(f"wire duration: {item.stub.wire_duration_seconds or '(none)'}  "
            "<- a sort key, never a TRT (§11.23)")
        if item.stub.embargo:
            add(f"EMBARGO      : {item.stub.embargo}")

        for note in item.fetch_notes:
            add(f"  fetch note   : {note}")

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
        if assembly.sources:
            add("  --- sources the editor pulls from ---")
            for source in assembly.sources:
                add(f"  {source}")
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
    html_paths: list[str],
    keep: int,
    out_path: str,
    config: ShowConfig | None = None,
    prod: Optional[Producer] = None,
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

    grades, grade_note = graded(unique, prod)
    if grade_note:
        log("grade", grade_note)
    groups = group_related(grades)
    merged = sum(len(g.related) for g in groups)
    log("grade", "ranked and grouped", stories=len(groups), merged_rows=merged)

    culled = cull(groups, keep=keep, config=config)
    log("cull", "kept", kept=len(culled.kept), dropped=len(culled.dropped))

    collected: list[Collected] = []
    for group in culled.kept:
        item = Collected(group=group)
        for member in group.members:
            wire = scripts.get(member.stub.story_number or "")
            if wire is None:
                item.fetch_notes.append(
                    f"{member.stub.story_number or member.slug[:30]}: "
                    "not expanded in the captures"
                )
            elif item.wire is None:
                item.wire = wire
            else:
                item.extra_bites.append((wire, member.stub))

        if item.wire is None:
            item.error = "no script in the captures — no row of this story was expanded"
        else:
            try:
                item.assembly = assemble_story(
                    item.wire, group.stub, extra_bites=item.extra_bites, config=config
                )
            except Exception as exc:
                item.error = f"assembly failed: {type(exc).__name__}: {exc}"
        collected.append(item)

    overrides, place_note = placed(culled.kept, prod)
    if place_note:
        log("slot", place_note)

    return write_report(
        collected, culled, unique, out_path, config,
        overrides=overrides, prod=prod,
        notes=[n for n in (grade_note, place_note) if n],
    )


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
    parser.add_argument(
        "--model",
        default=DEV_MODEL,
        help=f"grading and slotting model (§11.12; default {DEV_MODEL})",
    )
    parser.add_argument(
        "--ceiling",
        type=float,
        default=2.00,
        help="hard cost ceiling for the run in dollars (§11.12; default 2.00)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="use the deterministic grader and slotter, and spend nothing",
    )
    args = parser.parse_args(argv)

    values, env_path = load_env(args.env_file)

    prod = None
    if not args.no_llm:
        prod, why = make_producer(values, model=args.model, ceiling=args.ceiling)
        log("model", f"{args.model}, ceiling ${args.ceiling:.2f}" if prod
            else f"not used — {why}")

    if args.from_html:
        out_path = args.out or "collection-run.txt"
        run_offline(args.from_html, args.keep, out_path, prod=prod)
        print(f"\nwrote {os.path.abspath(out_path)}\n")
        return 0

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

    run(driver, args.count, args.keep, out_path, prod=prod)
    print(f"\nwrote {os.path.abspath(out_path)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
