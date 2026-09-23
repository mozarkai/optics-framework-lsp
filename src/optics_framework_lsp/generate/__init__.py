# One suite in, a native script out — and an honest account of what did not come across.
#
# The script talks to the device directly, so nothing optics does at run time is available
# to it: no vision fallback, no self-heal, no error-code detection. That is the trade, and
# `unsupported` is where the caller finds out what it cost them, per step, with file and row.
#
# What differs between targets lives in `targets/`; this module owns only what does not —
# walking the suite, resolving params, and collecting findings.

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .. import keywords as catalog
from ..parser import parse_sources
from ..parser.ast import AST, Block
from .targets import TARGETS

DEFAULT_TARGET = "uiautomator2"


def generate(files: list[tuple[str, str]], target: str = DEFAULT_TARGET) -> dict:
    """A suite as a script, plus every step that could not become one."""
    if target not in TARGETS:
        raise ValueError(f"unknown target: {target}; try one of {', '.join(sorted(TARGETS))}")
    backend = TARGETS[target]
    ast = parse_sources(files)
    findings: list[dict] = []

    elements, unusable = _elements(ast, backend, findings)
    modules = {block.name: block for block in ast.modules}
    bodies = [
        (block.name, _body(block, modules, elements, unusable, backend, findings))
        for block in modules.values()
    ]
    cases = [(block.name, _case(block, modules, backend, findings)) for block in ast.test_cases]

    return {
        "target": target,
        "extension": backend.EXTENSION,
        "source": backend.render(_config(files), elements, bodies, cases),
        "unsupported": sorted(findings, key=lambda f: (f["uri"], f["row"])),
    }


def _finding(uri: str, row: int, code: str, message: str) -> dict:
    return {"uri": uri, "row": row, "code": code, "message": message}


def _config(files: list[tuple[str, str]]) -> dict:
    """Serial, package and activity, read off the appium driver the suite configures."""
    for name, content in files:
        if Path(name).name.lower() not in ("config.yaml", "config.yml"):
            continue
        try:
            loaded = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            return {}
        for source in loaded.get("driver_sources") or []:
            caps = (source.get("appium") or {}).get("capabilities") or {}
            if caps:
                return {
                    "serial": caps.get("deviceName", ""),
                    "package": caps.get("appPackage", ""),
                    "activity": caps.get("appActivity", ""),
                }
    return {}


def _elements(ast: AST, backend, findings: list[dict]) -> tuple[dict[str, str], set[str]]:
    """Name to locator, the first definition winning as `resolve_with_fallback` tries them
    in order. A locator the target cannot express is reported here once, and its name
    returned so the steps that use it are reported too rather than emitting a broken call."""
    elements: dict[str, str] = {}
    unusable: set[str] = set()
    for element in ast.elements:
        if element.name in elements or not element.locators:
            continue
        locator = element.locators[0].text
        reason = backend.vet_locator(locator)
        if reason:
            unusable.add(element.name)
            findings.append(
                _finding(element.uri, element.row, "unusable-locator", f"'{element.name}' {reason}")
            )
            continue
        elements[element.name] = locator
    return elements, unusable


_REFERENCE = re.compile(r"\$\{([^}]+)\}")


def _param(raw: str, elements: dict[str, str], backend) -> str:
    """One param as an expression in the target's language: an element, a variable, or a
    literal."""
    match = _REFERENCE.fullmatch(raw.strip())
    if not match:
        return backend.literal(raw)
    key = match.group(1)
    return backend.element_ref(key) if key in elements else backend.var_ref(key)


def _body(
    block: Block, modules: dict[str, Block], elements, unusable, backend, findings
) -> list[str]:
    lines: list[str] = []
    for step in block.steps:
        lines += _step(step, block.uri, modules, elements, unusable, backend, findings)
    return lines


def _step(step, uri, modules, elements, unusable, backend, findings) -> list[str]:
    """One step as lines in the target's language, or nothing plus a finding saying why."""
    raw = (step.step_name or "").strip()
    keyword = raw.lower()

    # A step naming a module is a call to the method that module generated — the same
    # resolution `execute_module` does, done here instead.
    if keyword not in catalog.KEYWORDS:
        for name in modules:
            if name.strip().lower() == keyword:
                return [_call(backend, name)]
        findings.append(
            _finding(uri, step.row, "unknown-step", f"'{raw}' is neither a keyword nor a module")
        )
        return []

    if keyword in backend.UNSUPPORTED:
        findings.append(
            _finding(uri, step.row, "unsupported-keyword", f"'{raw}': {backend.UNSUPPORTED[keyword]}")
        )
        return []

    blocked = [
        match.group(1)
        for param in step.params
        for match in [_REFERENCE.fullmatch(param.strip())]
        if match and match.group(1) in unusable
    ]
    if blocked:
        findings.append(
            _finding(uri, step.row, "unusable-locator", f"'{raw}' needs {blocked[0]}, which has no query")
        )
        return []

    arity, emit = backend.EMIT[keyword]
    params = [_param(param, elements, backend) for param in step.params]
    if len(params) > arity:
        dropped = ", ".join(catalog.KEYWORDS[keyword]["params"][arity : len(params)])
        findings.append(
            _finding(
                uri, step.row, "params-dropped",
                f"'{raw}' translated without {dropped or 'its trailing params'}",
            )
        )
    try:
        return emit(params[:arity])
    except IndexError:
        findings.append(
            _finding(
                uri, step.row, "missing-params",
                f"'{raw}' needs {arity} params, got {len(params)}",
            )
        )
        return []


def _call(backend, name: str) -> str:
    """A module call, which is a function in python and a method in swift."""
    return f"{backend.func_name(name)}(d)" if backend.NAME == "uiautomator2" else f"{backend.func_name(name)}()"


def _case(block: Block, modules: dict[str, Block], backend, findings) -> list[str]:
    lines = []
    for step in block.steps:
        name = (step.step_name or "").strip()
        if any(name.lower() == module.strip().lower() for module in modules):
            lines.append(_call(backend, name))
        else:
            findings.append(
                _finding(block.uri, step.row, "unknown-module", f"'{name}' is not a module")
            )
    return lines


def as_text(body: dict) -> str:
    """The report for a person: one line per step that did not translate."""
    findings = body["unsupported"]
    lines = [f"{f['uri']}:{f['row']}: {f['code']}: {f['message']}" for f in findings]
    return "\n".join([*lines, f"{len(findings)} steps did not translate"])
