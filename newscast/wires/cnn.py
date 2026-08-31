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
from typing import Optional

from newscast.wires.dom import Node, parse_html
from newscast.wires.stub import ContentType, StoryStub, parse_timestamp

CNN_SOURCE = "CNN Newsource"
LANDING_URL = "https://newsource.ns.cnn.com/landing"

_VERSION_RE = re.compile(r"^\s*version\b\s*(?P<n>\d+)?", re.I)

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


def _classify_metadata(metadata: Node) -> tuple[str, Optional[int], str]:
    """Return (timestamp_text, version, source).

    Identified by content, not position: the timestamp is the field that parses
    as one, the version is the field that says so, and the source is what is
    left. A relabelled or reordered row still comes out right.
    """
    timestamp_text = ""
    version: Optional[int] = None
    leftovers: list[Node] = []

    for field in _caption_fields(metadata):
        text = field.text.strip()
        if not timestamp_text and parse_timestamp(text):
            timestamp_text = text
            continue
        match = _VERSION_RE.match(text)
        if match and version is None:
            # The title attribute holds the bare number ("1") where the text
            # reads "Version 1"; prefer it, fall back to the digits in the text.
            raw = field.attr("title") or (match.group("n") or "")
            if raw.isdigit():
                version = int(raw)
                continue
        leftovers.append(field)

    source = ""
    for field in leftovers:
        source = field.attr("title") or field.text.strip()
        if source:
            break

    return timestamp_text, version, source


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

    timestamp_text, version, source = "", None, ""
    metadata = scope.find(cls="metadata")
    if metadata is not None:
        timestamp_text, version, source = _classify_metadata(metadata)

    description = scope.find(cls="description")

    return StoryStub(
        id=parse_story_slug(scope),
        slug=slug.strip(),
        source=source or CNN_SOURCE,
        timestamp=parse_timestamp(timestamp_text),
        timestamp_text=timestamp_text,
        version=version,
        teaser=description.text.strip() if description is not None else "",
        content_type=parse_media_types(scope),
    )


ROW_CONTAINER = "storyLineItemWrapperBox"


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
