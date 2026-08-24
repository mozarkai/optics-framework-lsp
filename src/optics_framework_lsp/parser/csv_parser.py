# File kind comes from headers, not filename

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from .ast import AST, Block, CsvIssue, Element, ErrorDefinition, Locator, Step

_Row = tuple[list[str], int]


def _parse_rows(content: str) -> tuple[list[_Row], list[_Row], list[str]]:
    # `csv.reader` is already lenient about stray quotes and column counts.
    text = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.reader(io.StringIO(text, newline=""))

    rows: list[_Row] = []
    blank_rows: list[_Row] = []

    for cells in reader:
        target = blank_rows if all(c.strip() == "" for c in cells) else rows
        target.append((cells, reader.line_num))

    return rows, blank_rows, text.split("\n")


def _spans(line: str) -> list[tuple[int, int]]:
    """Where each field's text sits in its line, quotes and padding trimmed off."""
    spans, quoted, start = [], False, 0
    # The added comma flushes the last field without needing a second pass.
    for i, char in enumerate(line + ","):
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            text = line[start:i]
            spans.append((start + len(text) - len(text.lstrip()), start + len(text.rstrip())))
            start = i + 1
    return spans


def _cell(values: list[str], i: int) -> str | None:
    return (values[i] if i < len(values) else "") or None


def parse_csv_sources(files: Iterable[tuple[str, str]]) -> AST:
    ast = AST()

    for uri, content in files:
        rows, blank_rows, lines = _parse_rows(content)
        if not rows:
            continue

        (header_cells, _), *body = rows
        # Lowercased, as `read_csv_headers` does: the shipped samples all write
        # `Element_Name,Element_ID`, and classification is case-insensitive.
        headers = [h.strip().lower() for h in header_cells]

        is_test_case_csv = "test_case" in headers and "test_step" in headers
        is_module_csv = "module_name" in headers and "module_step" in headers
        is_element_csv = "element_name" in headers and "element_id" in headers
        is_error_csv = "error_code" in headers and "match_string" in headers

        # Unrecognised CSVs (test data, device caps) have schemas we don't know.
        if not (is_test_case_csv or is_module_csv or is_element_csv or is_error_csv):
            continue

        # Empty line is fine; whitespace-only is not.
        for cells, row in blank_rows:
            if any(c != "" for c in cells):
                ast.csv_issues.append(
                    CsvIssue(uri=uri, row=row, kind="whitespace-only-line")
                )

        # Rows sharing a name are one block wherever they sit: `read_test_cases` and
        # `read_modules` key by name, so rows split by another block still merge.
        current_test_case: Block | None = None
        current_module: Block | None = None
        test_cases: dict[str, Block] = {}
        modules: dict[str, Block] = {}

        for cells, row in body:
            values = [v.strip() for v in cells]

            if len(values) < 2:
                ast.csv_issues.append(
                    CsvIssue(uri=uri, row=row, kind="too-few-columns")
                )
                continue

            if len(values) > len(headers):
                ast.csv_issues.append(
                    CsvIssue(uri=uri, row=row, kind="too-many-columns")
                )

            if is_test_case_csv:
                name = _cell(values, headers.index("test_case"))
                step = _cell(values, headers.index("test_step"))

                # An unnamed row continues the block above it.
                if name and name not in test_cases:
                    test_cases[name] = Block(name=name, uri=uri, start_row=row)
                    ast.test_cases.append(test_cases[name])
                current_test_case = test_cases.get(name, current_test_case)

                if current_test_case is not None:
                    current_test_case.steps.append(Step(step_name=step, row=row))

            if is_module_csv:
                step_index = headers.index("module_step")
                name = _cell(values, headers.index("module_name"))
                step_name = _cell(values, step_index)

                if name and name not in modules:
                    modules[name] = Block(name=name, uri=uri, start_row=row)
                    ast.modules.append(modules[name])
                current_module = modules.get(name, current_module)

                if current_module is not None:
                    current_module.steps.append(
                        Step(step_name=step_name, row=row, params=values[step_index + 1 :])
                    )

            if is_element_csv:
                name = _cell(values, headers.index("element_name"))
                # Every `element_id*` column holds a locator, and `read_elements` keeps
                # them all: a row can carry an xpath and a text fallback side by side.
                spans = _spans(lines[row - 1] if row <= len(lines) else "")
                locators = [
                    Locator(cell, *(spans[i] if i < len(spans) else (0, 0)))
                    for i, header in enumerate(headers)
                    if header.startswith("element_id") and (cell := _cell(values, i))
                ]

                if name is None or not locators:
                    continue

                ast.elements.append(
                    Element(name=name, locators=locators, uri=uri, row=row)
                )

            if is_error_csv:
                code = _cell(values, headers.index("error_code")) or ""
                match = _cell(values, headers.index("match_string")) or ""
                if code or match:
                    ast.error_definitions.append(
                        ErrorDefinition(code=code, match=match, uri=uri, row=row)
                    )

    return ast
