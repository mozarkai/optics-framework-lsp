# Row numbers are 1-based

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CsvIssueKind = Literal[
    "whitespace-only-line",
    "too-few-columns",
    "too-many-columns",
]


@dataclass(slots=True)
class CsvIssue:
    uri: str
    row: int
    kind: CsvIssueKind


@dataclass(slots=True)
class Element:
    name: str
    value: str
    uri: str
    row: int


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


@dataclass(slots=True)
class Block:
    name: str
    uri: str
    start_row: int
    steps: list[Step] = field(default_factory=list)


@dataclass(slots=True)
class AST:
    test_cases: list[Block] = field(default_factory=list)
    modules: list[Block] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    error_definitions: list[ErrorDefinition] = field(default_factory=list)
    csv_issues: list[CsvIssue] = field(default_factory=list)
