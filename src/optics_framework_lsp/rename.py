# Renaming a name the project owns, across every file that writes it. The runner keys
# everything by name, so a rename that misses one cell silently changes what runs.

from __future__ import annotations

from collections.abc import Iterable, Iterator

from lsprotocol.types import Position, Range, TextEdit

from . import yaml_cursor
from .completion import Cursor, param_symbol, yaml_symbol_at
from .keyword_catalog import Catalog, slots, slug
from .parser import is_yaml
from .parser.ast import Span, Step
from .parser.csv_parser import filled_params, sheet, spans
from .parser.yaml_parser import parse_yaml_sources
from .positions import to_utf16
from .validation import VAR, declares_at, runs_at

_Place = tuple[str, int, int, int]

# What the project owns and so what may be moved. A keyword belongs to the framework,
# and an image, data file or api identifier names something outside the suite.
_OURS = ("module", "test case", "element", "error code")

# What a cell names, by the header above it. A `test_step` names a module, never a
# keyword: only a `module_step` can be either.
_BY_HEADER = {
    "test_case": "test case", "error_code": "error code", "element_name": "element",
    "module_name": "module", "test_step": "module",
}


def _symbol(cursor: Cursor, catalog: Catalog | None) -> tuple[str, str] | None:
    """The name under the cursor, and what kind of thing it is. Only what the project
    owns: a keyword is the framework's, and an image, data file or api identifier names
    something outside the csvs, so none of those ever come back from here."""
    field = cursor.field(cursor.column)
    if not field:
        return None

    step = cursor.column_of("module_step")
    header = cursor.header_at(cursor.column)
    if header in ("module_name", "test_step"):
        return "module", field
    if header == "test_case":
        return "test case", field
    if header == "element_name":
        return "element", field
    if header == "error_code":
        return "error code", field

    if step is None or cursor.column < step:
        return None
    if cursor.column == step:
        # A keyword is the framework's, so only a nested module call is renameable.
        return None if slug(field) in (catalog or {}) else ("module", field)

    # A data file or api identifier names something outside the csvs, so not ours.
    found = param_symbol(cursor, step)
    return found if found and found[0] in ("element", "module") else None


def _in_row(
    fields: list[str], places: list[tuple[int, int]], headers: list[str],
    catalog: Catalog, kind: str, name: str,
) -> Iterator[tuple[int, int]]:
    """Every span in one row that writes `name`, as the runner would read it."""
    step_at = headers.index("module_step") if "module_step" in headers else None
    step = fields[step_at] if step_at is not None and step_at < len(fields) else ""

    filled = filled_params(fields, headers)
    runs = runs_at(step, len(filled))
    binds = declares_at(step, len(filled))
    bound = slots(step, [fields[column] for column in filled], catalog)

    for column, (start, end) in enumerate(places):
        cell = fields[column] if column < len(fields) else ""
        header = headers[column] if column < len(headers) else ""
        if not cell:
            continue

        if _BY_HEADER.get(header) == kind and cell == name:
            yield start, end
        elif kind == "module" and column == step_at and cell == name:
            # A keyword of the same name wins, so that cell is not this module.
            if slug(cell) not in catalog:
                yield start, end
        elif column in filled:
            slot, value = bound[filled.index(column)]
            yield from _in_param(
                _value_start(cell, value, (start, end)), slot, value, runs, binds, kind, name
            )


def _value_start(cell: str, value: str, span: Span) -> int:
    """Where a param's value starts in its span: past the `name=`, inside the quote the
    span covers but the value does not. A csv cell is never quoted, so that term is 0."""
    return span[0] + len(cell) - len(value) + (span[1] - span[0] == len(cell) + 2)


def _in_param(
    at: int, param: int, value: str,
    runs: set[int], binds: set[int], kind: str, name: str,
) -> Iterator[tuple[int, int]]:
    if kind == "element":
        for match in VAR.finditer(value):
            if match.group(1) == name:
                # Only the name moves; the ${} around it stays put.
                yield at + match.start(1), at + match.end(1)
        if param in binds and value == name:
            yield at, at + len(value)
    elif kind == "module" and param in runs and value.removeprefix("!") == name:
        # The `!` of an inverted condition stays; only the name after it moves.
        yield at + len(value) - len(name), at + len(value)


def _in_yaml_params(
    uri: str, step: Step, catalog: Catalog | None, kind: str, name: str
) -> Iterator[_Place]:
    """`_in_param` over a step read whole, where a param's slot comes from its name."""
    runs = runs_at(step.step_name, len(step.params))
    binds = declares_at(step.step_name, len(step.params))
    bound = slots(step.step_name, step.params, catalog)

    for (slot, value), cell, span in zip(bound, step.params, step.param_spans):
        at = _value_start(cell, value, span)
        for start, end in _in_param(at, slot, value, runs, binds, kind, name):
            yield uri, step.row - 1, start, end


def _in_yaml(uri: str, text: str, catalog: Catalog, kind: str, name: str) -> Iterator[_Place]:
    """Every span in one yaml file that writes this name.

    Read from the ast rather than by scanning the text. A csv has to scan, because a
    cell's span is only recoverable from its line; a yaml step is one scalar that the
    reader itself split, and the parser recorded where each piece of it landed.
    """
    ast = parse_yaml_sources([(uri, text)])

    for block in ast.test_cases:
        if kind == "test case" and block.name == name and block.name_span:
            yield uri, block.start_row - 1, *block.name_span
        if kind == "module":
            for step in block.steps:
                # A test step names a module, never a keyword.
                if step.step_name == name and step.name_span:
                    yield uri, step.row - 1, *step.name_span

    for block in ast.modules:
        if kind == "module" and block.name == name and block.name_span:
            yield uri, block.start_row - 1, *block.name_span

        for step in block.steps:
            named = kind == "module" and step.step_name == name and step.name_span
            # A keyword of the same name wins, so that step is not this module.
            if named and slug(step.step_name) not in catalog and step.name_span:
                yield uri, step.row - 1, *step.name_span
            yield from _in_yaml_params(uri, step, catalog, kind, name)

    if kind == "element":
        for element in ast.elements:
            if element.name == name and element.name_span:
                yield uri, element.row - 1, *element.name_span


def places(sources: Iterable[tuple[str, str]], catalog: Catalog, kind: str, name: str) -> Iterator[_Place]:
    """Every cell in the project that writes this name, as uri, line, start, end.

    Dispatched per source, not per call: the runner keys by name and picks a reader per
    file, so one rename can span both formats.
    """
    for uri, text in sources:
        if is_yaml(uri):
            yield from _in_yaml(uri, text, catalog, kind, name)
            continue

        headers, body = sheet(text)
        lines = text.splitlines()
        for number, fields in body:
            for start, end in _in_row(fields, spans(lines[number]), headers, catalog, kind, name):
                yield uri, number, start, end


def _symbol_at(text: str, position: Position, catalog: Catalog | None, uri: str):
    """The name under the cursor and what kind of thing it is, whichever format the file
    is in. Only what the project owns comes back."""
    if is_yaml(uri):
        found = yaml_symbol_at(text, position, catalog)
        return found if found and found[0] in _OURS else None
    return _symbol(Cursor(text, position), catalog)


def _offered(text: str, position: Position, catalog: Catalog | None, uri: str):
    """The whole field the cursor is in, which is where the name is looked for."""
    if is_yaml(uri):
        found = yaml_cursor.cursor(text, position, catalog)
        return (found.start, found.start + len(found.word)) if found.word else None

    cursor = Cursor(text, position)
    places = spans(text.splitlines()[position.line])
    return places[cursor.column] if cursor.column < len(places) else None


def prepare(
    text: str, position: Position, catalog: Catalog | None, *, uri: str = ""
) -> Range | None:
    """The span the client should offer to edit, or nothing if the name is not ours."""
    found = _symbol_at(text, position, catalog, uri)
    field = _offered(text, position, catalog, uri)
    if found is None or field is None:
        return None

    # A ${name} offers only the name: the braces are not part of it.
    _, name = found
    start, end = field
    line = text.splitlines()[position.line]
    inside = line.find(name, start, end)
    at = (inside, inside + len(name)) if inside >= 0 else (start, end)
    return Range(
        start=Position(line=position.line, character=to_utf16(line, at[0])),
        end=Position(line=position.line, character=to_utf16(line, at[1])),
    )


def rename(
    sources: Iterable[tuple[str, str]],
    catalog: Catalog | None,
    text: str,
    position: Position,
    new_name: str,
    *,
    uri: str = "",
) -> dict[str, list[TextEdit]] | None:
    """Where the name under the cursor is written, and what to put there instead."""
    found = _symbol_at(text, position, catalog, uri)
    if found is None:
        return None

    kind, name = found
    # Kept, because the spans come back as code-point offsets and turning one into the
    # column a client counts in needs the line it sits on.
    sources = list(sources)
    lines = {uri: body.splitlines() for uri, body in sources}

    edits: dict[str, list[TextEdit]] = {}
    for uri, line, start, end in places(sources, catalog or {}, kind, name):
        row = lines[uri][line] if line < len(lines[uri]) else ""
        edits.setdefault(uri, []).append(
            TextEdit(
                range=Range(
                    start=Position(line=line, character=to_utf16(row, start)),
                    end=Position(line=line, character=to_utf16(row, end)),
                ),
                new_text=new_name,
            )
        )
    return edits or None
