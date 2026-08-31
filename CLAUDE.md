# Newscast Producer Agent

Automates production of the noon newscast at KIFI / Local News 8 (Idaho Falls, ID) — story
collection, ranking, slotting, script writing, and entry into the Inception CMS.

**Status:** milestone 1 of §10 is built — the domain model, the §4 markup parser/serializer,
the read-time estimator, and the §5 rule engine. No LLM and no network are involved yet.
Everything from §6 phase 0 onward (collection, grading, slotting, Inception) is still the
target, not the implementation. The §11 questions were answered on 2026-08-27 and the rule
engine now enforces the real anchor pattern, shots, CG ceiling and monitor rule; §11.20 lists
the three items still outstanding.

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

**§11 is answered.** Anything not covered there is still a question for Phil — §12 stands:
don't guess at domain rules, and put the answer in this file when it arrives.

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
- **No sports.** The noon show does not carry a sports section.

### Anchor pattern

The anchors are **Jeff** and **Megan**; Jeff doubles as the weather man. The pattern is
identical in both half hours:

1. Jeff and Megan open the A block together with an introduction and hello.
2. Jeff breaks off for a first look at weather, then tosses to Megan.
3. Megan carries solo through the rest of A and all of B.
4. Jeff is back for the weather tease closing the B block.
5. The C block is double reads, and Jeff transitions into the main weather segment.
6. The D block is double reads.

This is one of several per-block nuances — the system needs a rule engine that checks anchor
assignment against the block pattern, not a prompt instruction hoping the model remembers.

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
- `R2` **Park the monitor in D when two video files play over it.** If two or more video files
  play between the monitor being on screen and the monitor coming back, the opening camera cue
  must carry `- D` and the return must carry `BACK TO D`. A VO, a SOT and a PKG are each one
  file. A package on its own is therefore usually fine, and a story that never returns to
  camera never needs D. (Corrected from "a SOT or SOTVO that returns to camera" — see §11.14.)
- `R3` Every story terminates with `[#####]`.

**Editorial / format**

- `R4` Every segment has a CG unless explicitly exempted.
- `R5` CGs are short. Slug-length headlines fail. *"The Idaho Falls Farmers Market is closing
  down early because of the wind, and people are not happy about it"* is far too long;
  *"I.F. FARMER'S MARKET CLOSES AT 2:00 PM"* is right. Enforce a character ceiling (§11.9).
- `R6` RDR only if the story is under ~15 seconds and no visual aid is possible. A reader must
  justify itself: the script carries an editor note saying why there is no video (§11.18).
- `R7` VO runs 20–45 seconds. This is a range, not a hard rule — out-of-range is a warning for
  a human to wave through, not an error (§11.16).
- `R8` Every PKG has an intro. Flag any PKG without an outro for human review.
- `R9` Max 2 PKGs per block.
- `R10` Every block ends with a bump/tease.
- `R11` Camera shot is constant within a block unless an exception is explicitly flagged. The
  shot is the camera **and** the over-shoulder: the same camera on a different monitor is
  pointing somewhere else, which is a different shot (§11.17). Two departures are structure
  rather than exceptions — the A blocks open on their own shot for the double read, and
  weather is at the weather wall.
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

**Answered 2026-08-27.** Everything below carries its answer. What is still outstanding is
collected in §11.20 — three items, none of which block the next milestone.

1. **Block time budgets.** ✅ The first half hour is **27:55**, the second is **32:00**. The A
   block runs roughly **5–7 minutes**. The C block in both half hours is back-timed to begin
   about **1:00 to 0:30 before the quarter hour**. Breaks and weather take specific amounts of
   time, and Inception already back-times the show, holds those allowances, and reports how
   far over or under the show is running. *Still needed: the break and weather numbers
   themselves — see §11.20.*
2. **Anchor roster.** ✅ **Jeff** and **Megan**; Jeff doubles as the weather man. Full pattern
   in §2, identical in both half hours.
3. **Default camera shot per block.** ✅ Three cameras in the studio; OX1–OX5 are different
   monitors, and the over-shoulder is part of the shot.

   | Block | Half 1 | Half 2 |
   |---|---|---|
   | A | CAM2 OX3 | CAM2 OX3 |
   | B | CAM3 OX5 | CAM1 OX1 |
   | C | CAM3 OX2 | CAM3 OX2 |
   | D | CAM3 OX2 | CAM3 OX2 |

   The A blocks open on a different shot for the double read: **CAM3 OX2** in the first half
   hour, **CAM1 OX4** in the second. Weather is done at the **WX GFX** shot, at the weather wall.
4. **Wire access.** ✅ Selenium driving a real browser — web scraping in its purest form.
   Links and authorizations exist. No published API, so related-story links have to be
   discovered by navigating the page like a person would. Collection notes for CNN Newsource
   are in `docs/wires/cnn-newsource.md`; note the open question there about the internal JSON
   API the site's own front end calls.
5. **Inception access.** ✅ Browser automation is the only way in. Previous attempts had
   moderate success; development starts fresh. The prior implementation's hard-won knowledge —
   the frame map, the SlickGrid column indices, the CKEditor shortcut expansion, the CG object
   path — is recorded in `docs/inception.md`, along with what not to carry forward.
6. **Human handoff.** ✅ The agent reads the rundown directly, keeps track of the stories it
   has added, and cross-checks that list against what is actually in the show. In practice a
   protocol already exists and works: the producer puts a **CNN story number in the Source
   column** and a **trigger code in Notes**; the agent acts on rows where both are filled and
   **clears Notes** when the story is written. See `docs/inception.md`.
7. **SOT timestamps.** ✅ A pipeline. Download the video, run speech to text, and mark
   timestamps per word or sentence. That transcript is the **authoritative verbatim** — wires
   sometimes ship old scripts against revamped packages. The agent picks a sentence or two
   spoken by an interviewee (never the reporter) and takes the in/out points from the
   transcript. **Delete the downloaded video once transcription is done** — the agent does no
   editing and only needs the transcript.
8. **CG writing.** ✅ The agent writes CGs **into Inception**, not into the script. The §3
   examples are how the agent passes information to the script-construction tools, which do
   different things depending on what the agent provides. Mechanically: CG placeholders are
   objects in the story editor, opened by double-click into their own editor frame
   (`docs/inception.md`). The wire's `--SUPERS--` block supplies name and title.
9. **CG character ceiling.** ✅ **39 characters.**
10. **Sports.** ✅ The noon show does not carry a sports section.
11. **Bumps/teases.** ✅ A bump is its own rundown element, typically a VO, an RDRVO, or an
    RDR. Special bumps — weather bumps, the birthday bump — are a human's job, not the agent's.
12. **Model + budget.** ✅ An Opus model for grading, for deciding the context-collection
    process, and for script writing. Expected per-show cost is **under $1** because tool use
    collapses many calls into one or two; the hard limit is **$2**.
13. **R1 and packages.** ✅ Packages typically do not need to be put in D by their nature —
    a PKG is a single video file, so it does not on its own trip the two-file rule.
14. **The §3 PKG example and R2.** ✅ The example is right and R2 was stated wrong. The real
    rule is the two-video-files rule now recorded as §5 R2. A monitor, a VO, another VO, and
    then back to the monitor needs D; a monitor, a package, and back does not.
15. **Do bumps carry a CG?** ✅ Yes — a bump CG, formatted differently from a normal lower
    third. Weather carries a CG too, but it is the weather anchor's prefilled name and title,
    so nobody writes one for it.
16. **Is R7 hard or soft?** ✅ A range. Most stories land inside it, some do not. Warning.
17. **What is "the shot" for R11?** ✅ Camera plus over-shoulder. Changing the OX changes where
    the camera is pointing, which is a different shot entirely.
18. **Should an RDR have to justify itself?** ✅ Yes.
19. **Read-rate calibration.** ✅ 160 wpm is a reasonable working number; tweak as the project
    continues.

### 11.20 Still outstanding

None of these block the next milestone.

20. **Break and weather durations.** §11.1 gives the half-hour totals and the A-block range,
    but per-block budgets for B, C and D fall out only once the break and weather allowances
    are known. Inception already holds these numbers. Until they arrive, R14 checks the A
    blocks and reports the half-hour reconciliation as unconfigured.
21. **Bump CG format.** §11.15 establishes that a bump CG is formatted differently from a
    lower third, but not how — so R5 skips bump CGs rather than measuring them against the
    39-character ceiling.
22. **Weather as a rundown element.** Weather occupies real time and appears in the rundown,
    but whether the agent ever writes or times one — or whether it is purely Inception's, like
    the birthday bump — is not settled. The rule engine already exempts `WEATHER` elements
    from the CG, shot, and reader rules.

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

Written by the build. §1–§9 remain the source of truth; this section records what the code
does and where it is still guessing.

### 13.1 What exists

| Module | Purpose |
|---|---|
| `newscast/model.py` | Show / block / story / segment / element data classes (§1–§3). |
| `newscast/markup.py` | Parser and serializer for the §4 markup. Round-trips all five §3 examples byte for byte. |
| `newscast/readtime.py` | `estimate_read_time()` (§8, §10.2). |
| `newscast/timing.py` | Story and block durations, with in-package copy excluded. |
| `newscast/config.py` | The §11 answers, in one place. |
| `newscast/rules.py` | R1–R15 plus X1–X5, one function per rule. |
| `newscast/validator.py` | `validate_show()` (§8) and the violation-rate metric (§10). |
| `newscast/cli.py` | `validate`, `summary`, `rules`, `readtime`. |

`tests/fixtures/show_clean.txt` passes every rule; `show_broken.txt` breaks each one, and the
test suite asserts that. 131 tests, `python3 -m unittest discover -s tests -t .`.

### 13.2 Markup extensions

§4 has no way to express several things §5 requires, so the parser accepts these additional
cues. They are inventions and can be renamed or replaced freely:

| Cue | Exists because |
|---|---|
| `[SOURCE: ...]` | R15 — the source reference on a SOT/PKG segment. |
| `[NOTE: ...]` | R15, and R6 — the editor note, which also carries a reader's justification. |
| `[NO CG: reason]` | R4 — "unless explicitly exempted" needs a way to be explicit. |
| `[SHOT EXCEPTION: reason]` | R11 — "must be flagged, not silent" needs the flag. |
| `[MONITOR PLACEHOLDER]` / `[MONITOR DUPE]` | R1 — the two mitigations §5 R1 describes in prose. |
| `[JEFF/MEGAN]` | A double read, for R12. |
| `[WX GFX]` | The weather wall shot, parsed like any other camera cue. |

The rundown file format (`=== HALF 1 BLOCK A ===`, `--- STORY: SLUG ---`, `--- BUMP: SLUG ---`)
is a local interchange format for fixtures and tests. It is not an Inception format.

### 13.3 How the monitor rule is implemented

§5 R2 is the one rule the original spec stated incorrectly, so it is worth spelling out. The
engine walks each story counting video files — a `[VO]`, a `[CONT VO]`, a `[SOT]` and a `[PKG]`
are one file each — and resets the count every time the monitor is on screen. If two or more
files play before the monitor comes back, the story must park it in D.

This reproduces all five §3 examples exactly: the reader and the plain VO need no D, the
SOT example does (VO + SOT before the tag), the SOTVO does not because it never returns to
camera, and the package does not because it is a single file. R1 then applies to consecutive
stories that both park the monitor in D — which is why two packages back to back are fine.

### 13.4 What is still assumed

| Constant | Value | Status |
|---|---|---|
| `words_per_minute` | 160 | Confirmed good enough for now (§11.19); tweak as real scripts accumulate. |
| `cg_char_ceiling` | 39 | Confirmed (§11.9). |
| `bump_cg_char_ceiling` | UNSET | The bump CG format is not specified yet (§11.21), so R5 skips bump CGs. |
| `break_seconds` / `weather_seconds` | UNSET | Needed before the half-hour clock can be reconciled (§11.20). |
| `pkg_ceiling_seconds` | 180 | From §3, "3:00 needs to be stellar". Never confirmed directly. |
| `block_budget_tolerance_seconds` | 10 | Invented. |

### 13.5 Judgement calls that remain the build's, not Phil's

1. **R7 is enforced on whole VO stories.** Inside a composite, a short VO leg is normal
   because the story continues; only an over-long leg warns.
2. **R4 is checked per segment**, which means a bare tag segment needs `[NO CG: ...]`.
3. **Segment mode is derived, not declared** — from the cues present, so a mislabeled story
   cannot lie to the validator.
4. **Copy inside a `[PKG]` is not counted as read time**, because it is already inside the
   package's declared duration. Copy after `[CONT VO]` is counted, because the anchor is live
   again.
5. **A double read is checked at block level for C and D.** §11.2 says both anchors are
   involved in reading the stories; the engine requires both to appear in the block but does
   not require every individual story to be a double read.

---

## 13.6 Inception generates the markup

Discovered from the previous implementation, and it changes what §4 is for.

The agent does not type `[CAM2 OX3]` into Inception. Inception has its own shortcut
expansion: typing `[OX2` and pressing ENTER creates a real production element, and
Option+2 inserts MEGAN. So the §3/§4 markup is the **validated intermediate form** — what the
rule engine checks and what a human reads in a diff — while what actually gets typed is a
**keystroke plan** derived from it.

That is a good split rather than a problem: the validator stays the eval harness for
everything downstream (§10), and the keystroke layer becomes a narrow, separately testable
translation at the very end. It does mean `serialize_story()` is not what drives Inception,
and a `plan_keystrokes(story)` function is still to be written.

---

## 14. Runtime constraints

**The deliverable is a Python program, run from a terminal. Not an application.** That is the
only thing that runs on the work machine, so it is a hard constraint on every design decision
below the line, not a preference.

What follows from it:

- **Standard library first.** Milestone 1 has no dependencies at all and should stay that way.
  Every dependency added past this point needs a reason and a plan for how it gets onto a
  locked-down machine.
- **Selenium over Playwright** for browser work. Not just because §11.4 says so — Selenium
  drives the Chrome that is already installed and approved, while Playwright downloads and
  manages its own browser binaries, which is exactly the kind of thing a work machine blocks.
- **Prefer attaching to a running browser over launching one.** Chrome started with a remote
  debugging port, logged in by hand, with the collector attaching to that session: no
  credential handling, no driver launching a suspicious second browser, and the human is at
  the desk anyway before a noon show. See `docs/wires/cnn-newsource.md`.
- **No background service, no installer, no packaging.** If it cannot be run as
  `python3 -m something` from a checkout, it does not fit.

### Confirmed 2026-08-31

- `pip install` works, with network to PyPI.
- Latest Python. 3.10+ syntax is safe.
- Chrome is present and Selenium can drive it.
- **Run by hand each morning.** No scheduler, no service, no daemon. The entry point is a
  command a producer types before the noon show.
- Phil can copy Python files onto the machine and run them. Where the line sits beyond that is
  not known, which is what `python3 -m newscast.doctor` exists to answer.

### The architectural consequence

Because the machine that can reach the wires is not the machine this code is written on,
**Selenium only navigates and authenticates. It never parses.** The collector takes
`driver.page_source` and hands the HTML to a pure function.

Everything hard — finding rows, reading fields, building stubs — is therefore testable here,
against saved HTML, with no browser and no credentials. Only navigation has to be debugged on
the work machine, and navigation is the part that fails loudly rather than silently.
