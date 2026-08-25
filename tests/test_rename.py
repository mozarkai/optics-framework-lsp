"""Renaming a name the project owns, across every file that writes it."""

from lsprotocol.types import Position

from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.rename import prepare, rename

M, T, E, X = (
    "file:///w/modules.csv",
    "file:///w/tests.csv",
    "file:///w/elements.csv",
    "file:///w/errors.csv",
)
MODULES = (
    "module_name,module_step,param_1,param_2\n"
    "Do Login,Press Element,${btn},\n"                 # 2
    "Do Login,Read Data,serial,f.csv\n"                # 3
    "Do Login,Press Element,${serial},\n"              # 4
    "Guard,Condition,!Do Login,Do Login\n"             # 5
    "Guard,Execute Module,Do Login,\n"                 # 6
    "Guard,Do Login,,\n"                               # 7
    "Sleep,Press Element,${btn},\n"                    # 8
    "Guard,Sleep,1,\n"                                 # 9
)
TESTS = "test_case,test_step\nTC One,Do Login\nTC One,Sleep\n"
ELEMENTS = "element_name,element_id\nbtn,//a\nbtn,btn.png\n"
ERRORS = "error_code,match_string\nE001,Crashed\nE002,Frozen\n"
ERRORS_IOS = "error_code,match_string\nE001,Sign in failed\n"
X2 = "file:///w/errors_ios.csv"
SOURCES = [(M, MODULES), (T, TESTS), (E, ELEMENTS), (X, ERRORS), (X2, ERRORS_IOS)]
CATALOG = {
    "press element": Keyword(1, False, ["element"]),
    "read data": Keyword(2, False, ["input_element", "file_path"]),
    "condition": Keyword(0, True, []),
    "execute module": Keyword(1, False, ["target"]),
    "sleep": Keyword(1, False, ["duration"]),
}


def _at(text: str, line: int, needle: str) -> Position:
    row = text.splitlines()[line - 1]
    return Position(line=line - 1, character=row.index(needle) + len(needle) - 1)


def _rename(text: str, line: int, needle: str, new: str = "NEW"):
    edits = rename(SOURCES, CATALOG, text, _at(text, line, needle), new)
    return sorted(
        (uri.rsplit("/", 1)[-1], e.range.start.line + 1, e.range.start.character, e.range.end.character)
        for uri, found in (edits or {}).items()
        for e in found
    )


def _applied(text: str, uri: str, line: int, needle: str, new: str = "NEW") -> str:
    """The file after the edits, so a test reads like the result rather than offsets."""
    edits = rename(SOURCES, CATALOG, text, _at(text, line, needle), new) or {}
    target = dict(SOURCES)[uri]
    lines = target.splitlines()
    for e in sorted(edits.get(uri, []), key=lambda e: -e.range.start.character):
        number = e.range.start.line
        row = lines[number]
        lines[number] = row[: e.range.start.character] + e.new_text + row[e.range.end.character :]
    return "\n".join(lines) + "\n"


def test_a_module_moves_in_every_file_and_every_shape():
    assert _applied(MODULES, M, 2, "Do Login", "Sign In") == (
        "module_name,module_step,param_1,param_2\n"
        "Sign In,Press Element,${btn},\n"
        "Sign In,Read Data,serial,f.csv\n"
        "Sign In,Press Element,${serial},\n"
        "Guard,Condition,!Sign In,Sign In\n"
        "Guard,Execute Module,Sign In,\n"
        "Guard,Sign In,,\n"
        "Sleep,Press Element,${btn},\n"
        "Guard,Sleep,1,\n"
    )
    assert _applied(MODULES, T, 2, "Do Login", "Sign In") == (
        "test_case,test_step\nTC One,Sign In\nTC One,Sleep\n"
    )


def test_the_bang_of_an_inverted_condition_stays_put():
    (_, line, start, end) = next(
        place for place in _rename(MODULES, 2, "Do Login") if place[1] == 5
    )
    assert MODULES.splitlines()[4][start:end] == "Do Login"


def test_a_module_named_after_a_keyword_is_not_renamed_where_the_keyword_runs():
    after = _applied(MODULES, M, 8, "Sleep", "Nap").splitlines()
    assert after[7] == "Nap,Press Element,${btn},", "its own definition moves"
    assert after[8] == "Guard,Sleep,1,", "but a step of that name runs the keyword"
    # A test step is always a module, never a keyword, so that one does move.
    assert _applied(MODULES, T, 8, "Sleep", "Nap").splitlines()[2] == "TC One,Nap"


def test_an_element_moves_inside_its_braces_only():
    assert _applied(MODULES, M, 2, "${btn}", "target") == (
        "module_name,module_step,param_1,param_2\n"
        "Do Login,Press Element,${target},\n"
        "Do Login,Read Data,serial,f.csv\n"
        "Do Login,Press Element,${serial},\n"
        "Guard,Condition,!Do Login,Do Login\n"
        "Guard,Execute Module,Do Login,\n"
        "Guard,Do Login,,\n"
        "Sleep,Press Element,${target},\n"
        "Guard,Sleep,1,\n"
    )
    assert _applied(MODULES, E, 2, "${btn}", "target") == (
        "element_name,element_id\ntarget,//a\ntarget,btn.png\n"
    )


def test_a_bound_variable_moves_with_its_binding():
    after = _applied(MODULES, M, 4, "${serial}", "row").splitlines()
    assert after[2] == "Do Login,Read Data,row,f.csv", "the Read Data cell that binds it"
    assert after[3] == "Do Login,Press Element,${row},", "and the use"


def test_a_test_case_and_an_error_code_move_in_place():
    assert _applied(TESTS, T, 2, "TC One", "Smoke") == (
        "test_case,test_step\nSmoke,Do Login\nSmoke,Sleep\n"
    )
    assert _applied(ERRORS, X, 2, "E001", "E999") == (
        "error_code,match_string\nE999,Crashed\nE002,Frozen\n"
    )


def test_an_error_code_defined_in_two_files_moves_in_both():
    # Nothing in the dsl references a code, but a second definitions file can repeat one
    # — and `_load_error_definitions` merges every file into one dict keyed by code.
    assert _applied(ERRORS, X, 2, "E001", "E999") == (
        "error_code,match_string\nE999,Crashed\nE002,Frozen\n"
    )
    assert _applied(ERRORS, X2, 2, "E001", "E999") == (
        "error_code,match_string\nE999,Sign in failed\n"
    )


def test_what_is_not_ours_to_rename():
    for text, line, needle in (
        (MODULES, 2, "Press Element"),  # a framework keyword
        (ELEMENTS, 2, "//a"),           # a locator
        (MODULES, 3, "f.csv"),          # a data file
        (ERRORS, 2, "Crashed"),         # a match string
    ):
        assert rename(SOURCES, CATALOG, text, _at(text, line, needle), "x") is None, needle
        assert prepare(text, _at(text, line, needle), CATALOG) is None, needle


def test_prepare_offers_the_name_without_its_braces():
    at = prepare(MODULES, _at(MODULES, 2, "${btn}"), CATALOG)
    row = MODULES.splitlines()[1]
    assert row[at.start.character : at.end.character] == "btn"


def test_a_ref_in_a_non_param_column_is_left_alone():
    """The keyword never receives that cell, so the ${btn} in it is not a reference."""
    modules = (
        "module_name,module_step,param_1,notes\n"
        "Do Login,Press Element,${btn},also ${btn}\n"
    )
    edits = rename(
        [(M, modules), (E, ELEMENTS)], CATALOG, ELEMENTS, _at(ELEMENTS, 2, "btn"), "NEW"
    )
    assert len(edits[M]) == 1
