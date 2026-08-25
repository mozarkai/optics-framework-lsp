"""Semantic tokens: the column decides what a cell is."""

from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.tokens import LEGEND, tokens

CATALOG = {
    "press element": Keyword(1, False, ["element"]),
    "condition": Keyword(0, True, []),
    "sleep": Keyword(1, False, ["duration"]),
    "read data": Keyword(2, False, ["input_element", "file_path"]),
}
OTHER = "module_name,module_step\nHelper,Sleep\nLaunch App,Sleep\n"


def _marked(text: str, others: str = OTHER):
    """Every token as (line, the text it covers, its type), decoded back to absolutes."""
    ast = parse_csv_sources([("file:///w/m.csv", text), ("file:///w/o.csv", others)])
    data = tokens(text, ast, CATALOG)
    lines, out, line, char = text.splitlines(), [], 0, 0
    for i in range(0, len(data), 5):
        delta_line, delta_char, length, kind, _ = data[i : i + 5]
        line += delta_line
        char = delta_char if delta_line else char + delta_char
        out.append((line + 1, lines[line][char : char + length], LEGEND[kind]))
    return out


def _body(text: str, others: str = OTHER):
    """Only the rows, so a test does not have to count header tokens."""
    return [(line, covered, kind) for line, covered, kind in _marked(text, others) if line > 1]


def test_the_header_row_is_what_makes_the_file_a_kind():
    assert _marked("module_name,module_step\n") == [
        (1, "module_name", "keyword"),
        (1, "module_step", "keyword"),
    ]


def test_a_step_is_a_method_when_a_keyword_claims_it_and_a_module_otherwise():
    assert _body("module_name,module_step\nM,Press Element\nM,Helper\n") == [
        (2, "M", "function"),
        (2, "Press Element", "method"),
        (3, "M", "function"),
        (3, "Helper", "function"),
    ]


def test_a_module_named_after_a_keyword_still_reads_as_the_keyword():
    # `Launch App` is a module in the other file, but `sleep` is what the step names.
    assert _body("module_name,module_step\nM,Sleep\n")[-1] == (2, "Sleep", "method")


def test_every_variable_in_a_param_is_marked_and_the_rest_is_not():
    assert _body("module_name,module_step,param_1\nM,Condition,${a} == ${b}\n")[2:] == [
        (2, "${a}", "variable"),
        (2, "${b}", "variable"),
    ]


def test_a_module_run_by_a_param_reads_as_a_call():
    # This is the one invisible without tokens: a module name looks like any other cell.
    marked = _body("module_name,module_step,param_1,param_2\nM,Condition,${x},Helper\n")
    assert marked[-1] == (2, "Helper", "function")


def test_an_inverted_condition_marks_the_bang_apart_from_the_module():
    assert _body("module_name,module_step,param_1,param_2\nM,Condition,!Helper,Helper\n")[2:] == [
        (2, "!", "operator"),
        (2, "Helper", "function"),
        (2, "Helper", "function"),
    ]


def test_a_test_case_and_its_steps():
    assert _body("test_case,test_step\nTC,Helper\n") == [
        (2, "TC", "class"),
        (2, "Helper", "function"),
    ]


def test_elements_and_error_codes():
    assert _body("element_name,element_id\nbtn,//a\n") == [
        (2, "btn", "variable"),
        (2, "//a", "string"),
    ]
    assert _body("error_code,match_string\nE001,Crashed\n") == [
        (2, "E001", "enumMember"),
        (2, "Crashed", "string"),
    ]


def test_an_unrecognised_csv_gets_only_its_header():
    assert [t for _, _, t in _marked("device,os\nphone,android\n")] == ["keyword", "keyword"]


def test_a_quoted_cell_is_measured_from_the_line_not_the_value():
    assert _body('element_name,element_id\nbtn,"a,b"\n') == [
        (2, "btn", "variable"),
        (2, '"a,b"', "string"),
    ]


def test_a_data_file_and_an_api_identifier_are_strings():
    marked = _body(
        "module_name,module_step,param_1,param_2\n"
        "M,Read Data,row,data/users.csv\n"
        "M,Invoke Api,auth.login,\n"
    )
    assert marked[2:4] == [(2, "row", "variable"), (2, "data/users.csv", "string")]
    assert marked[-1] == (3, "auth.login", "string")


def test_the_name_read_data_binds_reads_like_the_uses_of_it():
    marked = _body("module_name,module_step,param_1,param_2\nM,Read Data,row,f.csv\nM,Sleep,${row}\n")
    assert [t for _, _, t in marked if t == "variable"] == ["variable", "variable"]


def test_a_run_loop_count_is_not_mistaken_for_a_bound_name():
    # `Run Loop` treats params after the target as name/iterable pairs, but the count
    # form writes a number there, which binds nothing and so is left unmarked.
    marked = _body("module_name,module_step,param_1,param_2\nM,Run Loop,Helper,3\n")
    assert [covered for _, covered, _ in marked] == ["M", "Run Loop", "Helper"]


def test_a_documented_value_is_an_enum_member():
    catalog = dict(CATALOG, scroll=Keyword(1, False, ["direction", "event_name"]))
    ast = parse_csv_sources([("file:///w/m.csv", ""), ("file:///w/o.csv", OTHER)])
    text = "module_name,module_step,param_1\nM,Scroll,down\n"
    data = tokens(text, ast, catalog)
    assert LEGEND[data[-2]] == "enumMember"


def test_a_framework_keyword_carries_the_defaultLibrary_modifier():
    ast = parse_csv_sources([("file:///w/o.csv", OTHER)])
    text = "module_name,module_step\nM,Press Element\nM,Helper\n"
    data = tokens(text, ast, CATALOG)

    # Five ints per token; the last of each is the modifier bitmask.
    mods = [data[i + 4] for i in range(0, len(data), 5)]
    kinds = [LEGEND[data[i + 3]] for i in range(0, len(data), 5)]
    assert (kinds[3], mods[3]) == ("method", 1), "a keyword belongs to the framework"
    assert (kinds[5], mods[5]) == ("function", 0), "a module belongs to the project"


def test_a_column_that_is_not_a_param_gets_no_token():
    """`read_modules` never hands that cell to the keyword, so it is inert text — and
    the param after it still counts as param 1, not param 2."""
    assert _body(
        "module_name,module_step,param_1,notes,param_2\n"
        "M,Read Data,serial,IGNORE ME,f.csv\n"
    ) == [
        (2, "M", "function"),
        (2, "Read Data", "method"),
        (2, "serial", "variable"),
        (2, "f.csv", "string"),
    ]
