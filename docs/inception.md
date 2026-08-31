# Inception — adapter notes

Everything here is read off Phil's previous working implementation, so unlike the CNN DOM
notes it describes behaviour that **actually ran against the real system**. Treat it as the
most reliable information in the repo about Inception, and still verify before relying on any
single selector.

No credentials here. See §"Access".

---

## Access

`https://inception.localnews8.com/`

Login is inside an iframe — `iframe[src*='User/Authentication/Dialog']` — with `#username`
and `#password`. Return to `default_content` after submitting.

---

## The frame map

This is the hard part of Inception and the source of most of the previous implementation's
complexity. Frames, and the most durable handle for each:

| Frame | Handle | Notes |
|---|---|---|
| Login dialog | `src*='User/Authentication/Dialog'` | Only present before login |
| Running Order Manager | `src*='RunningOrderManager'`, title `Running Order Manager` | Where shows are opened from |
| An open show | `document.title` starts with the air time | e.g. `5:00 AM 01/22/26` |
| Story editor | `src*='BroadcastStory/View.do'` | Holds `#objects`, the toolbar, and the CKEditor |
| CKEditor wysiwyg | `iframe.cke_wysiwyg_frame`, body `body.cke_editable` | Nested inside the story editor |
| CG editor | `id` starts with `view-` (e.g. `view-10`) | Opens on double-clicking a CG object |

Server routes (`BroadcastStory/View.do`) are the best handles available: they are application
structure rather than generated markup, so they outlast redesigns. Titles are next best. Frame
index is a last resort and should never be hard-coded.

### Why frames were painful, and what we do instead

`driver.switch_to.frame()` is a *move*, so every function has to know where the driver
currently is. The previous implementation shows what that costs: functions that scan every
iframe hunting for the right one, `switch_to.parent_frame()` in `finally` blocks, retry loops
around stale elements, and a bare `time.sleep(20)` waiting for the CG editor to appear. Any
failure mid-sequence leaves the driver somewhere unknown, and the next call starts from there.

`newscast/inception/frames.py` stops tracking position. A **frame path** says where an
operation belongs, as a sequence of matchers from the document root, and every operation
re-walks that path from `default_content` before it runs. Re-walking costs a few DOM queries,
which is nothing next to a network round trip, and it is idempotent: it cannot inherit a bad
context from a failure elsewhere.

The matchers are pure predicates over frame descriptors, so the matching logic is unit tested
without a browser — see `tests/test_frames.py`.

---

## Running Order Manager

1. Toolbar button: `li.toolbar-item[onclick*="inception.RunningOrder.open"]`
2. The ROM frame contains a **fancytree** — `span.fancytree-title` — with folders like
   `1. MORNING`. Click the node, then its `.fancytree-expander` if not already expanded
   (`fancytree-exp-e` / `fancytree-exp-ed` in the node's class means expanded).
3. Shows are a **SlickGrid**: `#gridView .grid-canvas .slick-row`. Rows carry the show name
   and a date. Pick the most recent row whose date is not in the future.
4. Open a show by **double-clicking** the name cell `div.slick-cell.l1`.

The tree may itself be nested one frame deeper — the previous code checked for
`span.fancytree-title` and descended if it was missing.

---

## The show rundown grid

Also SlickGrid. Rows are `.grid-canvas .slick-row[row='<n>']`; cells are addressed by column
index as `.slick-cell.l<n>.r<n>`.

| Column | Index | Contents |
|---|---|---|
| Shot | 6 | `OX2`, `OX3`, `OX5` … the block's shot for that story |
| Source | 7 | The CNN **story number** — what the producer wants pulled |
| Notes | 21 | The trigger (see below) |

> The previous code read Source from `l7` in `scan_show` but double-clicked `l8` in
> `open_story_from_row`. One of those is wrong, or the column moved between writings.
> **Verify before trusting either.**

**Columns are horizontally virtualised.** A cell that is scrolled out of view does not exist
in the DOM. Source and Shot are on the left, Notes is on the right, so reading a whole row
means scrolling the viewport (`.slick-viewport`) left, reading, then right, and reading again.
Rows are vertically virtualised too — scroll and re-query, and reset `scrollTop` to 0 at the
start of every scan or the second pass starts halfway down.

A show only gets touched if it is **monitored**: `li[item='MosMonitor.Unmonitor']` present.

---

## The handoff protocol — this is §11.6, already solved

The producer and the agent already have a working contract, and it is better than anything
worth inventing:

1. The producer puts a **CNN story number in the Source column** and a **number in Notes**.
2. The agent scans for rows where both are non-empty, and acts on the Notes code.
3. When the story is written and saved, the agent **clears the Notes cell**.

An empty Notes cell means "nothing wanted here". That is the whole protocol: a work queue,
a request type, and a completion marker, in two cells a human already fills in by habit.

Notes codes from the previous implementation:

| Code | Meaning |
|---|---|
| `0` | Rewrite the story already in the editor |
| `2` | Pull from CNN and edit |
| `3` | Write a bump |

Clearing Notes is done by clicking the cell, then `SPACE`, `BACKSPACE`, `BACKSPACE`, `ENTER` —
editing is entered with a space rather than Enter, which starts an edit rather than opening
the row.

---

## Writing a script: Inception generates the markup

**This changes how §4 is used, and it is the single most important thing in this file.**

The agent does not type `[CAM2 OX3]` into the editor. Inception has its own shortcut
expansion: type `[OX2` and press ENTER, and Inception expands it into a real production
element. The §3/§4 markup in `CLAUDE.md` is therefore the *validated intermediate form* — what
the rule engine checks — and a separate **keystroke plan** is what gets typed.

Bracket shortcuts, with the fix-ups the previous code applied after each:

| Type | Then | Because |
|---|---|---|
| `[OX2` | ENTER | Clean |
| `[OX3` | ENTER, BACKSPACE ×2 | Removes an auto-appended `-D` |
| `[OX4` | ENTER, BACKSPACE ×2 | Same |
| `[OX5` | ENTER, BACKSPACE ×2 | Same |
| `[VO` | ENTER | Clean |
| `[PKG` | ENTER, BACKSPACE ×4, DELETE ×4, then type the TRT | Removes `-D` and clears an auto-filled `0:00` |

Each needs a short pause (~0.35s) after the bracket text so Inception can expand it.

Keyboard shortcuts (Option is ALT in Selenium):

| Shortcut | Inserts |
|---|---|
| Option+1 | DOUG |
| Option+2 | MEGAN |
| Option+4 | LINDA |
| Option+5 | JEFF |
| Option+s | A CG placeholder |
| Option+Cmd+h | END of story |

Doug and Linda are the morning anchors; the noon show is Jeff and Megan (§11.2), so the noon
agent needs **Option+2 and Option+5**.

There is also a **SOT toggle** in the CKEditor toolbar — `a[aria-label='SOT']` — which turns
"green" mode on and off for soundbite text. Inserting a CG while green is on drops you out of
it, so a CG inside a package has to be followed by re-enabling SOT.

Saving: `li.toolbar-item[exec='save']` in the story editor frame. Wait after saving before
closing the window — the previous code slept 3 seconds and still commented that the viewport
needs time to unlock.

---

## Story windows

Open stories are viewports at the top level: `.viewport`, with `.header h1` for the title and
`.controls .close` to close. A viewport is a **story** rather than the ROM if its header icon
is `Story.png` or its title ends in ` - VO`, ` - PKG` or ` - SOT`; the ROM is identifiable by
an `extension` attribute containing `runningordermanager` and must never be closed by mistake.

Because titles are the only way to tell story windows apart, the previous implementation
snapshotted open titles before opening a story and diffed after, to learn what the new window
was called. That is worth keeping.

---

## CG objects

CG placeholders appear in the story editor as `#objects ul.ui-sortable > li`, identified by
`l3d_regular` in their text content, ordered by an `index` attribute and carrying a
`mosstoryitem` attribute. Double-clicking one opens the CG editor frame.

Inside the CG editor the fields are `textarea.text-area__area`, and the first one contains the
placeholder text `LINE ONE TEXT`.

This is the part §9 warns about — "the CG system in particular has been the main source of
breakage" — and the previous code confirms it: the CG fill is the only place that needed a
20-second sleep, and the block that populates CGs is commented out in the working version.

**Build the CG path first and test it hardest** (§9). It is the least reliable part of the
least forgiving system.

---

## What not to carry forward

The previous implementation worked, which is worth more than any critique. These are the
places where it accumulated risk, and where this build should do something different:

1. **Counted TABs to reach a button.** The CG fill presses TAB 22 times, types, TABs once,
   types, then TABs 9 more times and presses ENTER to hit "Update Story". If the form ever
   gains a field, this silently types into the wrong place. Target the button.
2. **Counted BACKSPACEs after shortcut expansion.** Same failure mode — if Inception changes
   what it auto-fills, the script quietly eats real characters. Read the field back and fix it
   up, or select-all and retype.
3. **`time.sleep(20)`.** Wait for a condition, not a duration. On a slow VPN morning 20
   seconds is not enough; on a fast one it is 20 seconds of the producer's time.
4. **`random.choice` for which anchor reads first.** Non-deterministic output cannot be
   validated or reproduced, and for the noon show it is also wrong: §11.2 fixes who reads
   what.
5. **Loose trigger regexes.** `(^|\D)2(\D|$)` matches a `2` anywhere in the Notes cell,
   including inside a note a human wrote for a human. Anchor the whole cell.
6. **Two browsers.** The previous code drove Inception and CNN in separate `webdriver.Chrome()`
   instances and switched windows between them. Two sessions, two logins, twice the ways to
   lose context. One browser with two tabs is enough.

---

## Still unknown

1. Whether Source is column 7 or 8 (the previous code says both).
2. What the CG editor's "Update Story" button can be targeted by directly.
3. Whether story locking (§9) surfaces in the DOM in any way the agent can detect, or whether
   a lock is only discovered by an edit failing.
4. How the rundown reports back-timing and over/under (§11.1) — Inception holds those numbers
   and the agent needs to read them.
