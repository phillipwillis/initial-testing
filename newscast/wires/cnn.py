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

**Unverified.** The fixture behind the tests was reconstructed from screenshots
of the DOM inspector, not saved from the live site. It pins down the parsing
logic; it does not prove the markup. Replace it with a real saved page as soon
as one exists — the tests will say what this got wrong.
"""

from __future__ import annotations

import re
from typing import Optional

from newscast.wires.dom import Node, parse_html
from newscast.wires.stub import ContentType, StoryStub, parse_timestamp

CNN_SOURCE = "CNN Newsource"
LANDING_URL = "https://newsource.ns.cnn.com/landing"

_VERSION_RE = re.compile(r"^\s*version\b\s*(?P<n>\d+)?", re.I)

# The Media icons have not been inspected yet, so this maps whatever accessible
# text they expose. Anything unrecognised is reported as UNKNOWN rather than
# guessed at.
_MEDIA_WORDS = {
    "script": ContentType.SCRIPT,
    "document": ContentType.SCRIPT,
    "text": ContentType.SCRIPT,
    "video": ContentType.VIDEO,
    "play": ContentType.VIDEO,
    "image": ContentType.IMAGE,
    "photo": ContentType.IMAGE,
    "picture": ContentType.IMAGE,
}


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

    UNVERIFIED — the icon markup has not been inspected. Reads whatever
    accessible text the icons expose and reports UNKNOWN when it recognises
    nothing, so a wrong guess shows up as missing data rather than as a
    plausible lie.
    """
    found: list[ContentType] = []
    for node in scope.walk():
        hints = " ".join(
            [
                node.attr("title"),
                node.attr("alt"),
                node.attr("aria-label"),
                node.attr("data-testid"),
            ]
        ).lower()
        if not hints.strip():
            continue
        for word, kind in _MEDIA_WORDS.items():
            if word in hints and kind not in found:
                found.append(kind)
    return tuple(found)


def parse_row(scope: Node) -> Optional[StoryStub]:
    """Parse one listing row. None if it carries no headline."""
    title = scope.find(cls="title")
    if title is None:
        return None

    # The title attribute holds the full headline; the visible text may be
    # truncated by MuiTypography-noWrap.
    slug = title.attr("title") or title.text

    timestamp_text, version, source = "", None, ""
    metadata = scope.find(cls="metadata")
    if metadata is not None:
        timestamp_text, version, source = _classify_metadata(metadata)

    description = scope.find(cls="description")

    return StoryStub(
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
