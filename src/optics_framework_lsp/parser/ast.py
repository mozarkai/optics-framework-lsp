# Row numbers are 1-based

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Where something sits on its row, as (start, end) character offsets.
Span = tuple[int, int]

IssueKind = Literal[
    # A csv's shape. Two of these are inherently tabular; the third is not, but a
    # yaml file cannot have a whitespace-only line that means anything.
    "csv-whitespace-line",
    "csv-too-few-columns",
    "csv-too-many-columns",
    # A yaml's shape. Every one of these loads as silence rather than as an error:
    # the reader logs and carries on, so the run fails somewhere else entirely.
    "yaml-parse-error",
    "yaml-section-key-case",
    "yaml-section-shape",
    "yaml-step-not-a-string",
    # Raised by `_unresolved` rather than by the parser: only the catalog can tell
    # `Sleep 5`, which never runs, from `Launch App`, which is a real paramless keyword.
    "yaml-error-definitions-unread",
]


@dataclass(slots=True)
class SourceIssue:
    """One misshapen file, and where. The kind is also the diagnostic code a caller
    matches on, so these names are a contract and not free to reword."""

    uri: str
    row: int
    kind: IssueKind
    # What the row said, for the kinds whose message has to quote it back. The csv
    # kinds leave it empty: there the row's shape is the whole problem.
    detail: str = ""


@dataclass(slots=True)
class Locator:
    text: str
    # Where the cell sits in its row, so a symbol can point at it rather than at the
    # line: two locators on one row are otherwise indistinguishable to a client.
    start: int
    end: int
    # A csv row writes every locator on one line, but a yaml fallback list gives each
    # its own, so the line cannot be taken from the element.
    row: int


@dataclass(slots=True)
class Element:
    name: str
    # Every `element_id*` cell on the row: `read_elements` collects them all and tries
    # each in turn, so one row can carry an xpath and a text fallback.
    locators: list[Locator]
    uri: str
    row: int
    name_span: Span | None = None


@dataclass(slots=True)
class ErrorDefinition:
    # Either may be blank: `read_error_definitions` drops such a row, so we keep it to
    # report it rather than dropping it too.
    code: str
    match: str
    uri: str
    row: int


@dataclass(slots=True)
class Step:
    step_name: str | None
    row: int
    params: list[str] = field(default_factory=list)
    # Where the name and each param sit on `row`. The csv parser leaves these unset:
    # a cell's span is recoverable from the line, so its features re-scan it. A yaml
    # step is one scalar holding the keyword and its params together, with nothing to
    # re-scan, so the spans are recorded here as the file is read.
    name_span: Span | None = None
    param_spans: list[Span] = field(default_factory=list)
    # The scalar as written, when the keyword catalog split params off it. A module is
    # looked up by its whole raw name, so a module called `Sleep Well` has to be
    # recognisable after the catalog has claimed `Sleep` and left `Well` a param.
    raw: str | None = None


@dataclass(slots=True)
class Block:
    name: str
    uri: str
    start_row: int
    steps: list[Step] = field(default_factory=list)
    name_span: Span | None = None


@dataclass(slots=True)
class AST:
    # What each file's contents made it, by uri. A file missing from here matched none
    # of the kinds, so the framework ignores it too — and a caller needs to say so
    # rather than let a skipped file read as a clean one.
    #
    # Comma-separated, because a csv is one kind but a yaml may hold several sections.
    # A string rather than a set so `lint.report`'s `analyzed` keeps its shape on the
    # wire; read it with `kinds_of`.
    kinds: dict[str, str] = field(default_factory=dict)
    test_cases: list[Block] = field(default_factory=list)
    modules: list[Block] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    error_definitions: list[ErrorDefinition] = field(default_factory=list)
    issues: list[SourceIssue] = field(default_factory=list)


def kinds_of(ast: AST, uri: str) -> set[str]:
    """What one file was read as. Several, for a yaml holding several sections."""
    return {kind for kind in ast.kinds.get(uri, "").split(",") if kind}
