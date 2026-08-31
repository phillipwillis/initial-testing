"""A very small HTML tree, built on the standard library.

Selenium can query the live DOM perfectly well. This exists so the *parsing*
does not need Selenium: the collector hands over `driver.page_source` and
everything downstream runs against a string, in a test, on any machine
(CLAUDE.md §14).

Deliberately not a general-purpose library. It supports finding elements by
class name and reading attributes and text, which is all the wire parsers need,
and it avoids adding a dependency that would have to earn its way onto a
locked-down work machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterator, Optional

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    parent: Optional["Node"] = field(default=None, repr=False, compare=False)
    _text: str = ""

    # -- attributes ---------------------------------------------------------

    def attr(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def has_class(self, name: str) -> bool:
        return name in self.classes

    # -- text ---------------------------------------------------------------

    @property
    def text(self) -> str:
        """All text in this subtree, whitespace-collapsed."""
        parts: list[str] = []
        if self._text:
            parts.append(self._text)
        for child in self.children:
            child_text = child.text
            if child_text:
                parts.append(child_text)
        return " ".join(" ".join(parts).split())

    # -- traversal ----------------------------------------------------------

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find_all(
        self, cls: str | None = None, tag: str | None = None
    ) -> list["Node"]:
        """Descendants matching a class name and/or a tag."""
        return [
            n
            for n in self.walk()
            if n is not self
            and (cls is None or n.has_class(cls))
            and (tag is None or n.tag == tag)
        ]

    def find(self, cls: str | None = None, tag: str | None = None) -> Optional["Node"]:
        found = self.find_all(cls=cls, tag=tag)
        return found[0] if found else None

    def children_with_class(self, cls: str) -> list["Node"]:
        return [c for c in self.children if c.has_class(cls)]


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="#document")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs})
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs})
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        # Tolerate mismatched or unclosed tags: unwind to the nearest match,
        # and ignore a stray close entirely rather than corrupting the tree.
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        if data.strip():
            holder = Node(tag="#text", _text=data)
            holder.parent = self._stack[-1]
            self._stack[-1].children.append(holder)


def parse_html(html: str) -> Node:
    """Parse an HTML document or fragment into a Node tree."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root
