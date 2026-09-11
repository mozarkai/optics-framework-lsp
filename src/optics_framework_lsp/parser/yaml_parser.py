# File kind comes from top-level keys, not filename
#
# Mirrors `optics_framework/common/runner/data_reader.py`'s `YAMLDataReader`, which is
# what `optics execute` and `optics dry_run` use. `optics generate` ships a second,
# more permissive yaml reader of its own; it is deliberately not followed here, because
# the runner is what decides whether a suite actually runs.
#
# `yaml.compose` rather than `yaml.safe_load`: a composed node carries `start_mark` and
# `end_mark`, and without them every row number and every rename span would be a guess.

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypeGuard

import yaml

from ..keyword_catalog import CATALOG, slug
from .ast import AST, Block, Element, IssueKind, Locator, SourceIssue, Span, Step

# The keys the reader looks up, spelt exactly as it spells them. Public: `validation`
# needs them to say which key a misspelt one should have been. `read_test_cases` does
# `data.get("Test Cases")`, so nothing else loads — however the file was classified.
SECTIONS = {"test_cases": "Test Cases", "modules": "Modules", "elements": "Elements"}

# `_parse_module_step`'s own pattern. Narrower than `validation.VAR`, which is about
# what the runner substitutes rather than about where a step splits.
_VAR = re.compile(r"\$\{[^{}]+\}")

# A step has to be a string. `read_test_cases` does `step.strip()` and
# `_parse_module_step` the same, so anything else raises an uncaught `AttributeError`
# and the whole load dies before a single keyword runs.
_STR = "tag:yaml.org,2002:str"

# What a normalised top-level key classifies the file as, as `_identify_yaml_content`
# matches them. Deliberately looser than `SECTIONS`: that gap is a diagnostic.
CLASSIFY = {
    "test cases": "test_cases",
    "test_cases": "test_cases",
    "test-cases": "test_cases",
    "testcases": "test_cases",
    "modules": "modules",
    "elements": "elements",
    "api": "api",
    "apis": "api",
}

# Error definitions have no yaml reader at all: `_load_error_definitions` hardcodes the
# csv one. Recognised only so we can say so.
_ERRORS = {"error definitions", "error_definitions", "error-definitions"}


def _issue(
    issues: list[SourceIssue],
    uri: str,
    node: yaml.Node,
    kind: IssueKind,
    detail: str = "",
) -> None:
    """One misshapen thing, against the line it starts on."""
    issues.append(SourceIssue(uri=uri, row=_row(node), kind=kind, detail=detail))


def _row(node: yaml.Node) -> int:
    """The 1-based line a node starts on, as the rest of the ast counts rows."""
    return node.start_mark.line + 1


def _span(node: yaml.Node) -> Span | None:
    """Where a scalar sits on its line. Nothing for a scalar spanning several lines: a
    folded or block scalar has no contiguous run of source matching its value, so an
    edit cannot be placed inside it."""
    if node.start_mark.line != node.end_mark.line:
        return None
    return node.start_mark.column, node.end_mark.column


def _pairs(node: yaml.Node) -> list[tuple[yaml.ScalarNode, yaml.Node]]:
    """A mapping's entries, dropping any whose key is not a plain scalar. A complex key
    is not something the reader could look up by name either."""
    if not isinstance(node, yaml.MappingNode):
        return []
    return [(k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]


def _text(node: yaml.Node) -> str:
    """A scalar as the reader sees it, which is always `str(value).strip()`."""
    return str(node.value).strip()


def _origin(node: yaml.ScalarNode) -> int | None:
    """The column the scalar's own text starts at, when the source is a faithful run of
    its value. Nothing when it is not — a block scalar spans lines and an escaped one is
    shorter in source than in value, so no offset inside it can be trusted."""
    span = _span(node)
    if span is None:
        return None

    quote = 1 if node.style in ("'", '"') else 0
    start, end = span[0] + quote, span[1] - quote
    return start if end - start == len(str(node.value)) else None


def _inner(node: yaml.ScalarNode):
    """A mapping from an index into the stripped text to a span in the source, or
    nothing when the scalar cannot be indexed into."""
    origin = _origin(node)
    raw = str(node.value)
    lead = len(raw) - len(raw.lstrip())

    def at(start: int, end: int) -> Span | None:
        if origin is None:
            return None
        return origin + lead + start, origin + lead + end

    return raw.strip(), at


def _string(
    node: yaml.Node, uri: str, issues: list[SourceIssue]
) -> TypeGuard[yaml.ScalarNode]:
    if isinstance(node, yaml.ScalarNode) and node.tag == _STR:
        return True
    _issue(issues, uri, node, "yaml-step-not-a-string")
    return False


def _test_step(node: yaml.Node, uri: str, issues: list[SourceIssue]) -> Step | None:
    """A test step names a module, and nothing more: `read_test_cases` only strips it."""
    if not _string(node, uri, issues):
        return None

    text, at = _inner(node)
    if not text:
        return None
    return Step(step_name=text, row=_row(node), name_span=at(0, len(text)))


# A quoted run holds together, so a value written entirely in quotes can carry a space. The
# quotes inside a locator (`//button[@id="save"]`) are not at the start of the value, so they
# stay; `_unwrap` gives up only the ones wrapping a value whole.
_TOKEN = re.compile(r"""(?:[^\s"']|"[^"]*"|'[^']*')+""")
_WRAPPED = re.compile(r"""^(?P<q>["'])(?P<body>.*)(?P=q)$""", re.S)


def _unbalanced(text: str) -> bool:
    """Whether the token pattern would skip a non-whitespace character, which only an
    unpaired quote makes it do. Counting each quote character instead reads the apostrophe
    in `text="Bob's file"` as an unpaired one and splits a value the reader keeps whole."""
    gap = 0
    for match in _TOKEN.finditer(text):
        if text[gap : match.start()].strip():
            return True
        gap = match.end()
    return bool(text[gap:].strip())


def tokens(text: str) -> list[re.Match]:
    """A step's whitespace-separated tokens, as the reader splits them — quoted runs whole. An
    unbalanced quote falls back to plain whitespace, which is what the reader does too."""
    if _unbalanced(text):
        return list(re.finditer(r"\S+", text))
    return list(_TOKEN.finditer(text))


def unwrap(token: str) -> str:
    """The value the runner sees: a value written entirely in quotes without them."""
    key, sep, value = token.partition("=")
    found = _WRAPPED.match(value if sep else token)
    if not found:
        return token
    return f"{key}={found['body']}" if sep else found["body"]


def _split(
    text: str, words: list[re.Match], modules: frozenset[str]
) -> tuple[int, int] | None:
    """Where the keyword name ends, as `_parse_module_step` decides it: the longest run of
    leading words the catalog names, else the first `${...}`. Returned as (end of the
    keyword, start of the params) — the two differ when a `${...}` is preceded by spaces.

    A name the project defines as a module is that module and nothing is split off it, or
    a module called `Sleep Well` would be read as `Sleep` with a param. Matched on the
    slug, which is how the reader matches it: `sleep well` names `Sleep Well` too.

    The catalog answers next because a keyword whose first param is a plain value has no
    `${...}` to split on; `Sleep 5` used to be read as one keyword named `sleep 5`."""
    if slug(text) in modules:
        return None

    for count in range(len(words), 0, -1):
        name = text[words[0].start() : words[count - 1].end()]
        if CATALOG.get(slug(name)) is not None:
            after = words[count].start() if count < len(words) else len(text)
            return words[count - 1].end(), after

    found = _VAR.search(text)
    return (found.start(), found.start()) if found else None


def _module_step(
    node: yaml.Node,
    uri: str,
    issues: list[SourceIssue],
    modules: frozenset[str] = frozenset(),
) -> Step | None:
    """A module step, split as `_parse_module_step` splits it: a keyword name and its
    whitespace-separated params."""
    if not _string(node, uri, issues):
        return None

    row = _row(node)
    text, at = _inner(node)
    if not text:
        return None

    words = tokens(text)
    split = _split(text, words, modules)
    if split is None:
        # Neither the catalog nor a `${...}` claims any of it, so the reader takes the
        # whole string as the keyword — which is how a step naming another module
        # reaches the runner. `_unknown_steps` says so when nothing answers to it.
        return Step(step_name=text, row=row, name_span=at(0, len(text)))

    end, start = split
    keyword = text[:end].strip()
    if not keyword:
        # `_process_module_steps` drops a step whose keyword came out empty.
        return None

    # The span covers the quotes, the param does not: an editor should select what was
    # written, while the step carries what the runner will be given.
    params = tokens(text[start:])
    return Step(
        step_name=keyword,
        row=row,
        params=[unwrap(m.group()) for m in params],
        name_span=at(0, len(keyword)),
        # All or nothing: `at` answers for every index or for none, so this drops
        # every param's span together rather than misaligning them with `params`.
        param_spans=[
            span
            for m in params
            if (span := at(start + m.start(), start + m.end())) is not None
        ],
        raw=text,
    )


def _blocks(section: str, node: yaml.Node, uri: str, issues: list[SourceIssue], step):
    """A `Test Cases` or `Modules` section: a list of single-key mappings, each naming a
    block and listing its steps.

    A mapping here instead of a list is what `optics generate`'s reader accepts and the
    runner's does not — `for item in data: item.items()` iterates the mapping's string
    keys and raises, taking the whole load down with it."""
    if not isinstance(node, yaml.SequenceNode):
        _issue(issues, uri, node, "yaml-section-shape", section)
        return []

    blocks: dict[str, Block] = {}
    for item in node.value:
        if not isinstance(item, yaml.MappingNode):
            _issue(issues, uri, item, "yaml-section-shape", section)
            continue

        for key, steps in _pairs(item):
            name = _text(key)
            # `if not name or not steps: continue` — an unnamed or empty block is
            # warned about and skipped, contributing nothing either way.
            if not name or not isinstance(steps, yaml.SequenceNode):
                continue

            if name not in blocks:
                blocks[name] = Block(
                    name=name, uri=uri, start_row=_row(key), name_span=_span(key)
                )
            blocks[name].steps.extend(
                found for value in steps.value if (found := step(value, uri, issues))
            )

    return list(blocks.values())


def _elements(node: yaml.Node, uri: str, issues: list[SourceIssue]) -> list[Element]:
    """An `Elements` section: a mapping of name to one locator or to a list of them,
    which `resolve_with_fallback` tries in order."""
    if not isinstance(node, yaml.MappingNode):
        _issue(issues, uri, node, "yaml-section-shape", "Elements")
        return []

    found: list[Element] = []
    for key, value in _pairs(node):
        name = _text(key)
        if not name:
            continue

        values = value.value if isinstance(value, yaml.SequenceNode) else [value]
        locators = [
            Locator(_text(v), *(_span(v) or (0, 0)), row=_row(v))
            for v in values
            if isinstance(v, yaml.ScalarNode) and _text(v)
        ]
        # `if name and values` — a name with nothing under it is dropped.
        if locators:
            found.append(
                Element(
                    name=name,
                    locators=locators,
                    uri=uri,
                    row=_row(key),
                    name_span=_span(key),
                )
            )

    return found


def _config(keys: set[str]) -> bool:
    """As `_is_config_file` decides it, on the keys as written rather than normalised.
    Not by filename: the runner never looks at one."""
    return "driver_sources" in keys and bool(
        keys & {"element_sources", "elements_sources"}
    )


def _problem(error: yaml.YAMLError) -> tuple[int, str]:
    """Where the parser gave up, and what it said. A `MarkedYAMLError` knows the line;
    anything else is reported against the first."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error).splitlines()[0]
    return (mark.line + 1 if mark else 1), problem


def _compose(ast: AST, uri: str, content: str) -> yaml.Node | None:
    try:
        return yaml.compose(content)
    except yaml.YAMLError as error:
        # `read_file` logs this and returns `{}`, so every section loads empty and the
        # run fails later on something unrelated — usually "no test cases to run".
        row, problem = _problem(error)
        ast.issues.append(
            SourceIssue(uri=uri, row=row, kind="yaml-parse-error", detail=problem)
        )
        return None


def _module_names(root: yaml.Node | None) -> Iterable[str]:
    """Every module a file defines, from the keys alone. `_load_modules` gathers these
    across the project before a single step is parsed, so a step naming one is read as
    that module rather than as the keyword its leading words happen to spell."""
    if root is None:
        return
    for key, value in _pairs(root):
        # `read_module_names` does `data.get("Modules")`, so a mis-cased key holds no
        # names — the same gap that makes its section read as nothing.
        if _text(key) != SECTIONS["modules"] or not isinstance(
            value, yaml.SequenceNode
        ):
            continue
        for item in value.value:
            for name, _ in _pairs(item):
                if text := _text(name):
                    yield text


def _parse(ast: AST, uri: str, root: yaml.Node, modules: frozenset[str]) -> None:
    if not isinstance(root, yaml.MappingNode):
        return

    pairs = _pairs(root)
    kinds: list[str] = []

    for key, value in pairs:
        name = _text(key)
        normalised = name.lower()

        if normalised in _ERRORS:
            # There is no yaml reader for these at all: `_load_error_definitions`
            # hardcodes the csv one, so the section is never even looked at.
            _issue(ast.issues, uri, key, "yaml-error-definitions-unread", name)
            continue

        kind = CLASSIFY.get(normalised)
        if kind is None:
            continue
        if kind not in kinds:
            kinds.append(kind)

        # Classification normalises case; the reader does not. A key that classifies
        # but is not spelt exactly is found by discovery and then read as nothing.
        if kind in SECTIONS and name != SECTIONS[kind]:
            _issue(ast.issues, uri, key, "yaml-section-key-case", name)
            continue

        if kind == "test_cases":
            ast.test_cases += _blocks("Test Cases", value, uri, ast.issues, _test_step)
        elif kind == "modules":
            ast.modules += _blocks(
                "Modules",
                value,
                uri,
                ast.issues,
                lambda node, at, issues: _module_step(node, at, issues, modules),
            )
        elif kind == "elements":
            ast.elements += _elements(value, uri, ast.issues)

    if _config({_text(key) for key, _ in pairs}):
        kinds.append("config")

    if kinds:
        ast.kinds[uri] = ",".join(kinds)


def parse_yaml_sources(files: Iterable[tuple[str, str]]) -> AST:
    ast = AST()
    # Composed first and read second, because a step splits against the module names of
    # every file, not just its own — and composing twice would double the parse errors.
    composed = [(uri, _compose(ast, uri, content)) for uri, content in files]
    modules = frozenset(
        slug(name) for _, root in composed for name in _module_names(root)
    )
    for uri, root in composed:
        if root is not None:
            _parse(ast, uri, root, modules)
    return ast
