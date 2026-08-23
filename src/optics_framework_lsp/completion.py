# Completion and signature help. The column a cursor sits in decides what belongs there.

from __future__ import annotations

import csv
import io
from collections.abc import Sequence

from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    ParameterInformation,
    Position,
    Range,
    SignatureHelp,
    SignatureInformation,
    TextEdit,
)

from .keyword_catalog import Catalog
from .parser.ast import AST
from .validation import declared, undefined


class Cursor:
    """Where a position falls in a csv: its header row, column, and partial field."""

    def __init__(self, text: str, position: Position) -> None:
        lines = text.splitlines()
        line = lines[position.line] if position.line < len(lines) else ""
        prefix = line[: position.character]

        header = next((row for row in lines if row.strip()), "")
        self.headers = [h.strip() for h in next(csv.reader(io.StringIO(header)), [])]
        self.fields = [f.strip() for f in next(csv.reader(io.StringIO(line)), [])]

        # csv, not prefix.count(","), so a quoted comma in an XPath does not shift us.
        fields = next(csv.reader(io.StringIO(prefix)), [""]) or [""]
        self.column = len(fields) - 1
        self.partial = fields[-1]
        self.line = position.line
        self.start = position.character - len(self.partial)

    def column_of(self, header: str) -> int | None:
        return self.headers.index(header) if header in self.headers else None

    def replacement(self, text: str) -> TextEdit:
        """Replace the whole field, so ${b} completes without nesting into ${${b}}."""
        return TextEdit(
            range=Range(
                start=Position(line=self.line, character=self.start),
                end=Position(line=self.line, character=self.start + len(self.partial)),
            ),
            new_text=text,
        )


def _item(cursor: Cursor, label: str, kind: CompletionItemKind, detail: str, text: str):
    return CompletionItem(
        label=label,
        kind=kind,
        detail=detail,
        text_edit=cursor.replacement(text),
        filter_text=text,
    )


def _modules(cursor: Cursor, ast: AST) -> list[CompletionItem]:
    return [
        _item(cursor, name, CompletionItemKind.Module, "module", name)
        for name in sorted({m.name for m in ast.modules})
    ]


def complete(
    text: str,
    position: Position,
    ast: AST,
    catalog: Catalog | None,
    images: Sequence[str] = (),
) -> list[CompletionItem]:
    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")

    if step is not None and cursor.column == step:
        # A step names a keyword or, for nested modules, another module.
        items = _modules(cursor, ast)
        for name, keyword in sorted((catalog or {}).items()):
            label = name.title()
            items.append(
                _item(
                    cursor,
                    label,
                    CompletionItemKind.Keyword,
                    ", ".join(keyword.params) or "no params",
                    label,
                )
            )
        return items

    if step is not None and cursor.column > step:
        names = {e.name for e in ast.elements} | declared(ast)
        return [
            _item(cursor, name, CompletionItemKind.Variable, "element", f"${{{name}}}")
            for name in sorted(names)
        ]

    # Both name columns continue an existing block, so they offer what already exists.
    if cursor.column in (cursor.column_of("test_step"), cursor.column_of("module_name")):
        return _modules(cursor, ast)

    # Defining an element is how an element-not-found gets fixed, so offer those names.
    if cursor.column == cursor.column_of("element_name"):
        return [
            _item(cursor, name, CompletionItemKind.Variable, "used, not defined", name)
            for name in sorted(undefined(ast))
        ]

    # An id is usually an xpath or literal text, which we cannot guess, but an image
    # locator is the bare filename of a template somewhere in the project.
    if cursor.column == cursor.column_of("element_id"):
        return [
            _item(cursor, name, CompletionItemKind.File, "template image", name)
            for name in images
        ]

    if cursor.column == cursor.column_of("test_case"):
        return [
            _item(cursor, name, CompletionItemKind.Value, "test case", name)
            for name in sorted({t.name for t in ast.test_cases})
        ]

    return []


def signature(text: str, position: Position, catalog: Catalog | None) -> SignatureHelp | None:
    """The keyword's params, with the column the cursor is in marked active."""
    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")
    if not catalog or step is None or cursor.column <= step:
        return None

    name = cursor.fields[step].lower() if step < len(cursor.fields) else ""
    keyword = catalog.get(name)
    if keyword is None:
        return None

    return SignatureHelp(
        signatures=[
            SignatureInformation(
                label=f"{name.title()}({', '.join(keyword.params)})",
                parameters=[ParameterInformation(label=p) for p in keyword.params],
            )
        ],
        active_signature=0,
        active_parameter=min(cursor.column - step - 1, max(len(keyword.params) - 1, 0)),
    )
