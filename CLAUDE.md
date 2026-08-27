# Newscast Producer Agent

Automates production of the noon newscast at KIFI / Local News 8 (Idaho Falls, ID) — story
collection, ranking, slotting, script writing, and entry into the Inception CMS.

**Status:** milestone 1 of §10 is built — the domain model, the §4 markup parser/serializer,
the read-time estimator, and the §5 rule engine. No LLM and no network are involved yet.
Everything from §6 phase 0 onward (collection, grading, slotting, Inception) is still the
target, not the implementation. See §13 for what was decided provisionally while building,
and §11.13–§11.19 for the questions building it raised.

---

## 0. Read this first

This is a domain-heavy project. The hard part is not the LLM calls — it's encoding the
architecture of producer decision-making, then enforcing it mechanically. Most bugs will be
rule violations that read fine as prose but break on air.

Two operating principles:

1. **"What's in it for the viewer?"** is the single dominant ranking criterion. A local road
   closure beats an Indonesian chemical plant explosion, every time, because it changes what
   the viewer does today.
2. **Bigger elements decompose into smaller ones.** A PKG is not atomic. If you have 40
   seconds left and the best remaining story is a 2:00 PKG, rewrite it as a VO and leave an
   editor note to cut the PKG into B-roll. This flexibility is what makes the fill algorithm
   tractable.

Before writing code, work through **§11 Open Questions** with Phil. Several of them block
real design decisions (block time budgets, wire access method, Inception access method).

---

## 1. Glossary

| Term | Meaning |
|---|---|
| **Show** | One newscast. Split into two half hours. |
| **Block** | A run of stories between breaks. Labeled A/B/C/D within each half hour. |
| **Story** | One item in the rundown. Composed of one or more segments. |
| **Segment** | A unit of a story with a single production mode (RDR, VO, SOT, PKG). |
| **Slug** | Short headline identifier for a story. |
| **CG** | Computer graphic; here, almost always the lower third. |
| **Monitor** | The over-shoulder graphic/video behind the anchor. |
| **D channel** | Playback channel that holds a video file for a story. Overwritten on load. |
| **Bump / tease** | End-of-block line teasing a story later in the show. |
| **Wire** | Syndicated feed source (ABC, CNN, etc.). |
| **Inception** | The newsroom CMS where scripts, CGs, and the rundown live. |
| **Tag (of a story)** | The anchor's closing on-camera line after video ends. |

---

## 2. Show architecture

The show is two half hours, each with four blocks. Purpose per block:

| Half | Block | Purpose | Notes |
|---|---|---|---|
| 1 | A | Local lead. Top regional/national sprinkled in. | Heaviest content of the show. |
| 1 | B | National quick hits. | War updates, Trump, striking international items. Short items. |
| 1 | C | Trending / talkers. Uplifting. | Leads into weather. |
| 1 | D | Local overflow; default is fun local. | Ribbon cuttings, new coach hired, etc. |
| 2 | A | Local. | |
| 2 | B | National quick hits. | |
| 2 | C | Flex. Interesting national, or local overflow. | Used to fill time. |
| 2 | D | Entertainment, then optional talker to close the show. | Movie releases, awards, big auctions. |

### Block-level rules

- **Heavy to light.** Lead with the hardest news, close with the lightest. If it bleeds, it leads.
- **Every block ends with a bump** teasing a story later in the show.
- **Camera shot is constant within a block.** Each block has an assigned default shot, broken
  only in special circumstances (which must be flagged, not silent).
- **PKG budget: max 2 per block.** Zero is acceptable.

### Anchor pattern

Two anchors open the A block. One breaks off for weather; the remaining anchor carries solo
until the C block, where dual reads resume. This is one of several per-block nuances — the
system needs a rule engine that checks anchor assignment against the block pattern, not a
prompt instruction hoping the model remembers.

> **Unresolved:** the second half hour's anchor and weather pattern is not yet specified. See §11.

---

## 3. Segment types

Every segment should generally carry a monitor **and** a lower-third CG. Exceptions exist and
must be explicit.

### RDR — Reader
Anchor reads on camera in front of the monitor, lower third below. Simple.
**Use sparingly:** only for stories under ~15 seconds where no other visual aid is possible.

```
[CAM1 OX1]
[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]
[MEGAN]
JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY. VENDORS CLOSE UP SHOP AT TWO THIS AFTERNOON.
GET OUT THERE FAST IF YOU WANTED TO GET SOME FRESH PRODUCE.
[#####]
```

### VO — Voice Over
The bread and butter. Anchor reads over video. May open and/or close on camera like an RDR,
or sit under video the whole way. **Typical length 20–45 seconds.**

```
[CAM1 OX1]
[MEGAN]
JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.
[VO]
[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]
VENDORS CLOSE UP SHOP AT 2 THIS AFTERNOON.
THEY MADE THE DECISION DUE TO THE WILD WEATHER WE'RE GOING TO BE GETTING AROUND THREE, AND THEY WANTED TO BE SURE THERE WAS TIME TO CLOSE UP PROPERLY.
[ON CAM]
GET OUT THERE FAST IF YOU WANTED TO GET SOME FRESH PRODUCE.
[#####]
```

### SOT — Sound on Tape
Audio/video clip that plays on its own. **The anchor's mic is off during the soundbite.**
Must be introduced by an RDR or VO. Because it uses a video file, the monitor goes into the
D channel — note `- D` on the camera cue and `BACK TO D` on the return.

```
[CAM1 OX1 - D]
[MEGAN]
JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.
[VO]
[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]
VENDORS CLOSE UP SHOP AT 2 THIS AFTERNOON.
THEY MADE THE DECISION DUE TO THE WILD WEATHER WE'RE GOING TO BE GETTING AROUND THREE, AND THEY WANTED TO BE SURE THERE WAS TIME TO CLOSE UP PROPERLY.
~~~New Segment~~~
[SOT 0:13]
[CG: DEBRA JONES, FARMER'S MARKET VENDOR]
"I know we're closing up early, but I'm just glad I was able to sell my cheeses for even a few hours today!"
[ON CAM - BACK TO D]
[MEGAN]
GET OUT THERE FAST IF YOU STILL WANTED TO GET SOME FRESH PRODUCE.
[#####]
```

### SOTVO — Sound on Tape + Voice Over
A SOT with extra video after it that the anchor talks over, without returning to camera.
May return to camera afterward for more lines — if so, maintain the monitor.

```
[CAM1 OX1]
[MEGAN]
JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.
[VO]
[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]
VENDORS CLOSE UP SHOP AT 2 THIS AFTERNOON.
THEY MADE THE DECISION DUE TO THE WILD WEATHER WE'RE GOING TO BE GETTING AROUND THREE, AND THEY WANTED TO BE SURE THERE WAS TIME TO CLOSE UP PROPERLY.
~~~New Segment~~~
[SOT 0:13]
[CG: DEBRA JONES, FARMER'S MARKET VENDOR]
"I know we're closing up early, but I'm just glad I was able to sell my cheeses for even a few hours today!"
[CONT VO]
[MEGAN]
GET OUT THERE FAST IF YOU STILL WANTED TO GET SOME OF MRS. JONES'S AMAZING CHEESE.
SHE'S JUST ONE OF MANY VENDORS WHO ARE GLAD THE FARMERS MARKET RAN AT ALL TODAY.
[#####]
```

> Note: no `- D` on the camera cue here, because the story never returns to camera.

### PKG — Package
Large prebuilt video/audio ensemble from a reporter or the wires. Mechanically it behaves as
one very large SOT (single video file). Fills time and gives anchors a break.

- **Always** has an RDR intro. **Most** have an outro.
- Lengths: 1:00 short, 2:00 normal. 3:00 needs to be stellar — that's near the ceiling for
  time with anchors off camera.
- Max 2 per block.

```
[CAM1 OX1]
[MEGAN]
IF YOU DIDN'T KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.
DANIELLE MULLENIX GIVES US AN INSIDE LOOK AS TO WHY.
[PKG 1:25]
[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]
-sounds of bustling-
THE IDAHO FALLS FARMERS MARKET IS A BELOVED TRADITION OF THE CITY - BUT TODAY...
-slamming of a car trunk-
... IT CLOSES EARLY.
AT TWO O'CLOCK THIS AFTERNOON, THIS STREET WILL BE EMPTY, AND ALL THESE TENTS WILL BE PACKED UP.
[CG: MANDY GAITHER, FARMER'S MARKET CUSTOMER]
"It's one of my favorite things, to come out and enjoy the food trucks, and to watch people walk their dogs. I don't get to do much in my old age, so it's something I look forward to, coming out here. It's a shame that today they're closing up early."
THEY MADE THE DECISION DUE TO THE WILD WEATHER WE'RE GOING TO BE GETTING AROUND THREE THIS AFTERNOON, WITH WINDS REACHING UP TO TWENTY SEVEN MILES AN HOUR.
ORGANIZERS WANTED TO BE SURE THERE WAS TIME TO CLOSE UP PROPERLY.
[CG: DEBRA JONES, FARMER'S MARKET VENDOR]
"I know we're closing up early, but I'm just glad I was able to sell my cheeses for even a few hours today!"
[ON CAM]
[MEGAN]
WHILE THE FARMER'S MARKET WILL BE CLOSING SOON, THERE'S STILL SOME TIME TO GET SOME GREAT DEALS.
DON'T FORGET TO MENTION THAT YOU WATCH LOCAL NEWS 8 AT THE POPCORN KETTLE STAND TO GET SOME FREE SAMPLE BAGS.
[#####]
```

### Composite forms
Segments chain: **VOSOT, SOTVO, VOSOTVO, VOSOTVOSOT**. The last is roughly the largest form
justifiable for a single story. Composites are the main tool for fitting a strong story into
an awkward time hole.

---

## 4. Script markup reference

| Cue | Meaning |
|---|---|
| `[CAM1 OX1]` | Camera and over-shoulder monitor assignment. |
| `[CAM1 OX1 - D]` | Same, but park the monitor in the D channel (needed when a video file follows). |
| `[ON CAM]` | Return to anchor on camera. |
| `[ON CAM - BACK TO D]` | Return to camera and restore the monitor stored in D. |
| `[MEGAN]` | Anchor assignment for the lines that follow. |
| `[CG: ...]` | Lower third text. |
| `[VO]` | Start of voice-over-video. |
| `[CONT VO]` | Voice over continues on new video after a SOT, without returning to camera. |
| `[SOT 0:13]` | Soundbite with duration. Anchor mic off. |
| `[PKG 1:25]` | Package with duration. |
| `~~~New Segment~~~` | Segment boundary within a story. |
| `[#####]` | End of story. |

Anchor copy is written in **ALL CAPS**. Soundbite and package interview transcription is
written in mixed case inside quotes. Natural sound is written as `-sounds of bustling-`.

---

## 5. Hard rules the validator must enforce

These are the checks that make the difference between a script and an on-air incident. The
rule engine runs against the assembled rundown, not against individual model outputs.

**Playback / technical**

- `R1` **Two D-channel stories may not run back to back.** If they must, the second requires a
  monitor video placeholder at the start *and* a duplicate monitor file at the end of its SOT
  (or wherever it returns to camera). Without this, loading the second story overwrites the
  first story's monitor mid-tag and the monitor insta-swaps on air.
- `R2` A SOT or SOTVO that returns to camera must carry `- D` on its opening camera cue and
  `BACK TO D` on the return.
- `R3` Every story terminates with `[#####]`.

**Editorial / format**

- `R4` Every segment has a CG unless explicitly exempted.
- `R5` CGs are short. Slug-length headlines fail. *"The Idaho Falls Farmers Market is closing
  down early because of the wind, and people are not happy about it"* is far too long;
  *"I.F. FARMER'S MARKET CLOSES AT 2:00 PM"* is right. Enforce a character ceiling (§11.9).
- `R6` RDR only if the story is under ~15 seconds and no visual aid is possible.
- `R7` VO runs 20–45 seconds.
- `R8` Every PKG has an intro. Flag any PKG without an outro for human review.
- `R9` Max 2 PKGs per block.
- `R10` Every block ends with a bump/tease.
- `R11` Camera shot is constant within a block unless an exception is explicitly flagged.
- `R12` Anchor assignment matches the block's anchor pattern.
- `R13` **Daypart language.** This is the noon show. Wire copy frequently opens with "this
  morning" or "tonight." Detect and either rewrite or mark for trim, with an editor note.
- `R14` Block runtime is within budget ± tolerance.

**Traceability**

- `R15` Every SOT and PKG segment carries its source reference and an editor note stating
  exactly what needs to be done (clip, trim, pull B-roll, etc.).

---

## 6. Pipeline

### Phase 0 — Collection *(runs while the human producer works email)*
Pull all fresh stories from the past day off the wires. Expect roughly 200. Capture **stubs
only** — do not pull full scripts yet:

```
{ id, slug, source, content_type, timestamp, tags[], related_ids[] }
```

Meanwhile the human producer is going through email, pulling local stories forward from
earlier shows and adapting them, and putting them into the show. The agent must read the
rundown to see what the human has already placed.

### Phase 1 — Bulk grading
Grade all stubs **relative to one another** in a batch, not independently. See §7.

### Phase 2 — Slotting
Fill each block's available time from the ranked pool, respecting block purpose. Section fit
is a **constraint, not just a score component** — if no entertainment story ranks highly, the
final block still needs entertainment, so take the highest-scored entertainment-eligible
story regardless of its absolute rank.

Local stories placed by the human are fixed points; the agent fills around them.

### Phase 3 — Deep research *(per selected story)*
Now go get everything: full text, tags, keyword searches, and stories the wire marks as
connected. A VO source is frequently linked to a SOT the collection pass never saw. Compile
all sources, soundbites, and video for the topic.

### Phase 4 — Story assembly
Choose the story type from what the research turned up and what time remains, then write the
script with all cues, CGs, sources, and editor notes. Decompose or compose as needed to fit
the hole (§3 composites).

### Phase 5 — Write to Inception, validate, iterate
Write the story, mark **story submitted**, run the validator on the whole show, and revise.
Loop until every story is marked **accepted** by the overseeing producer, or a stop flag is set.

`submitted` means the agent wrote it and may still replace it if something better arrives.
`accepted` means the human locked it in — treat as immutable.

---

## 7. Scoring model

Starting proposal. Weights need tuning against real rundowns.

| Field | What it measures |
|---|---|
| `viewer_impact` | Does this change what the viewer does today? Dominant term. Local weights hardest. |
| `magnitude` | How significant is the event in absolute terms. |
| `visual_strength` | Does the slug and content type imply striking video? |
| `audio_available` | Is there a usable soundbite? |
| `corroboration` | Count of the same story across wires, plus count of related entries. Heuristic for importance. |
| `section_fit` | Which blocks this story is eligible for. Also used as a slotting constraint. |
| `freshness` | New today vs. an update to something already aired. |

Grading is comparative and batched — the model sees the pool and ranks within it. Do not
score stories in isolation and sort afterward.

---

## 8. Tools to build

The agent is only as good as its tools. Build these as discrete, individually testable units.

**Wire access**
- `wire_collect(sources, since)` → story stubs
- `wire_search(query | tags | keywords)` → stubs
- `wire_expand(story_id)` → full script, media refs, related items, soundbites

**Media**
- `sot_timestamps(media_ref, speaker)` → in/out points for a person starting and finishing a
  section of speech. Output goes into the editor note alongside the source package reference,
  so the editor can find and pull the clip fast.

**Scripting**
- `assemble_story(research, target_type, target_duration)` → script with cues
- `decompose(pkg, target_form, target_duration)` → e.g. PKG → VO + B-roll editor note
- `estimate_read_time(copy)` → seconds (needed for every duration rule)

**Show construction**
- `rundown_read()` → current show state including human-placed local stories
- `slot_story(block, position, story)`
- `validate_show(rundown)` → rule violations from §5

**Inception**
- `story_write(...)`, `cg_write(...)`, `note_write(...)`
- `mark_submitted(story_id)`, `check_accepted(story_id)`
- `lock_acquire(story_id)` / `lock_release(story_id)`

---

## 9. Inception integration

Inception is the newsroom CMS. It is the hardest and least forgiving part of this project.

**Known failure modes from prior attempts:**

1. **Navigation is fragile**, and the CG system in particular has been the main source of
   breakage. Build the CG path first and test it hardest.
2. **Content locking.** When any user or agent opens a story, that story is locked to everyone
   else until the lock is released. The agent must never block on a lock. Required behavior:
   - Attempt acquire.
   - On failure, move to another task in the queue.
   - Re-check the locked story periodically with backoff.
   - Never hold a lock across a long model call — acquire late, release immediately.

**Design guidance:** put every Inception interaction behind a thin adapter interface. The
scripting and validation layers should never know how Inception is being driven. If the
access method changes, one module changes.

---

## 10. Suggested build order

Each milestone should be independently demonstrable.

1. **Domain model + validator.** Data classes for show/block/story/segment, the §5 rule
   engine, and a parser/serializer for the §4 markup. Test against hand-written scripts,
   including deliberately broken ones. *No LLM, no network — this is the foundation.*
2. **Read-time estimator.** Every duration rule depends on it.
3. **Wire collection + stub store.** Get the ~200 stubs reliably. No grading yet.
4. **Batch grader.** Run against a real day's stubs. Compare the ranking to what Phil
   actually produced that day — that comparison is the eval.
5. **Single-story script generation.** One story, from stub → research → script → validated.
6. **Inception adapter.** Read the rundown first. Then write one story. Then CGs. Then
   submit/accept and locking.
7. **Slotting and fill.** Whole-show assembly with the time budget.
8. **Full loop** with submit/accept polling and the stop flag.

**Testing note:** the validator is the eval harness for everything downstream. Every generated
script gets run through it, and a violation rate is the primary quality metric.

---

## 11. Open questions

Blocking or near-blocking. Resolve with Phil before the relevant milestone.

Items 1, 2, 3 and 9 are now *parameters* rather than guesses: the rule engine reads them from
`ShowConfig`, and the rules that depend on them report "not configured" instead of enforcing
an invented threshold. Answering one is a one-line edit in `newscast/config.py`.

1. **Block time budgets.** How many seconds does each block hold? This drives the entire fill
   algorithm and nothing above can be finalized without it.
2. **Anchor roster.** Who are the anchors, who does weather, and what is the second half hour's
   anchor/weather pattern? Where exactly does the weather break-off fall relative to A and B?
3. **Default camera shot per block.** `CAM1 OX1` is the only shot in the spec. What are the
   others, and what counts as a "special circumstance" for breaking one?
4. **Wire access.** ABC and CNN — API, feed, or screen scraping? What auth, and what format do
   items come back in? Are related-story links exposed programmatically?
5. **Inception access.** Is there an API, or is browser automation the only option? What auth?
6. **Human handoff.** How does the agent learn which local stories the producer already
   placed — read the rundown directly, or a separate handoff?
7. **SOT timestamps.** Where do in/out points come from? Existing transcript or caption track,
   or does this need ASR on the media?
8. **CG writing.** Does the agent write CGs into Inception's CG system directly, or write them
   into the script and leave the CG build to a human?
9. **CG character ceiling.** What's the actual on-air limit for a lower third?
10. **Sports.** The spec doesn't mention sports. Does the noon show carry a sports block?
11. **Bumps/teases.** Separate rundown elements, or appended to the last story of a block?
12. **Model + budget.** Which model runs the grading pass vs. the writing pass, and what's the
    per-show cost ceiling? 200 stubs graded plus deep research on ~20 selected stories is the
    load to plan around.

---

## 12. Working agreements

- **Don't guess at domain rules.** If a producing convention isn't in this file, ask. Wrong
  guesses here are expensive and only surface on air.
- **Rules go in the validator, not in prompts.** Anything checkable should be checked in code.
  Prompt instructions are a fallback, not an enforcement mechanism.
- **Update this file** when a decision gets made — especially answers to §11.
- **Never modify a story marked accepted.**

---

## 13. Implementation notes (milestone 1)

Written by the build, not by Phil. Everything here is provisional and is either a decision to
confirm or a question to answer. Nothing in this section is a producing convention — §1–§9
remain the source of truth.

### 13.1 What exists

| Module | Purpose |
|---|---|
| `newscast/model.py` | Show / block / story / segment / element data classes (§1–§3). |
| `newscast/markup.py` | Parser and serializer for the §4 markup. Round-trips all five §3 examples byte for byte. |
| `newscast/readtime.py` | `estimate_read_time()` (§8, §10.2). |
| `newscast/timing.py` | Story and block durations, with in-package copy excluded. |
| `newscast/config.py` | Every §11 threshold, in one place. |
| `newscast/rules.py` | R1–R15 plus X1–X5, one function per rule. |
| `newscast/validator.py` | `validate_show()` (§8) and the violation-rate metric (§10). |
| `newscast/cli.py` | `validate`, `summary`, `rules`, `readtime`. |

`tests/fixtures/show_clean.txt` passes every enforceable rule; `show_broken.txt` breaks each
one exactly once, and the test suite asserts that. 113 tests, `python3 -m unittest discover`.

### 13.2 Markup extensions

§4 has no way to express several things §5 requires, so the parser accepts these additional
cues. They are inventions and can be renamed or replaced freely:

| Cue | Exists because |
|---|---|
| `[SOURCE: ...]` | R15 — the source reference on a SOT/PKG segment. |
| `[NOTE: ...]` | R15 — the editor note saying what to clip, trim, or pull. |
| `[NO CG: reason]` | R4 — "unless explicitly exempted" needs a way to be explicit. |
| `[SHOT EXCEPTION: reason]` | R11 — "must be flagged, not silent" needs the flag. |
| `[MONITOR PLACEHOLDER]` / `[MONITOR DUPE]` | R1 — the two mitigations §5 R1 describes in prose. |
| `[TEASE: ...]` | R10 — a bump has to be identifiable either way §11.11 lands. |
| `[MEGAN/JAY]` | A dual read, for R12. |

The rundown file format (`=== HALF 1 BLOCK A ===`, `--- STORY: SLUG ---`) is a local
interchange format for fixtures and tests. It is not an Inception format.

### 13.3 Judgement calls, all reversible

1. **R2 exempts packages.** §3's PKG example returns to camera on a plain `[CAM1 OX1]`, with
   no `- D`, so R2 is applied only to segments containing a SOT. If the example is the thing
   that is wrong, this flips in one line. See §11.14.
2. **R1 does not exempt packages.** A PKG is a video file in D, so two PKG stories back to
   back trip R1 the same as two SOTs. See §11.13.
3. **R7 is enforced on whole VO stories only.** Inside a composite, a short VO leg is normal
   because the story continues; an over-long leg is a warning, not an error.
4. **R4 is checked per segment**, which means a bare tag segment needs `[NO CG: ...]`.
5. **R6 checks the duration half of the rule only.** "No visual aid is possible" is not
   checkable from the script. See §11.18.
6. **Segment mode is derived, not declared** — from the cues present, so a mislabeled story
   cannot lie to the validator.
7. **Copy inside a `[PKG]` is not counted as read time**, because it is already inside the
   package's declared duration. Copy after `[CONT VO]` is counted, because the anchor is live
   again.

### 13.4 Provisional constants

All in `newscast/config.py`; every one of them is a guess until Phil says otherwise, and each
is reported as PROVISIONAL when it fires.

| Constant | Value | Basis |
|---|---|---|
| `words_per_minute` | 160 | Ordinary broadcast read rate. At this rate the §3 reader example runs 12.2s (R6 wants < 15) and the §3 VO example runs 23.1s (R7 wants 20–45), which is the only evidence available. |
| `cg_char_ceiling_provisional` | 45 | The §5 R5 good example is 38 characters; the bad one is 94. |
| `pkg_ceiling_seconds` | 180 | §3, "3:00 needs to be stellar". |
| `block_budget_tolerance_seconds` | 10 | Invented. |

### 13.5 New questions for §11

13. **R1 and packages.** Do two PKG stories back to back need the same monitor mitigation as
    two SOT stories, or does the PKG's own return to camera handle it?
14. **The §3 PKG example and R2.** Should `[CAM1 OX1]` in that example be `[CAM1 OX1 - D]`?
    R2's scope depends on the answer.
15. **Do bumps carry a CG?** Every tease in the clean fixture currently declares
    `[NO CG: bump]` to satisfy R4.
16. **Is R7 hard or soft?** A 47-second VO is currently an error. If it is really a
    guideline, it should be a warning.
17. **What is "the shot" for R11** — the camera alone (`CAM1`), or camera plus over-shoulder
    (`CAM1 OX1`)? The engine currently compares cameras only, so `OX1` → `OX2` inside a block
    passes.
18. **Should an RDR have to justify itself?** R6's "no visual aid is possible" clause is
    unenforceable without a required note on the story.
19. **Read-rate calibration.** Roughly ten real scripts with their actual back-times would
    replace the 160 wpm guess with a measured number, and every duration rule depends on it.
