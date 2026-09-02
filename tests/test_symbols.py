from lsprotocol.types import SymbolKind

from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.symbols import symbols, workspace_symbols

TESTS = "test_case,test_step\nTC One,Login\nTC One,Check\nTC Two,Login\n"
MODULES = "module_name,module_step,param_1,param_2\nLogin,Press Element,${btn},\nLogin,Enter Text,${f},admin\nCheck,Sleep,1,\n"
ELEMENTS = "element_name,element_id\nbtn,//a\nbtn,btn.png\nfield,//b\n"


def _outline(source: str):
    return symbols(parse_csv_sources([("file:///w/f.csv", source)]))


def _tree(source: str):
    return [(s.name, s.detail, [c.name for c in s.children]) for s in _outline(source)]


def test_a_test_step_is_a_child_of_its_test_case():
    assert _tree(TESTS) == [
        ("TC One", "2 steps", ["Login", "Check"]),
        ("TC Two", "1 step", ["Login"]),
    ]


def test_a_module_step_is_a_child_of_its_module():
    assert _tree(MODULES) == [
        ("Login", "2 steps", ["Press Element", "Enter Text"]),
        ("Check", "1 step", ["Sleep"]),
    ]


def test_a_step_shows_its_params_and_drops_the_blank_ones():
    (login, _) = _outline(MODULES)
    assert [c.detail for c in login.children] == ["${btn}", "${f}, admin"]


def test_every_locator_is_a_child_of_its_element():
    # `btn` is one element with two fallbacks, not two elements.
    assert _tree(ELEMENTS) == [
        ("btn", "2 locators", ["//a", "btn.png"]),
        ("field", "1 locator", ["//b"]),
    ]


def test_the_kinds_say_what_each_row_is():
    (case,) = _outline("test_case,test_step\nTC,Login\n")
    (module,) = _outline("module_name,module_step\nLogin,Sleep\n")
    (element,) = _outline("element_name,element_id\nbtn,//a\n")

    assert (case.kind, case.children[0].kind) == (SymbolKind.Class, SymbolKind.Method)
    assert (module.kind, module.children[0].kind) == (SymbolKind.Function, SymbolKind.Method)
    assert (element.kind, element.children[0].kind) == (SymbolKind.Variable, SymbolKind.String)


def test_a_parent_spans_its_children():
    (one, two) = _outline(TESTS)

    # Rows 2-3 of the file, so lines 1-2, ending just past the last.
    assert (one.range.start.line, one.range.end.line) == (1, 3)
    assert (two.range.start.line, two.range.end.line) == (3, 4)
    # A client requires every child to sit inside its parent.
    for child in one.children:
        assert one.range.start.line <= child.range.start.line < one.range.end.line
    # Jumping to a symbol lands on its first line.
    assert one.selection_range.start == one.range.start


def test_an_unrecognised_csv_has_no_outline():
    assert _outline("device,os\nphone,android\n") == []


MULTI = "Element_Name,Element_ID,Element_ID_text\nbtn,//a,Save\nbtn,btn.png,\n"


def test_several_locators_on_one_row_each_get_a_child():
    # The calendar sample writes an xpath and a text fallback side by side.
    (element,) = _outline(MULTI)
    assert element.detail == "3 locators"
    assert [c.name for c in element.children] == ["//a", "Save", "btn.png"]


def test_each_locator_points_at_its_own_cell():
    # Two cells on one row need distinct ranges, or a client may fold them into one.
    line = "btn,//a,Save\n"
    (element,) = _outline("Element_Name,Element_ID,Element_ID_text\n" + line)
    spans = [(c.range.start.character, c.range.end.character) for c in element.children]

    assert spans == [(4, 7), (8, 12)]
    assert [line[a:b] for a, b in spans] == ["//a", "Save"]
    # A cell begins and ends on its own row; only a block spans to the next line.
    for child in element.children:
        assert (child.range.start.line, child.range.end.line) == (1, 1)


def test_a_quoted_cell_with_padding_is_measured_from_its_text():
    row = 'btn,"[""00"",""01""]", btn.png \n'
    (element,) = _outline("Element_Name,Element_ID,Element_ID_2\n" + row)
    spans = [(c.range.start.character, c.range.end.character) for c in element.children]
    assert [row[a:b] for a, b in spans] == ['"[""00"",""01""]"', "btn.png"]


def _found(query: str):
    """The whole project, not one file: `workspace/symbol` has no document to start from."""
    ast = parse_csv_sources(
        [
            ("file:///w/test_cases/test_cases.csv", TESTS),
            ("file:///w/modules/modules.csv", MODULES),
            ("file:///w/elements/elements.csv", ELEMENTS),
        ]
    )
    return [
        (s.name, s.kind, s.container_name, s.location.uri, s.location.range.start.line)
        for s in workspace_symbols(ast, query)
    ]


def test_the_match_is_a_case_insensitive_substring():
    # A caller types what it remembers, which is rarely the whole name in the right case.
    assert _found("login") == [
        ("Login", SymbolKind.Function, "modules", "file:///w/modules/modules.csv", 1),
    ]
    assert [name for name, *_ in _found("tc")] == ["TC One", "TC Two"]
    assert [name for name, *_ in _found("FIELD")] == ["field"]


def test_an_empty_query_is_every_declaration():
    assert [name for name, *_ in _found("")] == [
        "TC One",
        "TC Two",
        "Login",
        "Check",
        "btn",
        "field",
    ]


def test_an_element_repeated_for_its_fallbacks_is_one_symbol():
    # `btn` has two locator rows. `read_elements` reads one element, so we report one.
    assert _found("btn") == [
        ("btn", SymbolKind.Variable, "elements", "file:///w/elements/elements.csv", 1),
    ]


def test_an_error_code_is_a_symbol():
    codes = "error_code,match_string\nAPP_CRASH,has stopped\n,orphaned\n"
    ast = parse_csv_sources([("file:///w/error_definitions.csv", codes)])
    # The blank code is a row validation reports, not a name anything can search for.
    assert [(s.name, s.kind) for s in workspace_symbols(ast, "")] == [
        ("APP_CRASH", SymbolKind.Constant)
    ]
