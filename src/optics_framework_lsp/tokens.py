# Semantic tokens: what each cell is, so a csv reads as the dsl it is rather than as
# rows of text. The column decides, exactly as it does for completion and references.

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from . import yaml_cursor
from .completion import PARAM_KINDS, PARAM_VALUES
from .keyword_catalog import Catalog, slug
from .parser import is_yaml
from .parser.ast import AST, Span
from .parser.csv_parser import filled_params, spans
from .positions import to_utf16
from .validation import VAR, declares_at, module_args

# Sent once in the registration; every token below is an index into this list.
LEGEND = [
    "keyword",  # the header row: the names that decide what the file is
    "class",  # a test case
    "function",  # a module, wherever it is named
    "method",  # a step that resolves to a framework keyword
    "variable",  # ${name}, and an element_name that defines one
    "string",  # a locator, a data file, an api identifier
    "enumMember",  # an error code, and a param with a documented set of values
    "operator",  # the ! that inverts a Condition
]
# The framework owns the keyword, not the project. Themes colour this apart from a
# module of the same shape, which they otherwise draw identically.
MODIFIERS = ["defaultLibrary"]
_INDEX = {name: i for i, name in enumerate(LEGEND)}
_LIBRARY = 1 << MODIFIERS.index("defaultLibrary")

_Token = tuple[int, int, str, int]


def _params(
    cell: str,
    start: int,
    param: int,
    step: str,
    catalog: Catalog,
    modules: set[str],
    count: int | None = None,
) -> Iterator[_Token]:
    """A param reads ${names}, binds one, runs a module, or holds a value.

    `count` is how many params the step was given, which decides a `Condition`'s
    parity. A csv streams one cell at a time and settles for the cells seen so far; a
    yaml step is read whole, so it can say.
    """
    if found := list(VAR.finditer(cell)):
        for match in found:
            yield start + match.start(), len(match.group()), "variable", 0
        return

    given = count if count is not None else param + 1

    # A documented set of values, found by what the framework calls the param.
    names = catalog[step].params if step in catalog else []
    fixed = PARAM_VALUES.get(names[param] if param < len(names) else "", ())

    # `Run Loop` counts its params as name/iterable pairs, but its count form writes a
    # number where a name would go, and a number binds nothing.
    if param in declares_at(step, given) and not cell.replace(".", "", 1).isdigit():
        # `Read Data` and friends bind this name, so it reads like the ${uses} of it.
        yield start, len(cell), "variable", 0
    elif param in module_args(step, given) or cell.removeprefix("!") in modules:
        # `Condition` writes an inverted module as `!Name`, and the runner strips it.
        if cell.startswith("!"):
            yield start, 1, "operator", 0
            start, cell = start + 1, cell[1:]
        yield start, len(cell), "function", 0
    elif PARAM_KINDS.get(step, {}).get(param) in ("file", "api"):
        yield start, len(cell), "string", 0
    elif cell in fixed:
        yield start, len(cell), "enumMember", 0


def _row(
    fields: list[str], places: list[tuple[int, int]], headers: list[str],
    catalog: Catalog, modules: set[str],
) -> Iterator[_Token]:
    step_at = headers.index("module_step") if "module_step" in headers else None
    step = slug(fields[step_at]) if step_at is not None and step_at < len(fields) else ""
    params = filled_params(fields, headers)

    for column, (start, end) in enumerate(places):
        cell = fields[column] if column < len(fields) else ""
        header = headers[column] if column < len(headers) else ""
        if not cell:
            continue

        if header in ("test_case", "module_name"):
            yield start, end - start, "class" if header == "test_case" else "function", 0
        elif header == "test_step":
            yield start, end - start, "function", 0
        elif column == step_at:
            # A keyword wins over a same-named module, as `_execute_single_keyword` does.
            known = step in catalog
            yield start, end - start, "method" if known else "function", _LIBRARY * known
        elif header == "element_name":
            yield start, end - start, "variable", 0
        elif header.startswith("element_id") or header == "match_string":
            yield start, end - start, "string", 0
        elif header == "error_code":
            yield start, end - start, "enumMember", 0
        elif column in params:
            yield from _params(cell, start, params.index(column), step, catalog, modules)


def _encode(found: list[tuple[int, int, int, str, int]], lines: list[str]) -> list[int]:
    """Five ints per token, each positioned relative to the one before. Sorted first,
    because the protocol's deltas only make sense in reading order.

    Both the offset and the length are utf-16 units on the wire, so the conversion has
    to happen here rather than after the deltas are taken.
    """
    data: list[int] = []
    last_line = last_start = 0
    for number, start, length, kind, mods in sorted(found, key=lambda at: at[:2]):
        row = lines[number] if number < len(lines) else ""
        start, length = (
            to_utf16(row, start),
            to_utf16(row, start + length) - to_utf16(row, start),
        )
        first = start if number != last_line else start - last_start
        data += [number - last_line, first, length, _INDEX[kind], mods]
        last_line, last_start = number, start
    return data


def _at(row: int, span: Span, kind: str, mods: int = 0):
    """A token from a span the parser recorded. Rows are 1-based in the ast."""
    return row - 1, span[0], span[1] - span[0], kind, mods


def _yaml(text: str, ast: AST, uri: str, catalog: Catalog) -> list[int]:
    """One yaml file, from the spans the parser kept as it read it.

    Nothing here re-scans the text. A csv has to, because a cell's meaning comes from
    the column it is in; a yaml step is one scalar that the reader itself split, and the
    parser recorded where every piece of it landed.
    """
    modules = {block.name for block in ast.modules}
    found: list[tuple[int, int, int, str, int]] = []

    # The section keys, which are what decides the file's kind — the role a csv's header
    # row plays, and coloured the same way.
    for at, key in yaml_cursor.sections(text.splitlines()):
        found.append((at, 0, len(key), "keyword", 0))

    for blocks, kind in ((ast.test_cases, "class"), (ast.modules, "function")):
        for block in blocks:
            if block.uri != uri:
                continue
            if block.name_span:
                found.append(_at(block.start_row, block.name_span, kind))

            for step in block.steps:
                if kind == "class":
                    # A test case's steps are module names, never keywords.
                    if step.name_span:
                        found.append(_at(step.row, step.name_span, "function"))
                    continue

                name = slug(step.step_name)
                known = name in catalog
                if step.name_span:
                    # A keyword wins over a same-named module, as
                    # `_execute_single_keyword` does.
                    found.append(
                        _at(
                            step.row,
                            step.name_span,
                            "method" if known else "function",
                            _LIBRARY * known,
                        )
                    )

                for i, span in enumerate(step.param_spans):
                    found += [
                        (step.row - 1, *token)
                        for token in _params(
                            step.params[i], span[0], i, name, catalog, modules,
                            count=len(step.params),
                        )
                    ]

    for element in ast.elements:
        if element.uri != uri:
            continue
        if element.name_span:
            found.append(_at(element.row, element.name_span, "variable"))
        for locator in element.locators:
            found.append(
                _at(locator.row, (locator.start, locator.end), "string")
            )

    return _encode(found, text.splitlines())


def tokens(
    text: str, ast: AST, catalog: Catalog | None, *, uri: str = ""
) -> list[int]:
    """The whole document, encoded as the protocol wants it: five ints per token, each
    positioned relative to the one before."""
    if is_yaml(uri):
        return _yaml(text, ast, uri, catalog or {})

    lines = text.splitlines()
    header_line = next((i for i, line in enumerate(lines) if line.strip()), None)
    if header_line is None:
        return []

    headers = [h.strip().lower() for h in next(csv.reader(io.StringIO(lines[header_line])), [])]
    modules = {block.name for block in ast.modules}

    found: list[tuple[int, int, int, str, int]] = []
    for number, line in enumerate(lines):
        if not line.strip():
            continue

        places = spans(line)
        if number == header_line:
            found += [(number, a, b - a, "keyword", 0) for a, b in places if line[a:b]]
            continue

        fields = [f.strip() for f in next(csv.reader(io.StringIO(line)), [])]
        for start, length, kind, mods in _row(fields, places, headers, catalog or {}, modules):
            found.append((number, start, length, kind, mods))

    return _encode(found, lines)
