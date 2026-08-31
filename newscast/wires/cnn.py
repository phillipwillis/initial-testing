"""CNN Newsource listing parser (§10.3, §11.4).

Pure functions over HTML. Selenium fetches `driver.page_source`; everything here
runs on the resulting string, so it is testable without a browser, without
credentials and without the site (CLAUDE.md §14).

Selector policy, from `docs/wires/cnn-newsource.md`: the site is React/MUI with
emotion, so `css-1d6aoja`, `MuiGrid2-grid-xs-12` and the `__open--d5t9t` hash
suffixes are build artifacts that change on every CNN deploy. Only the
hand-authored names are used here — `metadataContainer`, `title`, `metadata`,
`metadataDivider`, `description` — and fields are identified by what they
contain rather than by position, so a reordered row still parses.

Verified against a real capture of the landing page on 31 Aug 2026. The fixture
is three rows lifted verbatim from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from newscast.markup import parse_duration
from newscast.wires.dom import Node, parse_html
from newscast.wires.stub import ContentType, StoryStub, parse_timestamp

CNN_SOURCE = "CNN Newsource"
LANDING_URL = "https://newsource.ns.cnn.com/landing"

_VERSION_RE = re.compile(r"^\s*version\b\s*(?P<n>\d+)?", re.I)

# "WE-001MO", "NE-005MO" — the Story Number, confirmed by cross-reference: the
# same code appears in the collapsed row's metadata and as "Story Number:" in
# the expanded panel. This is what a producer types into the rundown's Source
# column (docs/inception.md).
_STORY_NUMBER_RE = re.compile(r"^[A-Z]{2,3}-\d{3,4}[A-Z]{2}$")

# "01:02", "01:55" — what CNN prints as the duration. See StoryStub for why
# this is a hint rather than a running time.
_DURATION_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")

# Forms the wire ships video in. These line up with the §3 segment types, which
# is what makes the video schema worth parsing: the wire is telling us what the
# material can become before we have opened it.
FOOTAGE_TYPES = frozenset(
    {
        "VO", "VO/SIL", "SIL", "SOT", "VOSOT", "VO/SOT",
        "PKG", "DONUT", "LOOK LIVE", "RAW", "LIVE", "WRAP", "CUT SOUND",
    }
)

# The Media icons carry a real aria-label, which is the semantic name and the
# thing to match on. Matched exactly, never as a substring: the MUI icon name
# for a wire article is "DescriptionIcon", and looking for "script" inside that
# matches de-SCRIPT-ionicon, which is the right answer by accident and one icon
# rename away from being wrong.
MEDIA_ICONS = "mediaAndBundleIcons"

_MEDIA_LABELS = {
    "wire article": ContentType.SCRIPT,
    "script": ContentType.SCRIPT,
    "image": ContentType.IMAGE,
    "video": ContentType.VIDEO,
}

# Secondary signal, for a row whose icons carry no aria-label.
_MEDIA_TESTIDS = {
    "descriptionicon": ContentType.SCRIPT,
    "imageicon": ContentType.IMAGE,
    "playarrowicon": ContentType.VIDEO,
    "playcirclefilledicon": ContentType.VIDEO,
    "videocamicon": ContentType.VIDEO,
}

# The thumbnail lives on a rendition host and its path carries CNN's own slug
# for the story: WEA_NORTHEAST_STORMS_HEAT_CLIMATE, INT_SWITZERLAND_SHOOTING_RAVE.
_THUMBNAIL_SLUG_RE = re.compile(
    r"newsource-image-renditions[^/]*\.ns\.cnn\.com/(?P<slug>[A-Z0-9_]{4,})/"
)


def _caption_fields(metadata: Node) -> list[Node]:
    """The real fields in the metadata line, minus the '|' separators."""
    return [
        n
        for n in metadata.find_all(tag="span")
        if not n.has_class("metadataDivider") and n.text.strip()
    ]


@dataclass
class RowMetadata:
    timestamp_text: str = ""
    version: Optional[int] = None
    source: str = ""
    story_number: str = ""
    market: str = ""
    footage_type: str = ""
    wire_duration_seconds: Optional[float] = None


def _classify_metadata(metadata: Node) -> RowMetadata:
    """Read the metadata line, whichever schema the row uses.

    There is more than one. A wire article reads:

        31 Aug 26 07:29 ET | CNN | Version 11

    while a video record from an affiliate reads:

        31 Aug 26 06:52 ET | WABC | NE-005MO | New York, NY | VO/SIL | 01:02

    and a graphic reads simply:

        31 Aug 26 | CNN Weather via CNN Newsource

    So fields are identified by what they contain rather than by where they sit,
    and whatever is left over is source then market, in order. Positional
    parsing would silently put a market in the source column the first time a
    row shape changed.
    """
    found = RowMetadata()
    leftovers: list[str] = []

    for node in _caption_fields(metadata):
        text = node.text.strip()

        if not found.timestamp_text and parse_timestamp(text):
            found.timestamp_text = text
            continue

        match = _VERSION_RE.match(text)
        if match and found.version is None:
            # The title attribute holds the bare number where the text reads
            # "Version 11"; prefer it, fall back to the digits in the text.
            raw = node.attr("title") or (match.group("n") or "")
            if raw.isdigit():
                found.version = int(raw)
                continue

        if not found.story_number and _STORY_NUMBER_RE.match(text):
            found.story_number = text
            continue

        if found.wire_duration_seconds is None and _DURATION_RE.match(text):
            found.wire_duration_seconds = parse_duration(text)
            continue

        if not found.footage_type and text.upper() in FOOTAGE_TYPES:
            found.footage_type = text.upper()
            continue

        leftovers.append(node.attr("title") or text)

    leftovers = [x for x in leftovers if x]
    if leftovers:
        found.source = leftovers[0]
    if len(leftovers) > 1:
        found.market = leftovers[1]

    return found


def parse_media_types(scope: Node) -> tuple[ContentType, ...]:
    """Content types from the row's `Media :` icons.

    Scoped to the `mediaAndBundleIcons` container. The row also holds a copy
    button and a checkbox, and the page header holds Notifications, Planner and
    Download Manager icons — none of which describe the story, and all of which
    a looser search would eventually pick up.
    """
    icons = scope.find(cls=MEDIA_ICONS) or scope
    found: list[ContentType] = []

    for node in icons.walk():
        label = _norm_label(node.attr("aria-label"))
        kind = _MEDIA_LABELS.get(label)
        if kind is None:
            kind = _MEDIA_TESTIDS.get(_norm_label(node.attr("data-testid")))
        if kind is not None and kind not in found:
            found.append(kind)

    return tuple(found)


def _norm_label(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def parse_story_slug(scope: Node) -> str:
    """CNN's own slug for the story, off the thumbnail's rendition URL.

    Not the Story Number the search box takes — that is not in the listing DOM
    at all — but it is stable per story and it is human-readable, which makes it
    a far better key than a hash of the headline. Rows with no thumbnail (the
    CNN Wire logo rows) have none.
    """
    for node in scope.walk():
        match = _THUMBNAIL_SLUG_RE.search(node.attr("src"))
        if match:
            return match.group("slug")
    return ""


def parse_row(scope: Node) -> Optional[StoryStub]:
    """Parse one listing row. None if it carries no headline."""
    title = scope.find(cls="title")
    if title is None:
        return None

    # Read the attribute rather than the text. MuiTypography-noWrap truncates
    # with CSS rather than in the DOM, so the two agree today — but the
    # attribute is the value the app set deliberately, and it survives the app
    # deciding to shorten what it renders.
    slug = title.attr("title") or title.text

    metadata_node = scope.find(cls="metadata")
    meta = _classify_metadata(metadata_node) if metadata_node is not None else RowMetadata()

    description = scope.find(cls="description")

    return StoryStub(
        id=meta.story_number or parse_story_slug(scope),
        slug=slug.strip(),
        source=meta.source or CNN_SOURCE,
        timestamp=parse_timestamp(meta.timestamp_text),
        timestamp_text=meta.timestamp_text,
        version=meta.version,
        teaser=description.text.strip() if description is not None else "",
        content_type=parse_media_types(scope),
        story_number=meta.story_number,
        market=meta.market,
        footage_type=meta.footage_type,
        wire_duration_seconds=meta.wire_duration_seconds,
    )


ROW_CONTAINER = "storyLineItemWrapperBox"


ARTICLE_PREVIEW = "article-preview"


def parse_expanded_story(html: str) -> str:
    """The script text from an expanded row, with its line structure intact.

    Expanding a row renders the wire script as a run of `<p>` inside
    `.article-preview`. The markers that matter — `--SUPERS--`, `--LEAD IN--`,
    `--REPORTER PKG-AS FOLLOWS--` — are line-oriented, so the text has to come
    out with those boundaries preserved. Feed the result to
    `cnn_script.parse_wire_script`.
    """
    preview = parse_html(html).find(cls=ARTICLE_PREVIEW)
    return preview.block_text if preview is not None else ""


def _row_scopes(root: Node) -> list[Node]:
    """The per-story regions of the listing.

    `storyLineItemWrapperBox` is the row container — confirmed from the previous
    working implementation, which located stories with
    `//div[contains(@class,'storyLineItemWrapperBox')]`. Falls back to
    `metadataContainer`, then to the parent of each `metadata` line, so a
    renamed wrapper degrades instead of returning nothing.
    """
    for cls in (ROW_CONTAINER, "metadataContainer"):
        scopes = root.find_all(cls=cls)
        if scopes:
            return scopes

    seen: list[Node] = []
    for metadata in root.find_all(cls="metadata"):
        parent = metadata.parent
        if parent is not None and parent not in seen:
            seen.append(parent)
    return seen


def parse_listing(html: str) -> list[StoryStub]:
    """Parse a Newsource listing page into §6 stubs.

    Feed it `driver.page_source`.
    """
    root = parse_html(html)
    stubs = []
    for scope in _row_scopes(root):
        stub = parse_row(scope)
        if stub is not None:
            stubs.append(stub)
    return stubs
