# Newscast Producer Agent

Automates production of the noon newscast at KIFI / Local News 8 (Idaho Falls, ID).
The project spec — show architecture, segment types, script markup, and the rules that
must hold on air — is in [CLAUDE.md](CLAUDE.md), and it is the source of truth.

## Status

Milestone 1 of the §10 build order is done: the domain model, the §4 markup parser and
serializer, the read-time estimator, and the §5 rule engine. **No LLM, no network.**
Collection, grading, slotting, script generation, and the Inception adapter are still ahead.

The §11 questions were answered on 2026-08-27, so the engine enforces the real anchor pattern,
studio shots, 39-character CG ceiling and monitor rule rather than placeholders. Three items
remain open — see [§11.20](CLAUDE.md#1120-still-outstanding) — and none of them block the next
milestone. [§13](CLAUDE.md#13-implementation-notes-milestone-1) covers the markup this build
invented and what it still assumes.

## Layout

```
newscast/
  model.py      show / block / story / segment / element
  markup.py     parse and serialize the §4 script markup
  readtime.py   estimate_read_time() -- every duration rule depends on it
  timing.py     story and block durations
  config.py     every §11 threshold, in one place
  rules.py      R1-R15 plus X1-X5, one function per rule
  validator.py  validate_show() and the violation-rate metric
  cli.py        validate / summary / rules / readtime
tests/
  fixtures/     the five §3 examples, one clean rundown, one deliberately broken one
```

## Use it

```bash
python3 -m newscast rules                                   # what gets checked
python3 -m newscast validate tests/fixtures/show_broken.txt # the rule engine
python3 -m newscast summary  tests/fixtures/show_clean.txt  # rundown with timings
python3 -m newscast readtime --text "VENDORS CLOSE UP SHOP AT TWO."
```

`validate` exits non-zero when anything would break on air, so it drops straight into CI or a
pre-submit hook.

The §11 answers live in `newscast/config.py`. These flags override them for a what-if without
editing code:

```bash
python3 -m newscast validate rundown.txt --budget 1B=300 --cg-ceiling 42 --wpm 170
```

The rules that still depend on an unanswered question — the half-hour clock, the bump CG
ceiling — report `INFO ... not configured` rather than enforcing an invented threshold.

## On the work machine

The code and the credentials do not live in the same directory. Unzip the repo *inside* the
folder holding the `.env`:

```
monkey_king/
    .env                                  CNN_USER, CNN_PASS
    initial-testing-<branch>/             <- run commands from here
        newscast/
        probe-output/  → written to monkey_king/, not here
```

`python3 -m newscast...` only works from inside the unzipped folder, so that is where you run
it. The `.env` is found by walking up from the working directory, so it does not matter what
the unzipped folder is called or how deep it sits. Evidence is written beside the `.env`
rather than into the unzipped folder, which gets replaced every time a new build is
downloaded.

```bash
cd ~/Desktop/monkey_king/initial-testing-<branch>
python3 -m newscast.capture launch --url https://newsource.ns.cnn.com/
python3 -m newscast.probe
```


```bash
python3 -m newscast.capture launch                        # start Chrome with a debugging port
python3 -m newscast.capture doctor                        # what can this machine actually do?
python3 -m newscast.capture page --out cnn.html --tab newsource
python3 -m newscast.probe                                 # answer the open questions
python3 -m newscast.collect --count 50 --keep 8            # a full collection run
```

`collect` is the end-to-end run: it pulls stubs off the wire, grades them against each other,
culls to what a noon show can carry, fetches the script for each survivor, assembles §4
markup, validates it, and writes the lot — including the keystrokes the Inception writer
would type — to `collection-run.txt` beside the `.env`. **It writes nothing to Inception.**

The same pipeline runs with no browser over saved captures, which is how it is tested:

```bash
python3 -m newscast.collect --from-html page1.html page2.html --keep 6
```

`launch` starts Chrome detached on a separate profile and hands the terminal back. Log into
the wire in the window it opens — once, since the profile persists — then capture.

`doctor` reports Python, Selenium, Chrome and whether Chrome — specifically Chrome — is on
the debugging port. The default port is 9333 rather than the conventional 9222, because
Adobe's UXP tooling binds 9222 on any machine with Premiere or Photoshop installed; Chrome
then starts with no debugging port and does not mention it. `page`
attaches to a Chrome you have already logged into and saves what is on screen — it never logs
in and never takes a password. Saved HTML is scrubbed for emails, tokens and session ids
first; read it before sending it anywhere.

The wire sites are React apps, so Chrome's own "Save Page As" writes an empty `<div id="root">`.
Only the rendered DOM is useful — from this, or from DevTools → Elements → right-click
`<html>` → Copy → Copy outerHTML.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

191 tests, no dependencies beyond the standard library. The parser round-trips all five §3
examples byte for byte; `show_clean.txt` must stay silent and `show_broken.txt` must keep
breaking every rule. The monitor rule (§5 R2) is checked against all five §3 examples
directly, since those examples are what pinned it down. Per §10, the validator is the eval
harness for everything downstream, so it is the thing to keep honest.
