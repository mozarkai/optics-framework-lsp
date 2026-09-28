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
from .locators import normalise
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

    # A script missing the steps that touch an element would pass while testing less than
    # the suite does, so none is written. An element nothing uses does not stop it.
    refused = any(f["code"] == "needs-unusable-element" for f in findings)
    return {
        "target": target,
        "extension": backend.EXTENSION,
        "source": None if refused else backend.render(_config(files), elements, bodies, cases),
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


def _elements(ast: AST, backend, findings: list[dict]) -> tuple[dict[str, list[str]], set[str]]:
    """Name to every locator the target can carry, in the order `resolve_with_fallback`
    tries them. One the target cannot express is dropped and reported; an element left with
    none is returned as unusable, so the steps that use it are reported too rather than
    emitting a broken call."""
    # A name on several rows is one element: `read_elements` extends its list per row.
    rows: dict[str, list] = {}
    for element in ast.elements:
        rows.setdefault(element.name, []).append(element)

    elements: dict[str, list[str]] = {}
    unusable: set[str] = set()
    for name, group in rows.items():
        element = group[0]
        cells = [(row.uri, cell) for row in group for cell in row.locators]
        if not cells:
            continue
        kept, dropped = [], []
        for uri, cell in cells:
            # Normalised first: `text=` and `xpath=` are the framework's prefixes rather than
            # part of what is on screen, and a class is the node test of the path that finds it.
            locator = normalise(cell.text)
            reason = backend.vet_locator(locator)
            if reason:
                dropped.append((uri, cell, reason))
            elif locator not in kept:
                kept.append(locator)
        if not kept:
            unusable.add(name)
            reasons = "; ".join(f"{cell.text} {reason}" for _, cell, reason in dropped)
            finding = _finding(
                element.uri, element.row, "unusable-locator",
                f"'{name}' has no locator this target can use: {reasons}",
            )
            finding["element"] = name
            finding["locators"] = [[cell.text, reason] for _, cell, reason in dropped]
            findings.append(finding)
            continue
        for uri, cell, reason in dropped:
            findings.append(
                _finding(
                    uri, cell.row, "locator-dropped",
                    f"'{name}' keeps {len(kept)} locator(s) but not {cell.text}, which {reason}",
                )
            )
        elements[name] = kept
    return elements, unusable


_REFERENCE = re.compile(r"\$\{([^}]+)\}")


def _param(raw: str, elements: dict[str, list[str]], backend) -> str:
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

    # A whole cell only, as the runner resolves one: `${a}|${b}` is a literal there too.
    blocked = [
        match.group(1)
        for param in step.params
        for match in [_REFERENCE.fullmatch(param.strip())]
        if match and match.group(1) in unusable
    ]
    if blocked:
        finding = _finding(
            uri, step.row, "needs-unusable-element",
            f"'{raw}' needs {', '.join(blocked)}, which has no usable locator",
        )
        finding["step"] = raw
        finding["elements"] = blocked
        findings.append(finding)
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
    """The report for a person: one line per step that did not translate, or, when no script
    was written, which elements stopped it, why each of their locators was refused, and
    which steps needed them."""
    findings = body["unsupported"]
    line = lambda f: f"{f['uri']}:{f['row']}: {f['code']}: {f['message']}"
    if body["source"] is not None:
        return "\n".join([*map(line, findings), f"{len(findings)} steps did not translate"])

    needed: dict[str, list[dict]] = {}
    for f in findings:
        for name in f.get("elements", []):
            needed.setdefault(name, []).append(f)
    blocking = [f for f in findings if f["code"] == "unusable-locator" and f["element"] in needed]
    steps = sum(len(v) for v in needed.values())

    out = [
        f"error: no script written. {len(blocking)} element(s) have no locator the "
        f"{body['target']} target can use, and {steps} step(s) need them.",
    ]
    for f in blocking:
        out += ["", f"  {f['element']}  ({f['uri']}:{f['row']})"]
        width = max(len("needed by"), *(len(text) for text, _ in f["locators"]))
        out += [f"    {text:<{width}}  {reason}" for text, reason in f["locators"]]
        out += [
            f"    {'needed by' if i == 0 else '':<{width}}  {u['uri']}:{u['row']}  {u['step']}"
            for i, u in enumerate(needed[f["element"]])
        ]
    out += [
        "",
        "Give each an xpath, text or class locator (a fallback on another row is enough), "
        "or remove the steps that use it.",
    ]
    rest = [f for f in findings if f not in blocking and f["code"] != "needs-unusable-element"]
    if rest:
        out += ["", "Also not translatable, though these alone would not have stopped the script:"]
        out += [f"  {line(f)}" for f in rest]
    return "\n".join(out)
