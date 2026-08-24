# Completion, signature help, goto-definition and hover. The column a cursor sits in
# decides what belongs there.

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Literal

from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    Hover,
    Location,
    MarkupContent,
    MarkupKind,
    ParameterInformation,
    Position,
    Range,
    SignatureHelp,
    SignatureInformation,
    TextEdit,
)

from .keyword_catalog import Catalog, Keyword, slug
from .parser.ast import AST
from .validation import VAR, declared, undefined


ParamKind = Literal["module", "file", "api"]

# What a param holds, by keyword and position after `module_step`. Anything unlisted
# holds an element or variable.
_PARAM_KINDS: dict[str, dict[int, ParamKind]] = {
    "run loop": {0: "module"},
    "execute module": {0: "module"},
    "read data": {1: "file"},
    "invoke api": {0: "api"},
}

# Values a param accepts, by param name. Documented in docstrings only, so the catalog
# cannot supply them: `direction` is checked as `in ("up", "down")` by the appium driver,
# and `rule` as `any(...) if rule == 'any' else all(...)`.
_PARAM_VALUES = {
    "direction": ["up", "down", "left", "right"],
    "rule": ["any", "all"],
    "element_state": ["visible", "invisible", "enabled", "disabled"],
}


# Test cases the runner lifts out of the normal order. `categorize_test_cases` matches
# the words anywhere in the name, so these are canonical spellings, not reserved words.
# No frequency is claimed here: `get_execution_queue` keys its plan by name, so the
# test-level pair lands once around the first test rather than around every one.
_LIFECYCLE = {
    "Suite Setup": "suite setup, before the tests",
    "Suite Teardown": "suite teardown, after the tests",
    "Setup": "test-level setup",
    "Teardown": "test-level teardown",
}


class Cursor:
    """Where a position falls in a csv: its header row, column, and partial field."""

    def __init__(self, text: str, position: Position) -> None:
        lines = text.splitlines()
        line = lines[position.line] if position.line < len(lines) else ""
        prefix = line[: position.character]

        self.header_line, header = next(
            ((i, row) for i, row in enumerate(lines) if row.strip()), (0, "")
        )
        self.header = header
        self.headers = [h.strip().lower() for h in next(csv.reader(io.StringIO(header)), [])]
        self.fields = [f.strip() for f in next(csv.reader(io.StringIO(line)), [])]

        # csv, not prefix.count(","), so a quoted comma in an XPath does not shift us.
        fields = next(csv.reader(io.StringIO(prefix)), [""]) or [""]
        self.column = len(fields) - 1
        self.partial = fields[-1]
        self.line = position.line
        self.start = position.character - len(self.partial)

    def column_of(self, header: str) -> int | None:
        return self.headers.index(header) if header in self.headers else None

    def field(self, column: int) -> str:
        return self.fields[column] if column < len(self.fields) else ""

    def step_name(self, step: int) -> str:
        return slug(self.field(step))

    def replacement(self, text: str) -> TextEdit:
        """Replace the whole field, so ${b} completes without nesting into ${${b}}."""
        return TextEdit(
            range=Range(
                start=Position(line=self.line, character=self.start),
                end=Position(line=self.line, character=self.start + len(self.partial)),
            ),
            new_text=text,
        )


def _widen_header(cursor: Cursor, step: int) -> list[TextEdit] | None:
    """`csv.DictReader` drops cells the header does not name, so declare the columns."""
    if cursor.line == cursor.header_line or cursor.column < len(cursor.headers):
        return None

    added = "".join(f",param_{i - step}" for i in range(len(cursor.headers), cursor.column + 1))
    at = Position(line=cursor.header_line, character=len(cursor.header))
    return [TextEdit(range=Range(start=at, end=at), new_text=added)]


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


def _listing(
    cursor: Cursor, names: Iterable[str], kind: CompletionItemKind, detail: str
) -> list[CompletionItem]:
    """Names offered as they are written."""
    return [_item(cursor, name, kind, detail, name) for name in names]


def _variables(cursor: Cursor, ast: AST) -> list[CompletionItem]:
    names = {e.name for e in ast.elements} | declared(ast)
    return [
        _item(cursor, name, CompletionItemKind.Variable, "element", f"${{{name}}}")
        for name in sorted(names)
    ]


def _params(
    cursor: Cursor,
    ast: AST,
    catalog: Catalog | None,
    step: int,
    *,
    data_files: Sequence[str],
    apis: Sequence[str],
) -> list[CompletionItem]:
    """What belongs in a param column, by the keyword its row names."""
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
        return _listing(cursor, data_files, CompletionItemKind.File, "data file")
    if kind == "api":
        return _listing(cursor, apis, CompletionItemKind.Value, "api")

    # The catalog names the params, so a fixed-value one is found by name rather
    # than by listing every keyword that happens to take a `direction`.
    keyword = (catalog or {}).get(name)
    names = keyword.params if keyword else []
    if values := _PARAM_VALUES.get(names[param] if param < len(names) else ""):
        return _listing(cursor, values, CompletionItemKind.EnumMember, "value")

    return _variables(cursor, ast)


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
        items = _params(cursor, ast, catalog, step, data_files=data_files, apis=apis)

        # Accepting a param the header does not cover declares it in the same edit.
        for item in items:
            item.additional_text_edits = _widen_header(cursor, step)
        return items

    # Both name columns continue an existing block, so they offer what already exists.
    if cursor.column in (cursor.column_of("test_step"), cursor.column_of("module_name")):
        return _modules(cursor, ast)

    # Defining an element is how an element-not-found gets fixed, so offer those names.
    if cursor.column == cursor.column_of("element_name"):
        kind = CompletionItemKind.Variable
        return _listing(cursor, sorted(undefined(ast)), kind, "used, not defined")

    # An id is usually an xpath or literal text, which we cannot guess, but an image
    # locator is the bare filename of a template somewhere in the project.
    if cursor.column == cursor.column_of("element_id"):
        return _listing(cursor, images, CompletionItemKind.File, "template image")

    if cursor.column == cursor.column_of("test_case"):
        names = sorted({t.name for t in ast.test_cases})
        return _listing(cursor, names, CompletionItemKind.Value, "test case") + [
            _item(cursor, name, CompletionItemKind.Event, detail, name)
            for name, detail in _LIFECYCLE.items()
            if name not in names
        ]

    return []


def _rendered(keyword: Keyword) -> list[str]:
    """Params as `name='default'`, so what an omitted cell falls back to is visible."""
    return [
        f"{name}={keyword.defaults[name]}" if name in keyword.defaults else name
        for name in keyword.params
    ]


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

    # A parameter label must be a substring of the signature for a client to highlight
    # it, so both are built from the same rendering.
    params = _rendered(keyword)
    return SignatureHelp(
        signatures=[
            SignatureInformation(
                label=f"{name.title()}({', '.join(params)})",
                parameters=[ParameterInformation(label=p) for p in params],
            )
        ],
        active_signature=0,
        active_parameter=min(cursor.column - step - 1, max(len(keyword.params) - 1, 0)),
    )


def _at(uri: str, row: int) -> Location:
    """A definition points at the start of its row, which is 1-based in the ast."""
    at = Position(line=max(row - 1, 0), character=0)
    return Location(uri=uri, range=Range(start=at, end=at))


def definition(
    text: str, position: Position, ast: AST, catalog: Catalog | None
) -> list[Location]:
    """Where the module a step runs, or the elements a param reads, are defined."""
    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")
    if cursor.column != cursor.column_of("test_step") and (
        step is None or cursor.column < step
    ):
        return []

    field = cursor.field(cursor.column)

    # A step column resolves the keyword first, so a same-named module is not what runs.
    if cursor.column == step and slug(field) in (catalog or {}):
        return []

    # A cell holds either ${names} to read or a bare name to run. Every ${name} in the
    # cell is offered: a fallback element is several rows, and so is `${a} == ${b}`.
    if names := set(VAR.findall(field)):
        return [_at(e.uri, e.row) for e in ast.elements if e.name in names]

    # Condition writes an inverted module as `!Name`; the runner strips the same way.
    wanted = field.removeprefix("!")
    return [_at(m.uri, m.start_row) for m in ast.modules if m.name == wanted]


def hover(text: str, position: Position, catalog: Catalog | None) -> Hover | None:
    """A keyword's signature and the framework's own docstring for it."""
    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")
    if step is None or cursor.column != step:
        return None

    keyword = (catalog or {}).get(cursor.step_name(step))
    if keyword is None:
        return None

    # Plain text, because the docstrings are reST: markdown would fold the `:param x:`
    # lines into one paragraph.
    label = f"{cursor.field(step)}({', '.join(_rendered(keyword))})"
    return Hover(
        contents=MarkupContent(
            kind=MarkupKind.PlainText,
            value=f"{label}\n\n{keyword.doc}" if keyword.doc else label,
        )
    )
