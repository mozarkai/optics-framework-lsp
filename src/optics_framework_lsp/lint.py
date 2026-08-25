# One suite in, every finding out.
#
# This exists because a caller validating an upload needs a *complete* answer, and LSP push
# diagnostics never say "that is all of them". Editors get the same rules over the protocol.
#
# Imports nothing from `lsprotocol` or `pygls` — that is the point, and a test enforces it:
# `import lsprotocol.types` alone costs ~290ms, which a per-call process would pay every time.

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .keyword_catalog import CATALOG, Catalog
from .parser.csv_parser import parse_csv_sources
from .validation import ERROR, SOURCE, WARNING, validate

_SEVERITY = {ERROR: "error", WARNING: "warning"}


def report(files: list[tuple[str, str]], catalog: Catalog | None = CATALOG) -> dict:
    """Every finding for one suite, as a caller wants it on the wire.

    Findings are sorted by (file, row) so a caller need not re-sort, and `row` is 1-based
    while `range` is 0-based — the two conventions callers ask for.
    """
    sources = [(name, text) for name, text in files if name.lower().endswith(".csv")]
    ast = parse_csv_sources(sources)

    diagnostics = sorted(
        (
            {
                "uri": uri,
                "severity": _SEVERITY[finding.severity],
                "code": finding.code,
                "message": finding.message,
                "row": finding.row,
                "range": {
                    "startLine": finding.line,
                    "startColumn": 0,
                    "endLine": finding.line + 1,
                    "endColumn": 0,
                },
                "source": SOURCE,
            }
            for uri, findings in validate(ast, catalog).items()
            for finding in findings
        ),
        key=lambda diagnostic: (diagnostic["uri"], diagnostic["row"]),
    )

    return {
        # A summary of the list, not a decision: which severities block is the caller's policy.
        "status": "FAIL" if any(d["severity"] == "error" for d in diagnostics) else "PASS",
        # What each file's header made it, and everything we could not read. Without the
        # second, a file the framework also ignores is indistinguishable from a clean one.
        "analyzed": ast.kinds,
        "skipped": sorted(name for name, _ in files if name not in ast.kinds),
        "diagnostics": diagnostics,
    }


def walk(root: Path) -> list[tuple[str, str]]:
    """Every csv under `root`, named relative to it so two files of the same basename in
    different folders stay distinct.

    Dot folders are skipped, the same rule the server applies: a project's `.venv` holds
    optics-framework's own sample csvs, which would invent names the project does not have.
    """
    found = []
    for parent, folders, files in root.walk():
        folders[:] = sorted(folder for folder in folders if not folder.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(".csv"):
                path = parent / name
                found.append((str(path.relative_to(root)), path.read_text(errors="replace")))
    return found


def as_text(body: dict) -> str:
    """The report for a person rather than a caller: one line per finding, then a summary."""
    counts = Counter(d["severity"] for d in body["diagnostics"])
    summary = (
        f"{body['status']}  {len(body['analyzed'])} files analysed, "
        f"{counts['error']} errors, {counts['warning']} warnings"
    )
    if body["skipped"]:
        summary += f"  ({len(body['skipped'])} skipped: {', '.join(body['skipped'])})"

    lines = [
        f"{d['uri']}:{d['row']}: {d['severity']}: {d['code']}: {d['message']}"
        for d in body["diagnostics"]
    ]
    return "\n".join([*lines, summary])
