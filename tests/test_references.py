"""Find references: the inverse of goto-definition."""

from lsprotocol.types import Position

from optics_framework_lsp.completion import references
from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.parser.csv_parser import parse_csv_sources

T, M, M2, E, X = (
    "file:///w/tests.csv",
    "file:///w/modules.csv",
    "file:///w/more.csv",
    "file:///w/elements.csv",
    "file:///w/errors.csv",
)

TESTS = "test_case,test_step\nTC,Open App\nTC,Do Login\n"
MODULES = (
    "module_name,module_step,param_1,param_2,param_3\n"
    "Open App,Launch App,,\n"                       # 2
    "Do Login,Press Element,${login_btn},\n"        # 3
    "Do Login,Read Data,serial,data/users.csv\n"    # 4
    "Do Login,Press Element,${serial},\n"           # 5
    "Do Login,Invoke Api,auth.login,\n"             # 6
    "Guard,Execute Module,Do Login,\n"              # 7
    "Guard,Condition,!Do Login,Open App\n"          # 8
    "Extra,Condition,${x} == 1,Open App,Do Login\n" # 9
    "Launch App,Launch App,,\n"                     # 10
)
MORE = (
    "module_name,module_step,param_1\n"
    "Elsewhere,Execute Module,Do Login\n"           # 2
    "Nested,Do Login,\n"                            # 3
    "Nested,Launch App,\n"                          # 4
)
ELEMENTS = (
    "element_name,element_id,element_id_2\n"
    "login_btn,//a,\n"                              # 2
    "login_btn,login_btn.png,\n"                    # 3
    "other,//b,login_btn.png\n"                     # 4
)
ERRORS = "error_code,match_string\nE001,Crashed\n"

CATALOG = {
    "press element": Keyword(1, False, ["element"]),
    "launch app": Keyword(0, False, []),
    "read data": Keyword(2, False, ["input_element", "file_path"]),
    "invoke api": Keyword(1, False, ["api_identifier"]),
}


def _refs(uri: str, source: str, line: int, needle: str, *, declaration=False):
    """Ask at the middle of `needle` on that line, as a cursor would sit."""
    ast = parse_csv_sources(
        [(T, TESTS), (M, MODULES), (M2, MORE), (E, ELEMENTS), (X, ERRORS)]
    )
    row = source.splitlines()[line - 1]
    at = Position(line=line - 1, character=row.index(needle) + len(needle) - 1)
    found = references(source, at, ast, CATALOG, include_declaration=declaration)
    return [(f.uri.rsplit("/", 1)[-1], f.range.start.line + 1) for f in found]


# --- modules ---

def test_a_module_from_a_test_step():
    assert _refs(T, TESTS, 3, "Do Login") == [
        ("modules.csv", 7),
        ("modules.csv", 8),
        ("modules.csv", 9),
        ("more.csv", 2),
        ("more.csv", 3),
        ("tests.csv", 3),
    ]


def test_a_module_from_its_own_definition_row():
    # The natural place to ask: you are looking at the module and want its callers.
    assert _refs(M, MODULES, 3, "Do Login") == [
        ("modules.csv", 7),
        ("modules.csv", 8),
        ("modules.csv", 9),
        ("more.csv", 2),
        ("more.csv", 3),
        ("tests.csv", 3),
    ]


def test_including_the_declaration_adds_the_definition_row():
    assert _refs(M, MODULES, 3, "Do Login", declaration=True)[-1] == ("modules.csv", 3)


def test_an_inverted_module_condition_counts():
    # Row 8 asks "if Do Login fails"; `_is_module_condition` strips the bang and runs it,
    # so it is a call site even though validation cannot assume a condition is a module.
    assert ("modules.csv", 8) in _refs(M, MODULES, 8, "!Do Login")


def test_an_else_target_is_counted_once_not_twice():
    # Row 9 has three params, so the last is the bare else-target, not a condition.
    found = _refs(M, MODULES, 9, "Do Login")
    assert found.count(("modules.csv", 9)) == 1


def test_a_module_nobody_calls_has_no_references():
    assert _refs(M, MODULES, 7, "Guard") == []


# --- elements and bound variables ---

def test_an_element_from_a_param():
    assert _refs(M, MODULES, 3, "${login_btn}") == [("modules.csv", 3)]


def test_an_element_from_its_own_row_with_every_definition():
    found = _refs(E, ELEMENTS, 2, "login_btn", declaration=True)
    # Used once, defined twice: two locators for one name is the fallback pattern.
    assert found == [("modules.csv", 3), ("elements.csv", 2), ("elements.csv", 3)]


def test_a_read_data_variable_counts_its_binding_as_the_declaration():
    assert _refs(M, MODULES, 5, "${serial}", declaration=True) == [
        ("modules.csv", 5),
        ("modules.csv", 4),
    ]


# --- keywords ---

def test_a_keyword_lists_every_step_that_calls_it():
    assert _refs(M, MODULES, 3, "Press Element") == [
        ("modules.csv", 3),
        ("modules.csv", 5),
    ]


def test_a_keyword_has_no_declaration_to_add():
    plain = _refs(M, MODULES, 3, "Press Element")
    assert _refs(M, MODULES, 3, "Press Element", declaration=True) == plain


def test_a_nested_module_step_is_a_call_site():
    # `more.csv` line 3 runs `Do Login` as a step, not through Execute Module.
    assert ("more.csv", 3) in _refs(M2, MORE, 3, "Do Login")


def test_a_module_named_after_a_keyword_is_never_called_by_those_steps():
    # Row 10 defines a module `Launch App`, but every `Launch App` step runs the keyword:
    # `_execute_single_keyword` checks the keyword map before nested modules.
    assert _refs(M, MODULES, 10, "Launch App") == []
    # Asked as a keyword instead, those same cells are exactly what you want.
    assert ("more.csv", 4) in _refs(M2, MORE, 4, "Launch App")


# --- resources ---

def test_a_template_image_lists_the_element_rows_using_it():
    assert _refs(E, ELEMENTS, 3, "login_btn.png") == [
        ("elements.csv", 3),
        ("elements.csv", 4),
    ]


def test_an_image_in_a_second_locator_column_is_found_too():
    # Row 4 keeps the image in `element_id_2`; only the first cell used to be read.
    assert _refs(E, ELEMENTS, 4, "login_btn.png") == [
        ("elements.csv", 3),
        ("elements.csv", 4),
    ]


def test_an_xpath_is_not_a_shared_resource():
    assert _refs(E, ELEMENTS, 2, "//a") == []


def test_a_data_file_lists_every_read_data():
    assert _refs(M, MODULES, 4, "data/users.csv") == [("modules.csv", 4)]


def test_an_api_identifier_lists_every_invoke():
    assert _refs(M, MODULES, 6, "auth.login") == [("modules.csv", 6)]


# --- nothing to reference ---

def test_a_test_case_name_has_no_references():
    # Nothing in the dsl can run a test case: they are the root of the tree.
    assert _refs(T, TESTS, 2, "TC") == []


def test_an_error_code_has_no_references():
    # Matched against on-screen text at run time, never named from a csv.
    assert _refs(X, ERRORS, 2, "E001") == []
    assert _refs(X, ERRORS, 2, "Crashed") == []


def test_the_header_row_references_nothing():
    assert _refs(M, MODULES, 1, "module_step") == []
