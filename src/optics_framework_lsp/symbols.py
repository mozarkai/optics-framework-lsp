# The outline of one csv: the test cases, modules or elements it defines, and the rows
# that make each of them up. `workspace_symbols` is the same names across a whole project,
# flat and searchable, for a caller that has no file in hand.

from __future__ import annotations

from lsprotocol.types import (
    DocumentSymbol,
    Location,
    Position,
    Range,
    SymbolKind,
    WorkspaceSymbol,
)

from .parser.ast import AST, Block, Element


def _symbol(
    name: str,
    kind: SymbolKind,
    detail: str,
    first: int,
    last: int,
    children: list[DocumentSymbol] | None = None,
    chars: tuple[int, int] | None = None,
) -> DocumentSymbol:
    """Rows are 1-based, so a symbol runs from its first line to just past its last —
    unless it is a single cell, which spans its own columns instead. Two cells on one
    row need distinct ranges or a client is free to treat them as one symbol."""
    line = max(first - 1, 0)
    start, end = chars or (0, 0)
    at = Range(
        start=Position(line=line, character=start),
        end=Position(line=line if chars else max(last, 0), character=end),
    )
    return DocumentSymbol(
        name=name,
        kind=kind,
        detail=detail,
        range=at,
        selection_range=Range(start=at.start, end=at.start),
        children=children,
    )


def _count(rows: int, noun: str) -> str:
    return f"{rows} {noun}" if rows == 1 else f"{rows} {noun}s"


def _block(block: Block, kind: SymbolKind) -> DocumentSymbol:
    """A test case or a module, with a child per row: the steps it runs in order."""
    steps = [
        _symbol(
            step.step_name or "",
            SymbolKind.Method,
            ", ".join(step.params),
            step.row,
            step.row,
        )
        for step in block.steps
    ]
    last = max((step.row for step in block.steps), default=block.start_row)
    return _symbol(
        block.name, kind, _count(len(steps), "step"), block.start_row, last, steps
    )


def _element(rows: list[Element]) -> DocumentSymbol:
    """One element, with a child per locator: the fallbacks tried in order."""
    locators = [
        _symbol(
            found.text, SymbolKind.String, "", row.row, row.row,
            chars=(found.start, found.end),
        )
        for row in rows
        for found in row.locators
    ]
    return _symbol(
        rows[0].name,
        SymbolKind.Variable,
        _count(len(locators), "locator"),
        rows[0].row,
        rows[-1].row,
        locators,
    )


def symbols(ast: AST) -> list[DocumentSymbol]:
    """A csv holds one kind of thing, so only one of these lists is ever filled."""
    found = [_block(block, SymbolKind.Class) for block in ast.test_cases]
    found += [_block(block, SymbolKind.Function) for block in ast.modules]

    # A name repeated with another locator is one element with fallbacks, as
    # `read_elements` gathers them, so its rows nest under it instead of repeating it.
    grouped: dict[str, list[Element]] = {}
    for element in ast.elements:
        grouped.setdefault(element.name, []).append(element)

    found += [_element(rows) for rows in grouped.values()]

    # An error code has nothing under it: the row is the whole definition.
    return found + [
        _symbol(error.code, SymbolKind.Constant, error.match, error.row, error.row)
        for error in ast.error_definitions
        if error.code
    ]


def workspace_symbols(ast: AST, query: str) -> list[WorkspaceSymbol]:
    """Every name the project declares, for `workspace/symbol`.

    Declarations only. Steps and locators are in the per-file outline, and including them
    here would bury the handful of names a caller is searching for under every row that
    mentions them.
    """
    wanted = query.strip().lower()

    # Keyed to collapse an element repeated across rows for its fallback locators — which
    # `read_elements` treats as one element — into the row that first declares it.
    found: dict[tuple[str, str], WorkspaceSymbol] = {}

    def add(name: str, kind: SymbolKind, uri: str, row: int) -> None:
        if not name or wanted not in name.lower():
            return
        at = Position(line=max(row - 1, 0), character=0)
        found.setdefault(
            (name, uri),
            WorkspaceSymbol(
                name=name,
                kind=kind,
                # The kind the header row made the file. It is the only place a caller can
                # be told a module from a test case: WorkspaceSymbol has no `detail`.
                container_name=ast.kinds.get(uri),
                location=Location(uri=uri, range=Range(start=at, end=at)),
            ),
        )

    # The same kinds as the outline above, so a client showing both does not label one
    # thing two ways.
    for block in ast.test_cases:
        add(block.name, SymbolKind.Class, block.uri, block.start_row)

    for block in ast.modules:
        add(block.name, SymbolKind.Function, block.uri, block.start_row)

    for element in ast.elements:
        add(element.name, SymbolKind.Variable, element.uri, element.row)

    for error in ast.error_definitions:
        add(error.code, SymbolKind.Constant, error.uri, error.row)

    return list(found.values())
