"""The fourth csv kind `_identify_csv_content` accepts: error_code + match_string."""

from lsprotocol.types import CompletionItemKind, DiagnosticSeverity, Position, SymbolKind

from optics_framework_lsp.completion import complete
from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.symbols import symbols
from optics_framework_lsp.validation import validate

URI = "file:///w/error_definitions.csv"
OTHER = "file:///w/more_errors.csv"
HEADER = "error_code,match_string,description,severity\n"


def _ast(body: str):
    return parse_csv_sources([(URI, HEADER + body)])


def _codes(body: str):
    return [(d.row, d.code) for d in validate(_ast(body)).get(URI, [])]


def test_the_file_is_recognised_at_all():
    (one,) = _ast("E001,Crashed,App died,high\n").error_definitions
    assert (one.code, one.match, one.row) == ("E001", "Crashed", 2)


def test_a_clean_file_says_nothing():
    assert _codes("E001,Crashed,,\nE002,Timed out,,\n") == []


def test_a_repeated_code_is_a_warning():
    # `read_error_definitions` keys its dict by code, so the second row wins silently.
    body = "E001,Crashed,,\nE002,Timed out,,\nE001,Also crashed,,\n"
    assert _codes(body) == [(2, "duplicate-error-code"), (4, "duplicate-error-code")]
    assert all(d.severity == DiagnosticSeverity.Warning for d in validate(_ast(body))[URI])


def test_a_row_missing_either_column_never_matches():
    body = "E001,,No match string,\n,orphan,,\n"
    assert _codes(body) == [
        (2, "error-definition-incomplete"),
        (3, "error-definition-incomplete"),
    ]
    messages = [d.message for d in validate(_ast(body))[URI]]
    assert messages == [
        "Row has no match_string, so it never matches",
        "Row has no error_code, so it never matches",
    ]


def test_recognising_the_file_turns_on_the_csv_hygiene_checks():
    # An unrecognised csv is skipped before these run, so this only works now.
    assert _codes("E001,Crashed,,\n   \nE002,Timed out,,,extra\n") == [
        (3, "csv-whitespace-line"),
        (4, "csv-too-many-columns"),
    ]


def test_each_code_is_a_symbol_showing_what_it_matches():
    found = symbols(_ast("E001,Crashed,App died,high\nE002,Timed out,,low\n"))
    assert [(s.name, s.kind, s.detail) for s in found] == [
        ("E001", SymbolKind.Constant, "Crashed"),
        ("E002", SymbolKind.Constant, "Timed out"),
    ]


def test_a_row_with_no_code_is_not_a_symbol():
    assert symbols(_ast(",orphan,,\n")) == []


def _headers(text: str, character: int = 0):
    items = complete(text, Position(line=0, character=character), parse_csv_sources([]), None)
    return [(i.label, i.detail, i.kind) for i in items]


