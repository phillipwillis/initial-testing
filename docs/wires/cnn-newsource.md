# CNN Newsource — collection notes

Working notes for §10.3 (wire collection). Recorded from Phil's walkthrough and two
screenshots of the landing page on 31 Aug 2026, one with DevTools open. **Nobody has driven
this site from code yet** — everything here is read off the UI, so treat it as a starting
map, not verified behaviour.

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

## Still unknown

1. **The date filter.** Without it there is no "past day" and no ~200 stories.
2. **Story IDs.** Nothing in the screenshots shows a stable per-story identifier.
3. **Related stories.** §11.4 says these must be discovered by navigating. Not yet seen.
4. **Paging.** Whether the list pages, scrolls infinitely, or lazy-loads.
5. **The expanded panel vs. a story page.** Which one `wire_expand()` should read.
6. **Video and script download.** The download icon in the header, the per-row copy icon, and
   how §11.7's "download the video, transcribe, delete" actually gets the file.
7. **Whether we may use the JSON API** instead of the DOM.
