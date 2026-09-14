# Where a position falls in a yaml suite: its section, its depth, and the word it is on.
#
# The text is scanned rather than parsed. Completion has to answer on a half-written
# line and in an empty file, neither of which a parser accepts, so this cannot be built
# from the ast the way rename's targets are.
#
# Two answers come out of one scan, because two different questions are asked of it.
# Completion wants what is being *typed*, which is the text up to the cursor. Hover,
# goto and rename want the whole word the cursor is *in*. `partial` is the first,
# `word` the second.

from __future__ import annotations

import re
from dataclasses import dataclass

from lsprotocol.types import Position, Range, TextEdit

from .keyword_catalog import Catalog, slots, slug
from .parser.yaml_parser import CLASSIFY, tokens as step_tokens
from .positions import from_utf16, to_utf16

# A sequence item and a mapping key. Matched against a partial line too, so both have
# to tolerate one that stops mid-word.
_ITEM = re.compile(r"^(\s*)-(\s*)(.*)$")
_KEY = re.compile(r"^(\s*)(\S[^:]*?)\s*:(.*)$")
# Tokenising matches the reader's: a quoted value is one word, so a cursor inside `text="a b"`
# is inside one param rather than two. See `yaml_parser.tokens`.


@dataclass(slots=True)
class YamlCursor:
    """What belongs where the cursor is, and what is already there."""

    # The enclosing section, classified as `_identify_yaml_content` classifies it, or
    # nothing at the top level.
    section: str | None
    # "top" a section key, "name" a test case, module or element name, "step" a step,
    # "locator" an element's id.
    place: str
    # What is typed so far, and the whole word it belongs to.
    partial: str
    word: str
    line: int
    start: int
    paired: bool
    # The line's own text, which is what turns a code-point offset back into the utf-16
    # column a client counts in.
    source: str
    # The keyword the step names, slugged, and which of its params the cursor is on.
    # `-1` while the cursor is still inside the name — which is where it stays for a
    # step naming a module rather than a keyword, since a module call takes no params.
    step_name: str = ""
    param: int = -1
    # How many params the step was given, which `declares_at` and `runs_at` need to work
    # out what a slot holds: a `Condition` alternates by parity.
    params: int = 0

    def replacement(self, text: str) -> TextEdit:
        """Replace what is being typed, so `${b}` completes without nesting into
        `${${b}}` and a half-typed multi-word keyword is replaced whole."""
        end = self.start + len(self.partial) + (self.paired and text.endswith("}"))
        return TextEdit(
            range=Range(
                start=Position(
                    line=self.line, character=to_utf16(self.source, self.start)
                ),
                end=Position(line=self.line, character=to_utf16(self.source, end)),
            ),
            new_text=text,
        )


def sections(lines: list[str]):
    """Every top-level key, with the line it sits on. Public: completion offers the
    sections a file does not have yet.

    Comments are skipped, or a `# NOTE: ...` at the left margin reads as a key and
    every line below it loses the section it is really in.
    """
    for at, line in enumerate(lines):
        found = _KEY.match(line)
        if found and not found.group(1) and not line.lstrip().startswith("#"):
            yield at, found.group(2)


def _section_at(lines: list[str], row: int) -> tuple[int, str | None]:
    """The section the row falls in, as its line and what it classifies as."""
    where, kind = -1, None
    for at, key in sections(lines):
        if at >= row:
            break
        where, kind = at, CLASSIFY.get(key.strip().lower())
    return where, kind


def _content(line: str, indent: int) -> tuple[int, str]:
    """Where a line's value starts and what the value is. A `- ` is part of the syntax,
    not of the value."""
    item = _ITEM.match(line)
    if item is None:
        return indent, line[indent:]
    return len(item.group(1)) + 1 + len(item.group(2)), item.group(3)


def _name_indent(lines: list[str], section: int, row: int) -> int | None:
    """How far in the nearest block name above the cursor sits, which is what tells a
    step from another name: steps are the only thing nested under one."""
    for at in range(row - 1, section, -1):
        found = _ITEM.match(lines[at])
        if found and found.group(3).rstrip().endswith(":"):
            return len(found.group(1))
    return None


def _keyword(words: list[str], catalog: Catalog | None) -> tuple[int, str]:
    """How many leading words name the keyword, and its slug.

    The same rule `_parse_module_step` applies, and for the same reason: a keyword whose
    first param is a plain value has no `${...}` to anchor on, and neither does a cursor
    sitting just after `Press Element `.

    With no run the catalog knows, every word is part of the name — which is also what
    the reader does with a name it cannot claim, so that a step calling another module
    reaches it whole.
    """
    for take in range(len(words), 0, -1):
        name = slug(" ".join(words[:take]))
        if name in (catalog or {}):
            return take, name
    return len(words), ""


# What `_step` works out: partial, word, start, step_name, param, params.
_Step = tuple[str, str, int, str, int, int]


def _step(
    content_start: int, content: str, character: int, catalog: Catalog | None
) -> _Step:
    """The word the cursor is in and the word being typed, and which param each is."""
    words = [(found.start(), found.group()) for found in step_tokens(content)]
    at = character - content_start

    if not words:
        # Nothing written yet, so the step is still its own name.
        return "", "", content_start, "", -1, 0

    # The word the cursor sits in or ends, else the count of the words behind it.
    index = len(words)
    for i, (offset, word) in enumerate(words):
        if offset <= at <= offset + len(word):
            index = i
            break

    take, name = _keyword([word for _, word in words], catalog)
    rest = max(len(words) - take, 0)
    if index < take:
        # Inside the name. Offered and replaced whole, because a keyword is several
        # words and a client filters on what it was given.
        joined = " ".join(word for _, word in words[:take])
        return content[: max(at, 0)], joined, content_start, name, -1, rest

    offset, word = words[index] if index < len(words) else (at, "")
    # By name where one is written, and only the value is typed: `element="${b}"` is one token.
    bound = slots(name, [w for _, w in words[take:]], catalog)
    slot, value = bound[index - take] if index - take < len(bound) else (index - take, word)
    inner = len(word) - len(value) + (value[:1] in ('"', "'"))
    typed = at - offset - inner
    if typed < 0:
        # Still in the `name=` itself, which is not a value: answer as if it were one word.
        inner, typed = 0, max(at - offset, 0)
    value = word[inner:]
    if inner and (quote := word[inner - 1]) in "\"'" and value.endswith(quote):
        value = value[:-1]
    return (
        value[:typed],
        value,
        content_start + offset + inner,
        name,
        max(slot, 0),
        rest,
    )


def cursor(text: str, position: Position, catalog: Catalog | None = None) -> YamlCursor:
    lines = text.splitlines()
    line = lines[position.line] if position.line < len(lines) else ""
    # The client counted the column in utf-16; everything below slices `str`.
    character = from_utf16(line, position.character)
    prefix = line[:character]
    indent = len(prefix) - len(prefix.lstrip())

    def at(place: str, start: int, partial: str, word: str, section: str | None = None):
        return YamlCursor(
            section=section,
            place=place,
            partial=partial,
            word=word,
            line=position.line,
            start=start,
            paired=line[character:].startswith("}"),
            source=line,
        )

    # A key of its own at the left margin: a section, or the first thing in a new file.
    if indent == 0 and not prefix.lstrip().startswith("-"):
        return at("top", 0, prefix.strip(), line.strip())

    where, section = _section_at(lines, position.line)
    content_start, content = _content(line, indent)
    typed = prefix[content_start:] if character > content_start else ""

    if section == "elements":
        # A locator either follows the name's colon or is an item under it.
        if _ITEM.match(line) is None and (found := _KEY.match(line)) is not None:
            value = found.group(3)
            begins = len(line) - len(value.lstrip())
            if character < begins:
                return at("name", content_start, typed, found.group(2), section)
            return at(
                "locator", begins, line[begins:character], value.strip(), section
            )

        place = "locator" if _ITEM.match(line) else "name"
        return at(place, content_start, typed, content.strip(), section)

    name_indent = _name_indent(lines, where, position.line)
    if name_indent is None or indent <= name_indent:
        # Nothing is nested here yet, so this is a block name being written.
        bare = content.strip().removesuffix(":")
        return at("name", content_start, typed.removesuffix(":"), bare, section)

    found = at("step", content_start, typed, content.strip(), section)
    (
        found.partial,
        found.word,
        found.start,
        found.step_name,
        found.param,
        found.params,
    ) = _step(content_start, content, character, catalog)
    return found
