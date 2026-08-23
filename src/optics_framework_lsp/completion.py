# Completion and signature help. The column a cursor sits in decides what belongs there.

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Literal

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


ParamKind = Literal["module", "file", "api"]

# What a param holds, by keyword and position after `module_step`. Anything unlisted
# holds an element or variable.
_PARAM_KINDS: dict[str, dict[int, ParamKind]] = {
    "run loop": {0: "module"},
    "execute module": {0: "module"},
    "read data": {1: "file"},
    "invoke api": {0: "api"},
}


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

    def step_name(self, step: int) -> str:
        return self.fields[step].lower() if step < len(self.fields) else ""

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


def _modules(cursor: Cursor, ast: AST, prefix: str = "") -> list[CompletionItem]:
    return [
        _item(cursor, name, CompletionItemKind.Module, "module", prefix + name)
        for name in sorted({m.name for m in ast.modules})
    ]


def _paths(cursor: Cursor, names: Sequence[str], detail: str) -> list[CompletionItem]:
    return [_item(cursor, name, CompletionItemKind.File, detail, name) for name in names]


def _variables(cursor: Cursor, ast: AST) -> list[CompletionItem]:
    names = {e.name for e in ast.elements} | declared(ast)
    return [
        _item(cursor, name, CompletionItemKind.Variable, "element", f"${{{name}}}")
        for name in sorted(names)
    ]


def complete(
    text: str,
    position: Position,
    ast: AST,
    catalog: Catalog | None,
    *,
    images: Sequence[str] = (),
    data_files: Sequence[str] = (),
    apis: Sequence[str] = (),
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
        name = cursor.step_name(step)
        param = cursor.column - step - 1

        # `Condition` alternates condition, target. A target is always a module, while a
        # condition is either a module, optionally !-inverted, or an expression.
        if name == "condition":
            modules = _modules(cursor, ast, "!" if cursor.partial.startswith("!") else "")
            return modules if param % 2 else modules + _variables(cursor, ast)

        kind = _PARAM_KINDS.get(name, {}).get(param)
        if kind == "module":
            # A module to run, not an element to find, and written bare.
            return _modules(cursor, ast)
        if kind == "file":
            # Resolved against the project root, so a relative path is what belongs here.
            return _paths(cursor, data_files, "data file")
        if kind == "api":
            return [
                _item(cursor, name, CompletionItemKind.Value, "api", name) for name in apis
            ]

        return _variables(cursor, ast)

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
        return _paths(cursor, images, "template image")

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

    name = cursor.step_name(step)
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
