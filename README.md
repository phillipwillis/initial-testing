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

```bash
python3 -m newscast.capture doctor            # what can this machine actually do?
python3 -m newscast.capture page --out cnn.html   # save the rendered DOM of the current tab
```

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
