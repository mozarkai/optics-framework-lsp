# Rules turn an AST into LSP diagnostics, keyed by uri

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from functools import partial

from lsprotocol.types import Diagnostic, DiagnosticSeverity, Position, Range

from .keyword_catalog import Catalog
from .parser.ast import AST

SOURCE = "optics"

_VAR = re.compile(r"\$\{([^}]+)\}")

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
    seen: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for kind, name, uri, row in (
        [("test case", b.name, b.uri, b.start_row) for b in ast.test_cases]
        + [("module", b.name, b.uri, b.start_row) for b in ast.modules]
        + [("element", e.name, e.uri, e.row) for e in ast.elements]
    ):
        seen[(kind, name, uri)].append(row)

    for (kind, name, uri), rows in seen.items():
        if len(rows) < 2:
            continue

        severity = (
            DiagnosticSeverity.Error
            if kind == "element"
            else DiagnosticSeverity.Warning
        )
        code = f"duplicate-{kind.replace(' ', '-')}"

        for row in rows:
            yield _diag(uri, row, severity, code, f"Duplicate {kind} {name!r}")


def _unknown_modules(ast: AST) -> Iterator[_Finding]:
    known = {b.name for b in ast.modules}
    for test_case in ast.test_cases:
        for step in test_case.steps:
            if step.step_name and step.step_name not in known:
                yield _diag(
                    test_case.uri,
                    step.row,
                    DiagnosticSeverity.Error,
                    "module-not-found",
                    f"Module {step.step_name!r} not found",
                )


def declared(ast: AST) -> set[str]:
    """Names bound at run time rather than defined in an elements csv."""
    names = set()
    for module in ast.modules:
        for step in module.steps:
            where = _DECLARES.get((step.step_name or "").lower())
            if where is not None:
                names.update(_bare(d) for d in step.params[where] if d)
    return names


def _unknown_elements(ast: AST) -> Iterator[_Finding]:
    known = {e.name for e in ast.elements} | declared(ast)

    for module in ast.modules:
        for step in module.steps:
            # A declaring keyword names its target, it does not reference it.
            declares = (step.step_name or "").lower() in _DECLARES
            params = step.params[1:] if declares else step.params

            for text in (step.step_name or "", *params):
                for name in _VAR.findall(text):
                    if name not in known:
                        yield _diag(
                            module.uri,
                            step.row,
                            DiagnosticSeverity.Error,
                            "element-not-found",
                            f"{name!r} is not a defined element or variable",
                        )


def _unknown_steps(ast: AST, catalog: Catalog) -> Iterator[_Finding]:
    modules = {m.name.lower() for m in ast.modules}

    for module in ast.modules:
        for step in module.steps:
            if not step.step_name:
                continue

            # A step calls a keyword or, for nested modules, another module.
            name = step.step_name.lower()
            if name in modules:
                continue

            keyword = catalog.get(name)
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
    rules = [_hygiene, _duplicates, _unknown_modules, _unknown_elements]
    if catalog is not None:
        rules.append(partial(_unknown_steps, catalog=catalog))

    found: dict[str, list[Diagnostic]] = defaultdict(list)
    for rule in rules:
        for uri, diagnostic in rule(ast):
            found[uri].append(diagnostic)
    return dict(found)
