# Rules turn an AST into findings, keyed by uri.
#
# Deliberately protocol-free: a `Finding` is a plain dataclass, not an
# `lsprotocol.Diagnostic`. Importing `lsprotocol.types` costs ~290ms, which a long-lived
# server pays once but a per-call CLI would pay every time. Each transport converts.

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from operator import attrgetter

from .keyword_catalog import Catalog, slug
from .parser.ast import AST, ErrorDefinition

SOURCE = "optics"

# The two `DiagnosticSeverity` values we ever emit. Ints, and `DiagnosticSeverity` is an
# int-based enum, so a transport can hand these straight to lsprotocol.
ERROR = 1
WARNING = 2


@dataclass(slots=True)
class Finding:
    """One problem with one row. `row` is 1-based, as the framework counts rows."""

    severity: int
    code: str
    message: str
    row: int

    @property
    def line(self) -> int:
        """The 0-based line a client wants. The only definition of this conversion."""
        return max(self.row - 1, 0)


VAR = re.compile(r"\$\{([^}]+)\}")

# Keywords that bind a name instead of reading one, and which params hold the names.
# Taken from the optics-framework source: most store under the name in their first
# param, while Run Loop takes variable/iterable pairs after its target module.
_DECLARES = {
    "read data": slice(0, 1),
    "evaluate": slice(0, 1),
    "date evaluate": slice(0, 1),
    "run loop": slice(1, None, 2),
}


def _bare(name: str) -> str:
    """Declarations are written either plainly or as ${name}."""
    return name.strip().removeprefix("${").removesuffix("}").strip()


_CSV_ISSUES = {
    "whitespace-only-line": (
        WARNING,
        "csv-whitespace-line",
        "Whitespace-only line",
    ),
    "too-few-columns": (
        WARNING,
        "csv-too-few-columns",
        "Row has fewer than 2 columns, so it is skipped",
    ),
    "too-many-columns": (
        WARNING,
        "csv-too-many-columns",
        "Row has more columns than the header",
    ),
}

_Keyed = tuple[str, Finding]


def _diag(uri: str, row: int, severity: int, code: str, message: str) -> _Keyed:
    return uri, Finding(severity=severity, code=code, message=message, row=row)


# Where a short row is not skipped but fatal. `read_test_cases` and
# `read_error_definitions` do `row.get(column, "").strip()`, and `csv.DictReader` fills a
# missing field with None rather than the default — so they raise `AttributeError`, and
# neither `_load_test_cases` nor `_load_error_definitions` is wrapped. The whole project
# load dies before anything runs. `read_modules` and `read_elements` drop the row instead.
_SHORT_ROW_ABORTS_THE_RUN = {"test_cases", "error_definitions"}


def _hygiene(ast: AST) -> Iterator[_Keyed]:
    for issue in ast.csv_issues:
        severity, code, message = _CSV_ISSUES[issue.kind]
        if issue.kind == "too-few-columns" and ast.kinds.get(issue.uri) in _SHORT_ROW_ABORTS_THE_RUN:
            severity = ERROR
            message = "Row has fewer than 2 columns, which aborts the whole run"
        yield _diag(issue.uri, issue.row, severity, code, message)


def _duplicates(ast: AST) -> Iterator[_Keyed]:
    # A second module or test case of the same name overwrites the first, wherever the
    # files sit: `add_module_definition` assigns and `merge_dicts` keeps the later one.
    # Elements instead merge into one list, which is how platform variants coexist, so
    # for those only a single file repeating a row is a problem.
    seen: dict[tuple[str, str, str], list[tuple[str, int, tuple | None]]] = defaultdict(list)
    for kind, name, uri, row, value in (
        [("test case", b.name, b.uri, b.start_row, None) for b in ast.test_cases]
        + [("module", b.name, b.uri, b.start_row, None) for b in ast.modules]
        + [
            ("element", e.name, e.uri, e.row, tuple(l.text for l in e.locators))
            for e in ast.elements
        ]
    ):
        seen[(kind, name, uri if kind == "element" else "")].append((uri, row, value))

    for (kind, name, _), entries in seen.items():
        if kind == "element":
            # Repeating a name with different ids is how fallback locators are written:
            # `read_elements` gathers them into one list. Repeating the whole row is only
            # untidy: it runs the same, but a failed lookup retries those ids twice.
            repeated = Counter(value for _, _, value in entries)
            rows = [(u, r) for u, r, value in entries if repeated[value] > 1]
        else:
            rows = [(u, r) for u, r, _ in entries]

        if len(rows) < 2:
            continue

        code = f"duplicate-{kind.replace(' ', '-')}"
        for uri, row in rows:
            yield _diag(
                uri,
                row,
                WARNING,
                code,
                f"Duplicate {kind} {name!r}, see {_elsewhere(uri, row, rows)}",
            )


def _elsewhere(uri: str, row: int, rows: list[tuple[str, int]]) -> str:
    """The other rows carrying the same value, named as a person would look them up."""
    others: dict[str, list[int]] = defaultdict(list)
    for other_uri, other_row in rows:
        if (other_uri, other_row) != (uri, row):
            others[other_uri].append(other_row)

    parts = []
    # This file first, and named only when it is not this one.
    for other, lines in sorted(others.items(), key=lambda pair: pair[0] != uri):
        listed = ", ".join(str(line) for line in lines)
        where = f"line {listed}" if len(lines) == 1 else f"lines {listed}"
        parts.append(where if other == uri else f"{other.rsplit('/', 1)[-1]} {where}")
    return ", ".join(parts)


def _duplicate_errors(ast: AST) -> Iterator[_Keyed]:
    """`_load_error_definitions` merges every file into one dict keyed by code, so unlike
    elements these clash across files: a repeated code overwrites wherever it sits, and
    two rows matching the same text both fire on it."""
    for key, kind in ((attrgetter("code"), "error code"), (attrgetter("match"), "match string")):
        seen: dict[str, list[ErrorDefinition]] = defaultdict(list)
        for error in ast.error_definitions:
            if value := key(error):
                seen[value].append(error)

        for value, rows in seen.items():
            pairs = [(e.uri, e.row) for e in rows]
            for error in rows if len(rows) > 1 else ():
                yield _diag(
                    error.uri,
                    error.row,
                    WARNING,
                    f"duplicate-{kind.replace(' ', '-')}",
                    f"Duplicate {kind} {value!r}, see {_elsewhere(error.uri, error.row, pairs)}",
                )


def _incomplete_errors(ast: AST) -> Iterator[_Keyed]:
    """A row needs both columns; `read_error_definitions` silently drops it otherwise."""
    for error in ast.error_definitions:
        if not (error.code and error.match):
            missing = "error_code" if not error.code else "match_string"
            yield _diag(
                error.uri,
                error.row,
                WARNING,
                "error-definition-incomplete",
                f"Row has no {missing}, so it never matches",
            )


def declares_at(step_name: str | None, count: int) -> set[int]:
    """Which params of a step bind a name rather than read one."""
    where = _DECLARES.get(slug(step_name))
    return set(range(*where.indices(count))) if where else set()


def module_args(step_name: str | None, count: int) -> set[int]:
    """Which params of a step name a module to run, given how many it was given."""
    name = slug(step_name)
    if name in ("run loop", "execute module"):
        return {0}
    if name == "condition":
        # Condition, target pairs, with a bare else-target last when the count is odd.
        return set(range(1, count, 2)) | ({count - 1} if count % 2 else set())
    return set()


def runs_at(step_name: str | None, count: int) -> set[int]:
    """As `module_args`, plus a `Condition`'s own condition slots: each runs a module to
    ask whether it passed."""
    return set(range(count)) if slug(step_name) == "condition" else module_args(step_name, count)


def module_refs(ast: AST) -> Iterator[tuple[str, int, str]]:
    """Every place a module is named: a test case step, or a param that runs one."""
    for test_case in ast.test_cases:
        for step in test_case.steps:
            if step.step_name:
                yield test_case.uri, step.row, step.step_name

    for module in ast.modules:
        for step in module.steps:
            for i in module_args(step.step_name, len(step.params)):
                yield module.uri, step.row, step.params[i]


def module_conditions(ast: AST) -> Iterator[tuple[str, int, str]]:
    """`Condition` cells that name a module to run, with the `!` stripped as
    `_is_module_condition` strips it. Validation ignores these because a condition may be
    an expression instead, but the ones that do name a module are real call sites."""
    for module in ast.modules:
        for step in module.steps:
            if slug(step.step_name) != "condition":
                continue

            # Whatever is not a target is a condition, the bare else-target included.
            targets = module_args(step.step_name, len(step.params))
            for i, param in enumerate(step.params):
                if i not in targets:
                    yield module.uri, step.row, param.removeprefix("!").strip()


def _unknown_modules(ast: AST) -> Iterator[_Keyed]:
    # A ${name} is reported like any other: nothing substitutes it first. The runner
    # hands params to the keyword untouched, and `execute_module` indexes the dict raw.
    known = {b.name for b in ast.modules}

    for uri, row, name in module_refs(ast):
        if name not in known:
            yield _diag(
                uri,
                row,
                ERROR,
                "module-not-found",
                f"Module {name!r} not found",
            )


def declarations(ast: AST) -> Iterator[tuple[str, int, str]]:
    """Every place a name is bound at run time, as uri, row, name."""
    for module in ast.modules:
        for step in module.steps:
            where = _DECLARES.get(slug(step.step_name))
            if where is not None:
                for bound in step.params[where]:
                    if bound:
                        yield module.uri, step.row, _bare(bound)


def declared(ast: AST) -> set[str]:
    """Names bound at run time rather than defined in an elements csv."""
    return {name for _, _, name in declarations(ast)}


def substitutes_at(step_name: str | None, count: int) -> set[int]:
    """Which params the keyword substitutes `${refs}` *inside*.

    `resolve_param` looks a name up only when the whole cell is one `${name}`. These three
    keywords re-scan their own param and raise `E0702` on a missing name, so an embedded ref
    there is a real reference; anywhere else the keyword is handed the text verbatim.
    """
    name = slug(step_name)
    if name == "read data":
        return {2}  # the query — `_resolve_query_vars`
    if name == "evaluate":
        return {1}  # the expression — `_compute_expression`
    if name == "condition":
        # Whatever is not a target is a condition, and `_resolve_condition` substitutes it.
        return set(range(count)) - module_args(step_name, count)
    return set()


def element_refs(ast: AST) -> Iterator[tuple[str, int, str]]:
    """Every ${name} a module step actually resolves, as uri, row, name.

    Not the step-name cell: the runner looks that up in `keyword_map`, so a `${ref}` there is
    a missing keyword rather than a missing element.
    """
    for module in ast.modules:
        for step in module.steps:
            count = len(step.params)
            binds = declares_at(step.step_name, count)
            embeds = substitutes_at(step.step_name, count)

            for at, cell in enumerate(step.params):
                # A declaring keyword names its target, it does not reference it.
                if at in binds:
                    continue
                if whole := VAR.fullmatch(cell):
                    yield module.uri, step.row, whole.group(1)
                elif at in embeds:
                    for name in VAR.findall(cell):
                        yield module.uri, step.row, name


def undefined(ast: AST) -> set[str]:
    """Names read but never defined: what element-not-found reports."""
    known = {e.name for e in ast.elements} | declared(ast)
    return {name for _, _, name in element_refs(ast) if name not in known}


def _unknown_elements(ast: AST) -> Iterator[_Keyed]:
    known = {e.name for e in ast.elements} | declared(ast)

    for uri, row, name in element_refs(ast):
        if name not in known:
            yield _diag(
                uri,
                row,
                ERROR,
                "element-not-found",
                f"{name!r} is not a defined element or variable",
            )


def _unknown_steps(ast: AST, catalog: Catalog) -> Iterator[_Keyed]:
    # Raw names: `get_module_definition` is a plain dict lookup, so case matters.
    modules = {m.name for m in ast.modules}

    for module in ast.modules:
        for step in module.steps:
            if not step.step_name:
                continue

            # A step calls a keyword or, for nested modules, another module. Only the
            # keyword half is normalised: the runner looks a module up by its raw name.
            if step.step_name in modules:
                continue

            keyword = catalog.get(slug(step.step_name))
            if keyword is None:
                yield _diag(
                    module.uri,
                    step.row,
                    ERROR,
                    "keyword-not-found",
                    f"{step.step_name!r} is not a keyword or module",
                )
                continue

            given = len(step.params)
            most = None if keyword.variadic else len(keyword.params)
            if given < keyword.required or (most is not None and given > most):
                wanted = f"{keyword.required}+" if most is None else f"{keyword.required}-{most}"
                yield _diag(
                    module.uri,
                    step.row,
                    ERROR,
                    "keyword-arity",
                    f"{step.step_name!r} takes {wanted} params, got {given}",
                )


def validate(ast: AST, catalog: Catalog | None = None) -> dict[str, list[Finding]]:
    rules = [
        _hygiene,
        _duplicates,
        _unknown_modules,
        _unknown_elements,
        _duplicate_errors,
        _incomplete_errors,
    ]
    if catalog is not None:
        rules.append(partial(_unknown_steps, catalog=catalog))

    found: dict[str, list[Finding]] = defaultdict(list)
    for rule in rules:
        for uri, diagnostic in rule(ast):
            found[uri].append(diagnostic)
    return dict(found)
