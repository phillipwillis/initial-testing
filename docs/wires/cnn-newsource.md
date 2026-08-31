# CNN Newsource — collection notes

Working notes for §10.3 (wire collection). **Verified against a real capture** of the landing
page taken on 31 Aug 2026 with `python3 -m newscast.capture page`; the parser is tested
against three rows lifted verbatim from it. Anything still inferred says so.

No credentials appear in this file or anywhere in this repo. See §"Access" below.

---

## The path in

1. `https://newsource.ns.cnn.com/` → log in
2. Lands on `https://newsource.ns.cnn.com/landing`

## What the landing page is

A React single-page app built on MUI (Material-UI) with emotion CSS-in-JS. Three regions:

| Region | Contents |
|---|---|
| Left rail | Facet filters — content type, video format, categories |
| Centre | "All Stories" list, newest first, each row expandable in place |
| Right rail | "Live Channels" — CH1/CH2/CH3 with what is currently playing |

A red promo banner sits above the header ("LIVE from the White House: AM Lives") with a
dismiss X. Header carries search, notifications, a calendar, a download icon and the account
menu.

## The story list — this is the §6 phase 0 stub source

Each row carries, without opening anything:

```
<headline>
31 Aug 26 06:15 ET | CNN | Version 1
<one-line teaser>
Media : [script] [image] [video]
```

That maps almost exactly onto the §6 stub, which is the good news — phase 0 should not need
to open a single story:

| §6 stub field | Where it comes from |
|---|---|
| `slug` | the headline |
| `timestamp` | `31 Aug 26 06:15 ET` |
| `source` | `CNN` (one row showed a CNN Wire logo thumbnail instead) |
| `content_type` | the Media icons — script / image / video |
| `id` | not yet identified; probably in the row's link or a data attribute |
| `tags[]` | probably the categories in the left rail |
| `related_ids[]` | **not visible in the list** — still the open question from §11.4 |

**Version numbers are a freshness signal.** Rows showed "Version 1" next to "Version 19" and
"Version 14" on the same morning. A high version number is a story that has been updated all
day — directly useful for §7 `freshness`, and worth capturing in the stub.

Expanding a row (the chevron at the right) opens the full article inline — headline,
"Originally Published", byline, and the body copy — rather than navigating away. Whether that
inline panel carries everything `wire_expand()` needs, or whether there is a separate story
page with more, is not yet known.

## Facets in the left rail

Counts are from one morning and show the corpus is far larger than a day's work:

- **Content type** — Image (5441, greyed), Wire Article (4018), Video (4476),
  Downloadable (1102), Embeddable (3822, greyed)
- **Video formats** — File (537), **Packages (1386)**, **Raw (49)**, Vertical Video (67),
  **Cut Sound (683)**
- **Bundles**, **Has Script** — standalone checkboxes
- **Categories → Great for digital** — Editors' Choice (14)
- **Trending** — Trump Presidency (138), Economy/Inflation (29), 9/11 Attacks – 25 Years
  Later (28), Immigration (23), Wildfires (23), 9/11 Remembrance (12), Weekend Lookout (12)

Three of these matter more than the rest, because they map onto our segment types (§3):

- **Packages** → PKG material
- **Cut Sound** → SOT material; this is where soundbites come from
- **Raw** → B-roll, which is what a VO needs, and what a decomposed PKG becomes (§0.2)
- **Has Script** → whether wire copy exists to rewrite, versus video we would write to

§6 expects "roughly 200" fresh stories a day against 4018 wire articles and 4476 videos in
the index, so **the date filter is doing most of the work** and we have not identified it yet.
The header calendar icon and the calendar/sort toggle above the list are the candidates.

## DOM structure — a list row

From the Elements panel, inspecting the metadata line of a row:

```html
<span class="MuiTypography-root MuiTypography-caption MuiTypography-noWrap title css-1levgce"
      title="Tropical Storm Edouard or a depression could soon form in the Gulf">
  Tropical Storm Edouard or a depression could soon form in the Gulf
</span>

<p class="MuiTypography-root MuiTypography-body1 MuiTypography-noWrap metadata css-yzz7bx">
  <span class="MuiTypography-root MuiTypography-caption css-1d6aoja">31 Aug 26 06:15 ET</span>
  <span class="MuiTypography-root MuiTypography-body1 metadataDivider css-ypy096">|</span>
  <span class="MuiTypography-root MuiTypography-caption css-1d6aoja" title="CNN">CNN</span>
  <span class="MuiTypography-root MuiTypography-body1 metadataDivider css-ypy096">|</span>
  <span class="MuiTypography-root MuiTypography-caption css-1d6aoja" title="1">Version 1</span>
</p>

<span class="MuiTypography-root MuiTypography-subBody description css-1wqzo7f">
  A new potential tropical system is putting Texas and Louisiana on alert.
</span>
```

Two things make this much more tractable than the outer layout did.

**Hand-written class names sit alongside the generated ones.** Every element carries MUI
classes and a `css-*` hash, but also exactly one meaningful name the app's authors chose:
`title`, `metadata`, `metadataDivider`, `description`, and from the expanded panel
`article-preview`, `originally-published`, `byline`, plus `graphicContainer` and
`metadataContainer`. Those are the selectors.

**The `title` attributes carry clean values while the text is decorated.** The source span is
`title="CNN"`, and the version span is `title="1"` where the text reads "Version 1". Parse the
attribute, not the text — no stripping a "Version " prefix that might get relabelled. The
headline's `title` attribute also holds the full string where the visible text may be
truncated by `MuiTypography-noWrap`.

So a row parses as:

| Stub field | Selector | Read from |
|---|---|---|
| `slug` | `span.title` | `title` attribute |
| `timestamp` | `p.metadata > span.MuiTypography-caption` (1st) | text |
| `source` | `p.metadata > span.MuiTypography-caption` (2nd) | `title` attribute |
| version | `p.metadata > span.MuiTypography-caption` (3rd) | `title` attribute |
| teaser | `span.description` | text |
| `content_type` | the `Media :` icons | not yet inspected |

Skip `.metadataDivider` spans — they are the `|` separators. Better still, take the caption
spans that carry a `title` attribute and treat position as a fallback, in case a field is
absent on some rows (the CNN Wire row showed a different thumbnail treatment, so rows are not
all identical).

## DOM structure — an expanded story

From the Elements panel on an expanded story:

```html
<div class="js-components-stories-Media-Main__open--d5t9t ... MuiBox-root css-1mhl8wi">
  <div class="js-components-stories-Media-ContentArea__wrapper--FNhAj MuiBox-root css-sgcxw6">
    <div class="MuiGrid2-root ... css-1dtnbqp">
      <div class="article-preview">
        <h1>Tropical Storm Edouard or a depression could soon form in the Gulf</h1>
        <div class="originally-published">Originally Published: 31 AUG 26 06:15 ET</div>
        <div class="byline">By Meteorologists Briana Waxman and Chris Dolce</div>
        <p>…</p>
        <p>…</p>
      </div>
```

Other containers seen nearby: `metadataContainer css-1grs4ev`, `graphicContainer css-1xd7xq7`.

### Selector policy — the important part

**Never select on a `css-*` or `__name--hash` class.** `css-1mhl8wi`, `css-sgcxw6`,
`css-1dtnbqp`, `css-5rrml4` and the `--d5t9t` / `--FNhAj` suffixes are generated by emotion
and CSS Modules at build time. They change whenever CNN ships a deploy, and a scraper built
on them breaks silently on a Tuesday morning with no warning.

Stable hooks, in order of preference:

1. **Semantic class names** the app authors wrote by hand: `.article-preview`,
   `.originally-published`, `.byline`. These look deliberate and are the best anchors we have.
2. **Component-name prefixes** — the `js-components-stories-Media-Main__open` part is stable
   even though the hash after `--` is not, so match on a prefix:
   `[class^="js-components-stories-Media-ContentArea__wrapper"]`
3. **Structure and visible text** — headings, labels like `Media :`, relative position.

Never: `MuiGrid2-grid-xs-12`, `css-*`, or anything with a hash in it.

Any selector we settle on wants a saved copy of the page as a fixture, so the tests fail on
our machine when CNN changes rather than at 11:40am.

## There is an internal JSON API

The console showed repeated:

```
Uncaught (in promise) AxiosError: Request failed with status code 401
Failed to load resource: the server responded with a status of 401
  …newsource-content-ap…etActive/Domestic
```

Two things follow.

**The page is a client for a JSON API.** The SPA fetches from something like
`newsource-content-api/…/getActive/Domestic` over XHR and renders the result. If we are
permitted to call that directly, it is a far better collection path than DOM scraping:
stable shapes, real IDs, no selector rot, and the related-story links §11.4 needs are
probably fields rather than something to discover by navigating. This is worth asking
the CNN Newsource rep about before building anything — a paying affiliate may already have a
feed entitlement, which would delete this whole milestone's risk. **Question for Phil.**

**Sessions expire, and the failure is quiet.** Those 401s were live in a tab that looked
fine — the UI does not obviously announce the expiry. A long-running collector has to detect
401 and re-authenticate rather than assume an empty result means a quiet news day. Treat
"zero stories returned" as an error condition, never as a valid answer.

## Access

Credentials never enter this repo, this transcript, or any code.

**Preferred: attach to a Chrome that is already logged in.** Start Chrome once with a remote
debugging port, log in by hand, and have Selenium attach to that running browser rather than
launch its own. The collector then inherits a live session and never handles a password at
all — no credential in the environment, no credential in a vault, nothing to leak. It also
uses the Chrome that is already installed and approved on the work machine (see CLAUDE.md
§14), and it matches how a producer actually works: the browser is open anyway.

The cost is that somebody logs in each morning. For a noon show where a human is at the desk
from ten, that is close to free, and it sidesteps the whole "how do we get credentials to the
agent" problem.

**Fallback: environment variables**, if the collector ever has to log in unattended:

```
CNN_NEWSOURCE_URL       https://newsource.ns.cnn.com/
CNN_NEWSOURCE_USERNAME
CNN_NEWSOURCE_PASSWORD
```

Read at runtime, never logged, never written to disk.

## There is more than one row schema

The most important thing the captures settled. A **wire article** row reads:

```
31 Aug 26 07:29 ET | CNN | Version 11
```

A **video record** from an affiliate reads:

```
31 Aug 26 06:52 ET | WABC | NE-005MO | New York, NY | VO/SIL | 01:02
```

and a **graphic** reads simply:

```
31 Aug 26 | CNN Weather via CNN Newsource
```

Six fields, three fields, two fields — same `metadata` element, same caption spans, same
dividers. Positional parsing puts a market in the source column the first time it meets the
second shape, so fields are identified by what they contain: a timestamp is what parses as
one, a Story Number matches `NE-005MO`, a duration matches `01:02`, a footage type is in a
known set, and what is left over is source then market, in order.

### The printed duration is not the running time

Phil, 31 Aug: *"Duration in CNN is unreliable. The script may be for 20 seconds, and the
duration in a marker for how much b-roll is in the video file. Packages are notoriously
unpredictable with CNN."*

So the number in the listing is a sort key and nothing more. A duration that reaches a
rundown decides whether the show runs over, and this one cannot carry that weight. The field
is named `wire_duration_seconds` to keep that visible at every call site, and
`StoryStub.duration_is_trustworthy` returns False as the single place to change if that ever
stops being true.

Where a real duration can come from, in the order worth trying:

1. **`estimate_read_time` on the copy we write** — authoritative for anchor read time, which
   is the whole of a VO and the intro and tag of a package.
2. **The media element's own duration**, once the player has loaded the file.
3. **The `TRT:` field in the wire script**, where the script carries one.

`python3 -m newscast.probe --only duration` puts all three against one story and reports
which agree. Until that comes back, treat every package length as unknown.

### The video schema is worth having

It carries what slotting needs, before a story is ever opened:

| Field | Example | Why it matters |
|---|---|---|
| Story Number | `WE-001MO` | The id. This is what a producer types into the rundown's Source column (`docs/inception.md`) |
| Market | `Seattle-Tacoma, WA` | §7 `viewer_impact` — an Idaho Falls show weights local and regional hardest |
| Footage type | `VO/SIL`, `DONUT`, `PKG` | Maps onto the §3 segment types. The wire is saying what the material can become |
| Duration | `01:02` | **A hint only — see below** |

**The Story Number is confirmed**, not inferred: `WE-001MO` appears in the collapsed row's
metadata line *and* as `Story Number:` in that story's expanded panel.

## What the capture settled

**The story list is lazy-loaded, not paged.** The capture held exactly five
`storyLineItemWrapperBox` elements — one screenful. There is no pager and no virtual-list
library in the DOM, so rows arrive as you scroll. The collector therefore scrolls and
accumulates rather than walking pages.

**There is no date filter.** The two controls above the list are `Sort by Date` and
`Sort by Relevance` — sorting, not filtering. So "the past day" is not a query: it is
"scroll, sorted by date, until the timestamps fall past the cutoff". That is how §6 gets its
~200 stories, and it means collection cost scales with how far back the cutoff sits.

**Media icons carry a real `aria-label`**, which is the thing to match:

| aria-label | data-testid | Means |
|---|---|---|
| `Wire Article` | `DescriptionIcon` | Script exists |
| `Image` | `ImageIcon` | Stills |
| `Video` | `PlayArrowIcon` | Playable video |

Match the label **exactly**. Searching `DescriptionIcon` for the substring `script` matches
de-**script**-ionicon — the right answer for the wrong reason, and wrong as soon as CNN
renames an icon. The icons live in a `mediaAndBundleIcons` container; the row also holds a
copy button, and the page header holds Planner, Notifications and Download Manager icons that
a looser search picks up eventually.

**A story identifier exists, on the thumbnail.** Rendition URLs carry CNN's own slug:

```
newsource-image-renditions-prd.ns.cnn.com/INT_SWITZERLAND_SHOOTING_RAVE/…
newsource-image-renditions-prd.ns.cnn.com/WEA_NORTHEAST_STORMS_HEAT_CLIMATE/…
```

Human-readable, stable per story, and prefixed by desk (`INT`, `WEA`). Not the Story Number
the search box takes — that is not in the listing DOM at all — but far better than hashing a
headline. Rows with no thumbnail (affiliate logo rows) have none.

**Sources are not all CNN.** The capture carried `KCAL, KCBS` and `CNN Español` alongside
`CNN`. Affiliate credits list multiple call signs in one field, so the source is a label to
keep verbatim, not an enum.

**`MuiTypography-noWrap` truncates with CSS, not in the DOM.** An earlier note here assumed
the visible text could be clipped and the `title` attribute was needed to recover it. Not so —
they agree. Reading the attribute is still right, because it is the value the app set
deliberately, but the reason was wrong.

## Getting real markup into the repo

The fixture the parser is tested against was reconstructed from screenshots, so it pins the
parsing logic without proving the markup. Replacing it takes one of:

```bash
python3 -m newscast.capture page --out cnn-landing.html --tab newsource
```

or, with no code at all: DevTools → Elements → right-click `<html>` → Copy → Copy outerHTML,
and paste into a file. Chrome's "Save Page As" does **not** work here — this is a React app,
so the saved source is an empty `<div id="root">`.

Either way the file needs reading before it travels. `newscast.capture` scrubs emails, bearer
tokens, JWTs, key-shaped JSON fields and long hex ids, but that is best effort.

## The expanded panel

Expanding a row renders the wire script inside `.article-preview` as a run of `<p>`, one per
line of script. Every marker `cnn_script.py` knows was present and parsed:
`--SUPERS--`, `--LEAD IN--`, `--REPORTER PKG-AS FOLLOWS--`, `--TAG--`,
`-----END-----CNN.SCRIPT-----`, `--KEYWORD TAGS--`.

Two things the real copy taught us that invented test data had not:

1. **The panel has no `Footage Type:` line.** That field comes from the listing row, not the
   script, so "is this a package" has to be answered by the presence of a reporter section.
   The row's own footage type is the better answer where it exists.
2. **The SUPERS block opens with slates.** The day and the location sit above the first
   timecode, and real supers include single-word names:

   ```
   Saturday
   Seattle

   :05 - :07
   Kelly
   Seattle Resident
   ```

   `Kelly` is a super. Any "looks like a person" heuristic wanting two words drops it, so the
   parser takes position after the timecode instead: timecode, name, title.

Because the script is `<p>` per line, extracting it needs block-aware text. Collapsing the
subtree to one line — the right thing for a headline — destroys the line structure every one
of those markers depends on.

## Still unknown

1. **Related stories.** §11.4 says these must be discovered by navigating. Neither the
   collapsed listing nor the expanded panel showed them.
2. **Video and script download.** The header download icon, the per-row copy button, and how
   §11.7's "download the video, transcribe, delete" actually gets the file.
3. **Whether we may use the JSON API** instead of the DOM.
