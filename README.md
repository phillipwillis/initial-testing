# Newscast Producer Agent

Automates production of the noon newscast at KIFI / Local News 8 (Idaho Falls, ID).
The project spec — show architecture, segment types, script markup, and the rules that
must hold on air — is in [CLAUDE.md](CLAUDE.md), and it is the source of truth.

## Status

Milestone 1 of the §10 build order is done: the domain model, the §4 markup parser and
serializer, the read-time estimator, and the §5 rule engine. **No LLM, no network.**
Collection, grading, slotting, script generation, and the Inception adapter are still ahead.

Read [CLAUDE.md §13](CLAUDE.md#13-implementation-notes-milestone-1) before extending any of
this — it lists the markup this build invented, the constants it had to guess at, and the
questions the guessing raised.

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

Answers to the open questions in §11 can be tried without touching code:

```bash
python3 -m newscast validate rundown.txt \
    --budget 1A=420 --anchors 1A=MEGAN,JAY --shot 1A=CAM1 --cg-ceiling 38 --wpm 165
```

Rules that depend on an unanswered question report `INFO ... not configured` rather than
enforcing an invented threshold.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

113 tests, no dependencies beyond the standard library. The parser round-trips all five §3
examples byte for byte; `show_clean.txt` must stay silent and `show_broken.txt` must keep
breaking every rule exactly once. Per §10, the validator is the eval harness for everything
downstream, so it is the thing to keep honest.
