"""The xpath optics itself writes for an element, ported from its Appium helper so a suggestion matches
what optics would generate: a unique attribute if there is one, the path from the nearest unique parent if not."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from itertools import combinations

UNIQUE = ("name", "content-desc", "id", "resource-id", "accessibility-id")
MAYBE = ("label", "text", "value")


def literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    parts = value.split('"')
    pieces = [f'"{part}"' if i == len(parts) - 1 else f"\"{part}\", '\"'" for i, part in enumerate(parts)]
    return "concat(" + ", ".join(pieces) + ")"


class Xpaths:
    def __init__(self, root: ET.Element) -> None:
        self._parent = {child: node for node in root.iter() for child in node}
        self._by_tag: dict[str, list[ET.Element]] = defaultdict(list)
        self._by_attr: dict[tuple[str, str, str], list[ET.Element]] = defaultdict(list)
        for node in root.iter():
            self._by_tag[node.tag].append(node)
            for attr in (*UNIQUE, *MAYBE):
                if node.get(attr):
                    self._by_attr[(node.tag, attr, node.get(attr))].append(node)
        self._memo: dict[ET.Element, str] = {}

    def _matches(self, tag: str, conditions: tuple[tuple[str, str], ...]) -> list[ET.Element]:
        if not conditions:
            return self._by_tag[tag]
        shortest = min((self._by_attr[(tag, attr, value)] for attr, value in conditions), key=len)
        return [n for n in shortest if all(n.get(attr) == value for attr, value in conditions)]

    def _probe(self, node: ET.Element, entries: list[tuple[str, ...]]) -> tuple[str | None, bool]:
        semi = None
        for entry in entries:
            conditions = tuple((attr, node.get(attr)) for attr in entry)
            if not all(value for _, value in conditions):
                continue
            probe = f"//{node.tag}[" + " and ".join(f"@{attr}={literal(value)}" for attr, value in conditions) + "]"
            found = self._matches(node.tag, conditions)
            if len(found) == 1:
                return probe, True
            if semi is None and found:
                semi = f"({probe})[{found.index(node) + 1}]"
        return semi, False

    def _unique(self, node: ET.Element) -> str | None:
        singles = lambda attrs: [(attr,) for attr in attrs]  # noqa: E731
        semi = None
        for entries in (singles(UNIQUE), list(combinations((*UNIQUE, *MAYBE), 2)), singles(MAYBE), []):
            if entries:
                xpath, unique = self._probe(node, entries)
            elif len(self._by_tag[node.tag]) == 1:
                xpath, unique = (f"//{node.tag}" if node in self._parent else f"/{node.tag}"), True
            else:
                xpath, unique = None, False
            if unique and xpath:
                return xpath
            semi = semi or xpath
        return semi

    def of(self, node: ET.Element) -> str:
        if node not in self._memo:
            self._memo[node] = self._unique(node) or self._hierarchical(node)
        return self._memo[node]

    def _hierarchical(self, node: ET.Element) -> str:
        parent = self._parent.get(node)
        if parent is None:
            return f"/{node.tag}"
        twins = [c for c in parent if c.tag == node.tag]
        step = f"/{node.tag}" + (f"[{twins.index(node) + 1}]" if len(twins) > 1 else "")
        return self.of(parent) + step
