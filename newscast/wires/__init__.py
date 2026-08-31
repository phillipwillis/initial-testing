"""Wire collection (§6 phase 0, §8, build order §10.3).

The split that matters is in CLAUDE.md §14: Selenium navigates and
authenticates, and a pure function parses. Nothing in `dom.py`, `stub.py` or
`cnn.py` imports Selenium or touches the network, so the whole parsing layer is
testable against saved HTML.
"""

from newscast.wires.stub import StoryStub, ContentType
from newscast.wires.cnn import parse_listing, parse_row, CNN_SOURCE

__all__ = ["StoryStub", "ContentType", "parse_listing", "parse_row", "CNN_SOURCE"]
