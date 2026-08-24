# Rules turn an AST into LSP diagnostics, keyed by uri

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from functools import partial
from operator import attrgetter

from lsprotocol.types import Diagnostic, DiagnosticSeverity, Position, Range

from .keyword_catalog import Catalog, slug
from .parser.ast import AST, ErrorDefinition

SOURCE = "optics"

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
        DiagnosticSeverity.Warning,
        "csv-whitespace-line",
        "Whitespace-only line",
    ),
    "too-few-columns": (
        DiagnosticSeverity.Error,
        "csv-too-few-columns",
        "Row has fewer than 2 columns",
    ),
    "too-many-columns": (
        DiagnosticSeverity.Warning,
        "csv-too-many-columns",
        "Row has more columns than the header",
    ),
}

_Finding = tuple[str, Diagnostic]


def _diag(
    uri: str, row: int, severity: DiagnosticSeverity, code: str, message: str
) -> _Finding:
    line = max(row - 1, 0)
    return uri, Diagnostic(
        range=Range(
            start=Position(line=line, character=0),
            end=Position(line=line + 1, character=0),
        ),
        message=message,
        severity=severity,
        code=code,
        source=SOURCE,
    )


def _hygiene(ast: AST) -> Iterator[_Finding]:
    for issue in ast.csv_issues:
        severity, code, message = _CSV_ISSUES[issue.kind]
        yield _diag(issue.uri, issue.row, severity, code, message)


def _duplicates(ast: AST) -> Iterator[_Finding]:
    # Same name in two files is how platform variants (ard/ios) coexist, so only a
    # single file redefining a name is a problem.
    seen: dict[tuple[str, str, str], list[tuple[int, str | None]]] = defaultdict(list)
    for kind, name, uri, row, value in (
        [("test case", b.name, b.uri, b.start_row, None) for b in ast.test_cases]
        + [("module", b.name, b.uri, b.start_row, None) for b in ast.modules]
        + [("element", e.name, e.uri, e.row, e.value) for e in ast.elements]
    ):
        seen[(kind, name, uri)].append((row, value))

    for (kind, name, uri), entries in seen.items():
        if kind == "element":
            # Repeating a name with different ids is how fallback locators are written:
            # `read_elements` gathers them into one list. Repeating the same id is only
            # untidy: it runs the same, but a failed lookup retries that id twice.
            repeated = Counter(value for _, value in entries)
            rows = [row for row, value in entries if repeated[value] > 1]
        else:
            rows = [row for row, _ in entries]

        if len(rows) < 2:
            continue

        code = f"duplicate-{kind.replace(' ', '-')}"
        for row in rows:
            yield _diag(
                uri, row, DiagnosticSeverity.Warning, code, f"Duplicate {kind} {name!r}"
            )


def _elsewhere(error: ErrorDefinition, rows: list[ErrorDefinition]) -> str:
    """The other rows carrying the same value, named as a person would look them up."""
    others: dict[str, list[int]] = defaultdict(list)
    for other in rows:
        if other is not error:
            others[other.uri].append(other.row)

    parts = []
    # This file first, and named only when it is not this one.
    for uri, lines in sorted(others.items(), key=lambda pair: pair[0] != error.uri):
        listed = ", ".join(str(line) for line in lines)
        where = f"line {listed}" if len(lines) == 1 else f"lines {listed}"
        parts.append(where if uri == error.uri else f"{uri.rsplit('/', 1)[-1]} {where}")
    return ", ".join(parts)


def _duplicate_errors(ast: AST) -> Iterator[_Finding]:
    """`_load_error_definitions` merges every file into one dict keyed by code, so unlike
    elements these clash across files: a repeated code overwrites wherever it sits, and
    two rows matching the same text both fire on it."""
    for key, kind in ((attrgetter("code"), "error code"), (attrgetter("match"), "match string")):
        seen: dict[str, list[ErrorDefinition]] = defaultdict(list)
        for error in ast.error_definitions:
            if value := key(error):
                seen[value].append(error)

        for value, rows in seen.items():
            for error in rows if len(rows) > 1 else ():
                yield _diag(
                    error.uri,
                    error.row,
                    DiagnosticSeverity.Warning,
                    f"duplicate-{kind.replace(' ', '-')}",
                    f"Duplicate {kind} {value!r}, see {_elsewhere(error, rows)}",
                )


def _incomplete_errors(ast: AST) -> Iterator[_Finding]:
    """A row needs both columns; `read_error_definitions` silently drops it otherwise."""
    for error in ast.error_definitions:
        if not (error.code and error.match):
            missing = "error_code" if not error.code else "match_string"
            yield _diag(
                error.uri,
                error.row,
                DiagnosticSeverity.Warning,
                "error-definition-incomplete",
                f"Row has no {missing}, so it never matches",
            )


def _module_args(step_name: str | None, count: int) -> set[int]:
    """Which params of a step name a module to run, given how many it was given."""
    name = slug(step_name)
    if name in ("run loop", "execute module"):
        return {0}
    if name == "condition":
        # Condition, target pairs, with a bare else-target last when the count is odd.
        return set(range(1, count, 2)) | ({count - 1} if count % 2 else set())
    return set()


def _module_refs(ast: AST) -> Iterator[tuple[str, int, str]]:
    """Every place a module is named: a test case step, or a param that runs one."""
    for test_case in ast.test_cases:
        for step in test_case.steps:
            if step.step_name:
                yield test_case.uri, step.row, step.step_name

    for module in ast.modules:
        for step in module.steps:
            # Blank cells are dropped by `read_modules`, so they do not hold a place.
            params = [p for p in step.params if p]
            for i in _module_args(step.step_name, len(params)):
                yield module.uri, step.row, params[i]


def _unknown_modules(ast: AST) -> Iterator[_Finding]:
    # A ${name} is reported like any other: nothing substitutes it first. The runner
    # hands params to the keyword untouched, and `execute_module` indexes the dict raw.
    known = {b.name for b in ast.modules}

    for uri, row, name in _module_refs(ast):
        if name not in known:
            yield _diag(
                uri,
                row,
                DiagnosticSeverity.Error,
                "module-not-found",
                f"Module {name!r} not found",
            )


def declared(ast: AST) -> set[str]:
    """Names bound at run time rather than defined in an elements csv."""
    names = set()
    for module in ast.modules:
        for step in module.steps:
            where = _DECLARES.get(slug(step.step_name))
            if where is not None:
                names.update(_bare(d) for d in step.params[where] if d)
    return names


def _references(ast: AST) -> Iterator[tuple[str, int, str]]:
    """Every ${name} a module step reads, as uri, row, name."""
    for module in ast.modules:
        for step in module.steps:
            # A declaring keyword names its target, it does not reference it.
            declares = slug(step.step_name) in _DECLARES
            params = step.params[1:] if declares else step.params

            for text in (step.step_name or "", *params):
                for name in VAR.findall(text):
                    yield module.uri, step.row, name


def undefined(ast: AST) -> set[str]:
    """Names read but never defined: what element-not-found reports."""
    known = {e.name for e in ast.elements} | declared(ast)
    return {name for _, _, name in _references(ast) if name not in known}


def _unknown_elements(ast: AST) -> Iterator[_Finding]:
    known = {e.name for e in ast.elements} | declared(ast)

    for uri, row, name in _references(ast):
        if name not in known:
            yield _diag(
                uri,
                row,
                DiagnosticSeverity.Error,
                "element-not-found",
                f"{name!r} is not a defined element or variable",
            )


def _unknown_steps(ast: AST, catalog: Catalog) -> Iterator[_Finding]:
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
                    DiagnosticSeverity.Error,
                    "keyword-not-found",
                    f"{step.step_name!r} is not a keyword or module",
                )
                continue

            # Trailing commas pad rows out, so blank params are not arguments.
            given = len([p for p in step.params if p])
            most = None if keyword.variadic else len(keyword.params)
            if given < keyword.required or (most is not None and given > most):
                wanted = f"{keyword.required}+" if most is None else f"{keyword.required}-{most}"
                yield _diag(
                    module.uri,
                    step.row,
                    DiagnosticSeverity.Error,
                    "keyword-arity",
                    f"{step.step_name!r} takes {wanted} params, got {given}",
                )


def validate(ast: AST, catalog: Catalog | None = None) -> dict[str, list[Diagnostic]]:
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

    found: dict[str, list[Diagnostic]] = defaultdict(list)
    for rule in rules:
        for uri, diagnostic in rule(ast):
            found[uri].append(diagnostic)
    return dict(found)
