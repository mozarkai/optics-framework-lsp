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
    InsertTextFormat,
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

from . import yaml_cursor
from .keyword_catalog import Catalog, Keyword, slug
from .parser.ast import AST
from .parser import is_yaml
from .parser.csv_parser import filled_params
from .parser.yaml_parser import tokens as step_tokens
from .positions import from_utf16, to_utf16
from .yaml_cursor import YamlCursor
from .validation import (
    VAR,
    declarations,
    declared,
    declares_at,
    element_refs,
    module_conditions,
    module_refs,
    runs_at,
    undefined,
)


ParamKind = Literal["module", "file", "api"]

# What a yaml holds at the top level, spelt as `read_test_cases` and friends look the
# keys up. The yaml counterpart of `_HEADERS`: naming the section is what decides what
# the file is, so it is the one thing worth offering in an empty file.
_SECTION_KEYS = ("Test Cases", "Modules", "Elements")

# What a param holds, by keyword and position after `module_step`. Anything unlisted
# holds an element or variable.
PARAM_KINDS: dict[str, dict[int, ParamKind]] = {
    "run loop": {0: "module"},
    "execute module": {0: "module"},
    "read data": {1: "file"},
    "invoke api": {0: "api"},
}

# Values a param accepts, by param name. Documented in docstrings only, so the catalog
# cannot supply them: `direction` is checked as `in ("up", "down")` by the appium driver,
# and `rule` as `any(...) if rule == 'any' else all(...)`.
PARAM_VALUES = {
    "direction": ["up", "down", "left", "right"],
    "rule": ["any", "all"],
    "element_state": ["visible", "invisible", "enabled", "disabled"],
    "fail": ["True", "False"],
    # For Get Interactive Elements keyword. The full set is in `expose_api.py`, not
    # the keyword's own docstring, which shows two.
    "filter_config": ["all", "interactive", "buttons", "inputs", "images", "text"],
}

# Params holding a literal, not a name the project defines: everything unlisted falls
# through to the elements and bound variables.
_LITERAL = {
    "aoi_height", "aoi_width", "aoi_x", "aoi_y",
    "coor_x", "coor_y", "duration", "event_name", "index", "keycode", "number",
    "offset_x", "offset_y", "percent_x", "percent_y",
    "repeat", "scroll_length", "swipe_length", "timeout", "timeout_str",
    # An app the device knows, not a name the project defines.
    "app_activity", "app_identifier", "app_name", "app_package",
    # `date_evaluate`'s output format, a strftime string like `%d %B`.
    "param4",
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


# The header decides what a csv is. These are the four `_identify_csv_content` accepts,
# written as the framework reads them back: `read_elements` looks up `Element_Name` with
# the case intact, while the other three readers lowercase theirs. Five params is what
# 5 of 7 real projects write.
_HEADERS = {
    "test_case,test_step": "test cases",
    "module_name,module_step,param_1,param_2,param_3,param_4,param_5": "modules",
    "Element_Name,Element_ID": "elements",
    "error_code,match_string,description,severity": "error definitions",
}


class Cursor:
    """Where a position falls in a csv: its header row, column, and partial field."""

    def __init__(self, text: str, position: Position) -> None:
        lines = text.splitlines()
        line = lines[position.line] if position.line < len(lines) else ""
        # The client counted the column in utf-16; everything below slices `str`.
        at = from_utf16(line, position.character)
        prefix = line[:at]
        self.source = line
        self.paired = line[at:].startswith("}")

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
        self.start = at - len(self.partial)

    def column_of(self, header: str) -> int | None:
        return self.headers.index(header) if header in self.headers else None

    def field(self, column: int) -> str:
        return self.fields[column] if column < len(self.fields) else ""

    def header_at(self, column: int) -> str:
        return self.headers[column] if column < len(self.headers) else ""

    def step_name(self, step: int) -> str:
        return slug(self.field(step))

    def replacement(self, text: str) -> TextEdit:
        """Replace the whole field, so ${b} completes without nesting into ${${b}}."""
        # An editor that auto-pairs braces leaves `${|}`, and the item brings its own.
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


# Both cursors answer "what is being typed and what should replace it", which is all a
# completion item needs from one. Everything past that differs: a csv has columns and a
# yaml has depth.
AnyCursor = Cursor | YamlCursor


def _widen_header(cursor: Cursor, step: int) -> list[TextEdit] | None:
    """`csv.DictReader` drops cells the header does not name, so declare the columns."""
    if cursor.line == cursor.header_line or cursor.column < len(cursor.headers):
        return None

    added = "".join(f",param_{i - step}" for i in range(len(cursor.headers), cursor.column + 1))
    header = cursor.header
    at = Position(line=cursor.header_line, character=to_utf16(header, len(header)))
    return [TextEdit(range=Range(start=at, end=at), new_text=added)]


def _item(cursor: AnyCursor, label: str, kind: CompletionItemKind, detail: str, text: str):
    return CompletionItem(
        label=label,
        kind=kind,
        detail=detail,
        text_edit=cursor.replacement(text),
        filter_text=text,
    )


def _modules(cursor: AnyCursor, ast: AST, prefix: str = "") -> list[CompletionItem]:
    return [
        _item(cursor, name, CompletionItemKind.Module, "module", prefix + name)
        for name in sorted({m.name for m in ast.modules})
    ]


def _listing(
    cursor: AnyCursor, names: Iterable[str], kind: CompletionItemKind, detail: str
) -> list[CompletionItem]:
    """Names offered as they are written."""
    return [_item(cursor, name, kind, detail, name) for name in names]


def _variables(
    cursor: AnyCursor, ast: AST, catalog: Catalog | None = None
) -> list[CompletionItem]:
    names = {e.name for e in ast.elements} | declared(ast, catalog)
    return [
        _item(cursor, name, CompletionItemKind.Variable, "element", f"${{{name}}}")
        for name in sorted(names)
    ]


def _params(
    cursor: AnyCursor,
    ast: AST,
    catalog: Catalog | None,
    name: str,
    param: int,
    *,
    data_files: Sequence[str],
    apis: Sequence[str],
) -> list[CompletionItem]:
    """What belongs in a param slot, by the keyword the step names. Given the name and
    the index rather than working them out, because a csv counts columns and a yaml
    counts words."""
    # `Condition` alternates condition, target. A target is always a module, while a
    # condition is either a module, optionally !-inverted, or an expression.
    if name == "condition":
        modules = _modules(cursor, ast, "!" if cursor.partial.startswith("!") else "")
        return modules if param % 2 else modules + _variables(cursor, ast, catalog)

    kind = PARAM_KINDS.get(name, {}).get(param)
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
    param_name = names[param] if param < len(names) else ""
    if values := PARAM_VALUES.get(param_name):
        return _listing(cursor, values, CompletionItemKind.EnumMember, "value")

    # A yaml writes a number as `Sleep ${five}`, so keep the elements reachable behind `$`.
    if param_name in _LITERAL and not cursor.partial.startswith("$"):
        return []

    return _variables(cursor, ast, catalog)


def _call(name: str, keyword: Keyword) -> str:
    """The keyword with a hole per required param; a fixed-value one becomes a choice."""
    holes = []
    for at, param in enumerate(keyword.params[: keyword.required], start=1):
        values = PARAM_VALUES.get(param)
        hole = f"${{{at}|{','.join(values)}|}}" if values else f"${{{at}:{param}}}"
        holes.append(f'{param}="{hole}"')
    return " ".join([name.title(), *holes])


def _param_names(
    cursor: YamlCursor, catalog: Catalog | None, *, snippets: bool
) -> list[CompletionItem]:
    """The keyword's params, as `name="` with the cursor inside the quotes. Not where a
    value is being typed -- a name there would nest -- and not one already written."""
    keyword = (catalog or {}).get(cursor.step_name)
    # Past the end of the line has nothing before it, which is where a step is written.
    before = cursor.source[max(cursor.start - 1, 0) : cursor.start]
    if keyword is None or cursor.partial.startswith("$") or (before and not before.isspace()):
        return []

    keys = (token.group().partition("=")[0] for token in step_tokens(cursor.source))
    written = {key for key in keys if key in keyword.params}
    # A slot a positional fills cannot be named too; the token being typed fills nothing.
    taken = max(cursor.params - bool(cursor.partial) - len(written), 0)

    items = []
    for name in keyword.params[taken:]:
        if name in written:
            continue
        default = keyword.defaults.get(name)
        detail = f"param, {default} if omitted" if default else "param"
        item = _item(cursor, f"{name}=", CompletionItemKind.Property, detail, f"{name}=")
        if snippets:
            item.text_edit = cursor.replacement(f'{name}="$0"')
            item.insert_text_format = InsertTextFormat.Snippet
        items.append(item)
    return items


def _steps(
    cursor: AnyCursor, ast: AST, catalog: Catalog | None, *, snippets: bool = False
) -> list[CompletionItem]:
    """What a step may name: any keyword, or any module for a nested call."""
    items = _modules(cursor, ast)
    for name, keyword in sorted((catalog or {}).items()):
        label = name.title()
        detail = ", ".join(keyword.params) or "no params"
        item = _item(cursor, label, CompletionItemKind.Keyword, detail, label)
        if snippets and keyword.required:
            item.text_edit = cursor.replacement(_call(name, keyword))
            item.insert_text_format = InsertTextFormat.Snippet
        items.append(item)
    return items


def _test_cases(cursor: AnyCursor, ast: AST) -> list[CompletionItem]:
    """Test cases that exist, plus the lifecycle names not yet used."""
    names = sorted({t.name for t in ast.test_cases})
    return _listing(cursor, names, CompletionItemKind.Value, "test case") + [
        _item(cursor, name, CompletionItemKind.Event, detail, name)
        for name, detail in _LIFECYCLE.items()
        if name not in names
    ]



def _complete_yaml(
    text: str,
    position: Position,
    ast: AST,
    catalog: Catalog | None,
    *,
    images: Sequence[str],
    data_files: Sequence[str],
    apis: Sequence[str],
    snippets: bool,
) -> list[CompletionItem]:
    found = yaml_cursor.cursor(text, position, catalog)

    if found.place == "top":
        # Naming a section is what makes the file a suite, so it is what an empty one
        # is offered. Only the ones it does not have — and a section spelt in the wrong
        # case is not one it has, because the reader never finds it.
        taken = {key for _, key in yaml_cursor.sections(text.splitlines())}
        return [
            _item(found, f"{key}:", CompletionItemKind.Struct, "section", f"{key}:")
            for key in _SECTION_KEYS
            if key not in taken
        ]

    if found.section == "test_cases":
        # A test case's steps are modules; both name slots continue an existing block.
        if found.place == "step":
            return _modules(found, ast)
        return _test_cases(found, ast)

    if found.section == "modules":
        if found.place != "step":
            return _modules(found, ast)
        if found.param < 0:
            return _steps(found, ast, catalog, snippets=snippets)
        return _params(
            found,
            ast,
            catalog,
            found.step_name,
            found.param,
            data_files=data_files,
            apis=apis,
        ) + _param_names(found, catalog, snippets=snippets)

    if found.section == "elements":
        if found.place == "locator":
            # An id is usually an xpath or literal text, which we cannot guess, but an
            # image locator is the bare filename of a template in the project.
            return _listing(found, images, CompletionItemKind.File, "template image")
        kind = CompletionItemKind.Variable
        return _listing(found, sorted(undefined(ast, catalog)), kind, "used, not defined")

    return []


def complete(
    text: str,
    position: Position,
    ast: AST,
    catalog: Catalog | None,
    *,
    uri: str = "",
    images: Sequence[str] = (),
    data_files: Sequence[str] = (),
    apis: Sequence[str] = (),
    snippets: bool = False,
) -> list[CompletionItem]:
    if is_yaml(uri):
        return _complete_yaml(
            text,
            position,
            ast,
            catalog,
            images=images,
            data_files=data_files,
            apis=apis,
            snippets=snippets,
        )

    cursor = Cursor(text, position)

    # Nothing is defined yet, so the row being typed is the header that decides the kind.
    if cursor.column == 0 and len([row for row in text.splitlines() if row.strip()]) <= 1:
        kind = CompletionItemKind.Struct
        return [_item(cursor, h, kind, detail, h) for h, detail in _HEADERS.items()]

    step = cursor.column_of("module_step")

    if step is not None and cursor.column == step:
        return _steps(cursor, ast, catalog)

    if step is not None and cursor.column > step:
        # A blank holds no place, so the runner's index is the filled count, not the column.
        items = _params(
            cursor,
            ast,
            catalog,
            cursor.step_name(step),
            sum(1 for at in filled_params(cursor.fields, cursor.headers) if at < cursor.column),
            data_files=data_files,
            apis=apis,
        )

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
        return _listing(cursor, sorted(undefined(ast, catalog)), kind, "used, not defined")

    # An id is usually an xpath or literal text, which we cannot guess, but an image
    # locator is the bare filename of a template somewhere in the project. Any
    # `element_id*` column holds one, as `read_elements` reads them all.
    if cursor.header_at(cursor.column).startswith("element_id"):
        return _listing(cursor, images, CompletionItemKind.File, "template image")

    if cursor.column == cursor.column_of("test_case"):
        return _test_cases(cursor, ast)

    return []


def _rendered(keyword: Keyword) -> list[str]:
    """Params as `name='default'`, so what an omitted cell falls back to is visible."""
    return [
        f"{name}={keyword.defaults[name]}" if name in keyword.defaults else name
        for name in keyword.params
    ]


def _signature_at(
    text: str, position: Position, catalog: Catalog | None, uri: str
) -> tuple[str, int] | None:
    """The keyword the cursor is inside the params of, and which param that is."""
    if is_yaml(uri):
        found = yaml_cursor.cursor(text, position, catalog)
        if found.section != "modules" or found.place != "step" or found.param < 0:
            return None
        return found.step_name, found.param

    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")
    if step is None or cursor.column <= step:
        return None
    return cursor.step_name(step), cursor.column - step - 1


def signature(
    text: str, position: Position, catalog: Catalog | None, *, uri: str = ""
) -> SignatureHelp | None:
    """The keyword's params, with the one the cursor is in marked active."""
    found = _signature_at(text, position, catalog, uri) if catalog else None
    if found is None:
        return None

    name, param = found
    keyword = catalog.get(name) if catalog else None
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
        active_parameter=min(param, max(len(keyword.params) - 1, 0)),
    )


def _at(uri: str, row: int) -> Location:
    """A definition points at the start of its row, which is 1-based in the ast."""
    at = Position(line=max(row - 1, 0), character=0)
    return Location(uri=uri, range=Range(start=at, end=at))


def definition(
    text: str, position: Position, ast: AST, catalog: Catalog | None, *, uri: str = ""
) -> list[Location]:
    """Where the module a step runs, or the elements a param reads, are defined."""
    if is_yaml(uri):
        found = yaml_symbol_at(text, position, catalog)
        if found is None:
            return []

        kind, name = found
        if kind == "element":
            return [_at(e.uri, e.row) for e in ast.elements if e.name == name]
        if kind == "module":
            return [_at(m.uri, m.start_row) for m in ast.modules if m.name == name]
        # A keyword is the framework's, and an image, data file or api is not a name the
        # suite declares anywhere.
        return []

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


# Only these classify as Image in `determine_element_type` (.tiff discovers but never
# matches), so an id ending in one is a template filename, not an xpath or literal text.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")


def _symbol_at(cursor: Cursor, catalog: Catalog | None) -> tuple[str, str] | None:
    """What the cursor is on, as a kind and the name to match against."""
    field = cursor.field(cursor.column)
    if not field:
        return None

    step = cursor.column_of("module_step")
    if cursor.column in (cursor.column_of("module_name"), cursor.column_of("test_step")):
        return "module", field
    if cursor.column == cursor.column_of("element_name"):
        return "element", field
    if cursor.header_at(cursor.column).startswith("element_id"):
        # Only an image is shared by name; an xpath is written per row.
        return ("image", field) if field.lower().endswith(IMAGE_SUFFIXES) else None

    if step is None or cursor.column < step:
        return None
    if cursor.column == step:
        # A keyword beats a same-named module here, as `_execute_single_keyword` resolves.
        return ("keyword" if slug(field) in (catalog or {}) else "module"), field

    return param_symbol(cursor, step)


def param_symbol(cursor: Cursor, step: int) -> tuple[str, str] | None:
    """What a param cell names, shared with `rename` so a binding cell resolves the same
    either way. Indexed by filled params, as the runner reads them: a blank holds no place."""
    field = cursor.field(cursor.column)
    if names := VAR.findall(field):
        return "element", names[0]

    filled = filled_params(cursor.fields, cursor.headers)
    param = filled.index(cursor.column) if cursor.column in filled else -1
    name = cursor.step_name(step)

    if param in declares_at(name, len(filled)):
        return "element", field
    if param in runs_at(name, len(filled)):
        return "module", field.removeprefix("!")
    kind = PARAM_KINDS.get(name, {}).get(param)
    return (kind, field) if kind else None


def _yaml_param_symbol(found: YamlCursor) -> tuple[str, str] | None:
    """What a yaml step's param names, by the same rules as `param_symbol`. The index is
    the word's place after the keyword, where a csv counts filled columns."""
    if names := VAR.findall(found.word):
        return "element", names[0]
    if found.param in declares_at(found.step_name, found.params):
        return "element", found.word
    if found.param in runs_at(found.step_name, found.params):
        return "module", found.word.removeprefix("!")

    kind = PARAM_KINDS.get(found.step_name, {}).get(found.param)
    return (kind, found.word) if kind else None


def yaml_symbol_at(
    text: str, position: Position, catalog: Catalog | None
) -> tuple[str, str] | None:
    """What the cursor is on, as a kind and the name to match against. The yaml
    counterpart of `_symbol_at`: depth and word position where that one has columns.

    Shared with `rename`, so a name resolves the same whether it is being looked up or
    moved."""
    found = yaml_cursor.cursor(text, position, catalog)
    if not found.word:
        return None

    if found.section == "test_cases":
        return ("module" if found.place == "step" else "test case"), found.word

    if found.section == "elements":
        if found.place != "locator":
            return "element", found.word
        # Only an image is shared by name; an xpath is written per element.
        image = found.word.lower().endswith(IMAGE_SUFFIXES)
        return ("image", found.word) if image else None

    if found.section != "modules":
        return None
    if found.place != "step":
        return "module", found.word
    if found.param >= 0:
        return _yaml_param_symbol(found)

    # A keyword beats a same-named module here, as `_execute_single_keyword` resolves.
    known = slug(found.word) in (catalog or {})
    return ("keyword" if known else "module"), found.word


def references(
    text: str,
    position: Position,
    ast: AST,
    catalog: Catalog | None,
    *,
    uri: str = "",
    include_declaration: bool = False,
) -> list[Location]:
    """Every place the name under the cursor is used, and optionally where it is bound."""
    found = (
        yaml_symbol_at(text, position, catalog)
        if is_yaml(uri)
        else _symbol_at(Cursor(text, position), catalog)
    )
    if found is None:
        return []

    kind, name = found
    declared_at: list[Location] = []

    if kind == "module":
        # A Condition names a module to run, which validation cannot assume, and so does
        # a step cell — but only when no keyword claims the name first.
        seen = list(module_refs(ast, catalog)) + list(module_conditions(ast)) + [
            (m.uri, step.row, step.step_name)
            for m in ast.modules
            for step in m.steps
            if step.step_name and slug(step.step_name) not in (catalog or {})
        ]
        uses = [_at(uri, row) for uri, row, n in seen if n == name]
        declared_at = [_at(m.uri, m.start_row) for m in ast.modules if m.name == name]
    elif kind == "element":
        uses = [_at(uri, row) for uri, row, n in element_refs(ast, catalog) if n == name]
        declared_at = [_at(e.uri, e.row) for e in ast.elements if e.name == name] + [
            _at(uri, row) for uri, row, n in declarations(ast, catalog) if n == name
        ]
    elif kind == "keyword":
        # The framework defines it, so there is nothing here to declare.
        wanted = slug(name)
        uses = [
            _at(module.uri, step.row)
            for module in ast.modules
            for step in module.steps
            if slug(step.step_name) == wanted
        ]
    elif kind == "image":
        uses = [
            _at(e.uri, e.row)
            for e in ast.elements
            if any(locator.text == name for locator in e.locators)
        ]
    else:
        # A file or an api, by the same table completion offers.
        uses = [
            _at(m.uri, step.row)
            for m in ast.modules
            for step in m.steps
            for i, param in enumerate(step.params)
            if PARAM_KINDS.get(slug(step.step_name), {}).get(i) == kind and param == name
        ]

    # Sorted, so a result reads top to bottom per file rather than by rule order.
    uses.sort(key=lambda at: (at.uri, at.range.start.line))
    return uses + declared_at if include_declaration else uses


def _hovered(
    text: str, position: Position, catalog: Catalog | None, uri: str
) -> str | None:
    """The step name under the cursor, however the file is written."""
    if is_yaml(uri):
        # A step naming a module rather than a keyword comes back as one, and misses
        # the catalog lookup below just as it would have.
        found = yaml_symbol_at(text, position, catalog)
        return found[1] if found and found[0] == "keyword" else None

    cursor = Cursor(text, position)
    step = cursor.column_of("module_step")
    return cursor.field(step) if step is not None and cursor.column == step else None


def hover(
    text: str, position: Position, catalog: Catalog | None, *, uri: str = ""
) -> Hover | None:
    """A keyword's signature and the framework's own docstring for it."""
    name = _hovered(text, position, catalog, uri)
    if name is None:
        return None

    keyword = (catalog or {}).get(slug(name))
    if keyword is None:
        return None

    # Plain text, because the docstrings are reST: markdown would fold the `:param x:`
    # lines into one paragraph.
    label = f"{name}({', '.join(_rendered(keyword))})"
    return Hover(
        contents=MarkupContent(
            kind=MarkupKind.PlainText,
            value=f"{label}\n\n{keyword.doc}" if keyword.doc else label,
        )
    )
