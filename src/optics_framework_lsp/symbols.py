# The outline of one csv: the test cases, modules or elements it defines, and the rows
# that make each of them up.

from __future__ import annotations

from lsprotocol.types import DocumentSymbol, Position, Range, SymbolKind

from .parser.ast import AST, Block, Element


def _symbol(
    name: str,
    kind: SymbolKind,
    detail: str,
    first: int,
    last: int,
    children: list[DocumentSymbol] | None = None,
) -> DocumentSymbol:
    """Rows are 1-based, so a symbol runs from its first line to just past its last."""
    at = Range(
        start=Position(line=max(first - 1, 0), character=0),
        end=Position(line=max(last, 0), character=0),
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
            ", ".join(param for param in step.params if param),
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
        _symbol(row.value, SymbolKind.String, "", row.row, row.row) for row in rows
    ]
    return _symbol(
        rows[0].name,
        SymbolKind.Variable,
        _count(len(rows), "locator"),
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

    return found + [_element(rows) for rows in grouped.values()]
