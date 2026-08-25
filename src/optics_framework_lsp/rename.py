# Renaming a name the project owns, across every file that writes it. The runner keys
# everything by name, so a rename that misses one cell silently changes what runs.

from __future__ import annotations

from collections.abc import Iterable, Iterator

from lsprotocol.types import Position, Range, TextEdit

from .completion import Cursor
from .keyword_catalog import Catalog, slug
from .parser.csv_parser import filled_params, sheet, spans
from .validation import VAR, declares_at, module_args

_Place = tuple[str, int, int, int]

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

    if names := VAR.findall(field):
        return "element", names[0]

    # Anything that is neither a bound name nor a module we run — a data file, an api
    # identifier, a plain value — names nothing we own.
    filled = filled_params(cursor.fields, cursor.headers)
    param = filled.index(cursor.column) if cursor.column in filled else -1
    if param in declares_at(cursor.step_name(step), len(filled)):
        return "element", field
    if param in _runs(cursor.step_name(step), len(filled)):
        return "module", field.removeprefix("!")
    return None


def _runs(step: str, count: int) -> set[int]:
    """Which params name a module to run. A `Condition` may in any slot: a target runs
    one, and a condition runs one to ask whether it passed."""
    return set(range(count)) if slug(step) == "condition" else module_args(step, count)


def _in_row(
    fields: list[str], places: list[tuple[int, int]], headers: list[str],
    catalog: Catalog, kind: str, name: str,
) -> Iterator[tuple[int, int]]:
    """Every span in one row that writes `name`, as the runner would read it."""
    step_at = headers.index("module_step") if "module_step" in headers else None
    step = fields[step_at] if step_at is not None and step_at < len(fields) else ""

    filled = filled_params(fields, headers)
    runs = _runs(step, len(filled))
    binds = declares_at(step, len(filled))

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
            yield from _in_param(cell, start, filled.index(column), runs, binds, kind, name)


def _in_param(
    cell: str, start: int, param: int, runs: set[int], binds: set[int], kind: str, name: str
) -> Iterator[tuple[int, int]]:
    if kind == "element":
        for match in VAR.finditer(cell):
            if match.group(1) == name:
                # Only the name moves; the ${} around it stays put.
                yield start + match.start(1), start + match.end(1)
        if param in binds and cell == name:
            yield start, start + len(cell)
    elif kind == "module" and param in runs and cell.removeprefix("!") == name:
        # The `!` of an inverted condition stays; only the name after it moves.
        yield start + len(cell) - len(name), start + len(cell)


def places(sources: Iterable[tuple[str, str]], catalog: Catalog, kind: str, name: str) -> Iterator[_Place]:
    """Every cell in the project that writes this name, as uri, line, start, end."""
    for uri, text in sources:
        headers, body = sheet(text)
        lines = text.splitlines()
        for number, fields in body:
            for start, end in _in_row(fields, spans(lines[number]), headers, catalog, kind, name):
                yield uri, number, start, end


def prepare(text: str, position: Position, catalog: Catalog | None) -> Range | None:
    """The span the client should offer to edit, or nothing if the name is not ours."""
    cursor = Cursor(text, position)
    found = _symbol(cursor, catalog)
    if found is None:
        return None

    _, name = found
    line = text.splitlines()[position.line]
    places = spans(line)
    if cursor.column >= len(places):
        return None

    # A ${name} offers only the name: the braces are not part of it.
    start, end = places[cursor.column]
    inside = line.find(name, start, end)
    at = (inside, inside + len(name)) if inside >= 0 else (start, end)
    return Range(
        start=Position(line=position.line, character=at[0]),
        end=Position(line=position.line, character=at[1]),
    )


def rename(
    sources: Iterable[tuple[str, str]],
    catalog: Catalog | None,
    text: str,
    position: Position,
    new_name: str,
) -> dict[str, list[TextEdit]] | None:
    """Where the name under the cursor is written, and what to put there instead."""
    found = _symbol(Cursor(text, position), catalog)
    if found is None:
        return None

    kind, name = found
    edits: dict[str, list[TextEdit]] = {}
    for uri, line, start, end in places(sources, catalog or {}, kind, name):
        edits.setdefault(uri, []).append(
            TextEdit(
                range=Range(
                    start=Position(line=line, character=start),
                    end=Position(line=line, character=end),
                ),
                new_text=new_name,
            )
        )
    return edits or None
