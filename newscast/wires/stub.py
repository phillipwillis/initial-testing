"""The §6 phase 0 story stub.

Phase 0 captures stubs only — no full scripts. On CNN Newsource every field
below except `related_ids` is visible in the story list without opening
anything, which is what keeps the collection pass cheap across ~200 stories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ContentType(Enum):
    """What material the wire is offering, from the row's Media icons."""

    SCRIPT = "SCRIPT"      # wire copy exists to rewrite
    VIDEO = "VIDEO"        # playable video
    IMAGE = "IMAGE"        # stills only
    UNKNOWN = "UNKNOWN"


@dataclass
class StoryStub:
    """One item from the wire listing (§6).

    `version` is not in the §6 field list but is free on CNN Newsource and
    feeds §7 `freshness`: a story on Version 19 has been rewritten all morning,
    while Version 1 is new.
    """

    id: str = ""
    slug: str = ""
    source: str = ""
    content_type: tuple[ContentType, ...] = ()
    timestamp: Optional[datetime] = None
    timestamp_text: str = ""
    version: Optional[int] = None
    teaser: str = ""
    tags: list[str] = field(default_factory=list)
    related_ids: list[str] = field(default_factory=list)

    @property
    def has_script(self) -> bool:
        return ContentType.SCRIPT in self.content_type

    @property
    def has_video(self) -> bool:
        return ContentType.VIDEO in self.content_type

    @property
    def is_update(self) -> bool:
        """A story the wire has already revised at least once."""
        return bool(self.version and self.version > 1)


# "31 Aug 26 06:15 ET"  /  "31 AUG 26 06:15 ET"
_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\s+(?P<year>\d{2,4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<zone>[A-Z]{2,4})?\s*$"
)

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def parse_timestamp(text: str) -> Optional[datetime]:
    """Parse the wire's timestamp format, or None if it does not match.

    Returned naive, in the wire's own zone. The zone abbreviation is kept in
    `StoryStub.timestamp_text` rather than resolved: ET is ambiguous across
    daylight saving, and the show only ever compares these to each other.
    """
    m = _TIMESTAMP_RE.match(text or "")
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if not month:
        return None
    year = int(m.group("year"))
    if year < 100:
        year += 2000
    try:
        return datetime(
            year, month, int(m.group("day")), int(m.group("hour")), int(m.group("minute"))
        )
    except ValueError:
        return None
