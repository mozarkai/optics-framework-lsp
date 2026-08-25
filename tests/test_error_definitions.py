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


def test_an_empty_csv_offers_the_four_header_sets():
    offered = _headers("")
    assert [detail for _, detail, _ in offered] == [
        "test cases",
        "modules",
        "elements",
        "error definitions",
    ]
    assert {kind for _, _, kind in offered} == {CompletionItemKind.Struct}


def test_the_elements_header_keeps_the_case_the_framework_reads():
    # `read_elements` does row.get("Element_Name"), so a lowercase header loads nothing.
    assert ("Element_Name,Element_ID", "elements", CompletionItemKind.Struct) in _headers("")


def test_the_modules_header_carries_the_five_params_real_projects_write():
    labels = [label for label, _, _ in _headers("")]
    assert "module_name,module_step,param_1,param_2,param_3,param_4,param_5" in labels


def test_a_partly_typed_header_still_offers_them():
    assert len(_headers("err", 3)) == 4


def test_a_file_that_already_has_rows_does_not():
    assert _headers("test_case,test_step\nTC,Login\n") != []
    assert not any(detail == "modules" for _, detail, _ in _headers("test_case,test_step\nTC,Login\n"))


def test_only_the_first_column_offers_a_header():
    # Past the first comma a header set would nest inside itself: `test_case,test_case,…`.
    assert _headers("test_case,", len("test_case,")) == []


def test_two_rows_matching_the_same_text_both_fire():
    body = "E001,Crashed,,\nE002,Crashed,,\nE003,Timed out,,\n"
    assert _codes(body) == [
        (2, "duplicate-match-string"),
        (3, "duplicate-match-string"),
    ]
    (first, second) = validate(_ast(body))[URI]
    # Each row names the others, so a clash is one hop away rather than a hunt.
    assert first.message == "Duplicate match string 'Crashed', see line 3"
    assert second.message == "Duplicate match string 'Crashed', see line 2"
    assert first.severity == DiagnosticSeverity.Warning


def _across_files(a: str, b: str):
    ast = parse_csv_sources([(URI, HEADER + a), (OTHER, HEADER + b)])
    found = validate(ast)
    return {uri.rsplit("/", 1)[-1]: [d.code for d in ds] for uri, ds in found.items()}


def test_three_rows_name_the_other_two():
    body = "E001,Crashed,,\nE002,Crashed,,\nE003,Crashed,,\n"
    assert [d.message.split("see ")[1] for d in validate(_ast(body))[URI]] == [
        "lines 3, 4",
        "lines 2, 4",
        "lines 2, 3",
    ]


def test_a_row_in_another_file_is_named_with_its_file():
    ast = parse_csv_sources([(URI, HEADER + "E001,Crashed,,\n"), (OTHER, HEADER + "E001,Frozen,,\n")])
    found = validate(ast)
    assert found[URI][0].message.endswith("see more_errors.csv line 2")
    assert found[OTHER][0].message.endswith("see error_definitions.csv line 2")


def test_a_code_repeated_in_another_file_still_overwrites():
    # `_load_error_definitions` merges every file into one dict keyed by code, so unlike
    # elements these clash across files.
    assert _across_files("E001,Crashed,,\n", "E001,Frozen,,\n") == {
        "error_definitions.csv": ["duplicate-error-code"],
        "more_errors.csv": ["duplicate-error-code"],
    }


def test_a_match_string_repeated_in_another_file_is_reported_too():
    assert _across_files("E001,Crashed,,\n", "E002,Crashed,,\n") == {
        "error_definitions.csv": ["duplicate-match-string"],
        "more_errors.csv": ["duplicate-match-string"],
    }


def test_an_element_name_in_two_files_is_still_fine():
    # Elements merge into a list, so sharing a name across files is the ard/ios pattern.
    two = parse_csv_sources([
        ("file:///w/ard.csv", "element_name,element_id\nbtn,//a\n"),
        ("file:///w/ios.csv", "element_name,element_id\nbtn,//b\n"),
    ])
    assert validate(two) == {}
