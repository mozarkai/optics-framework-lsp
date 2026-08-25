import pytest
from lsprotocol.types import CompletionItemKind, MarkupKind, Position

from optics_framework_lsp.completion import complete, signature
from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.parser.csv_parser import parse_csv_sources

CATALOG = {
    "press element": Keyword(
        required=1, variadic=False, params=["element", "repeat"], defaults={"repeat": "'1'"}
    ),
    "read data": Keyword(required=2, variadic=False, params=["input_element", "file_path"]),
    "scroll": Keyword(required=1, variadic=False, params=["direction", "event_name"]),
    "is element": Keyword(
        required=2, variadic=False, params=["element", "element_state", "timeout"]
    ),
}

MODULES = (
    "module_name,module_step,param_1,param_2\n"
    "Login,Press Element,${btn}\n"
    "Login,Read Data,serial_id,${env}\n"
)
TESTS = "test_case,test_step\nSmoke,Login\n"
ELEMENTS = "element_name,element_id\nbtn,//a\nenv,ENV:X\n"


def _typing(
    base: str, line: str, *others: str, catalog=CATALOG, images=(), data=(), apis=()
):
    """Complete at the end of `line`, as if it were being typed onto `base`."""
    text = base + line
    ast = parse_csv_sources(
        [("file:///w/0.csv", text)] + [(f"file:///w/{i}.csv", o) for i, o in enumerate(others, 1)]
    )
    position = Position(line=base.count("\n"), character=len(line))
    return complete(
        text, position, ast, catalog, images=images, data_files=data, apis=apis
    )


def test_module_step_offers_keywords_and_modules():
    items = _typing(MODULES, "Other,", ELEMENTS)
    kinds = {i.label: i.kind for i in items}

    assert kinds["Press Element"] == CompletionItemKind.Keyword
    assert kinds["Login"] == CompletionItemKind.Module


def test_keyword_detail_lists_params():
    (item,) = [i for i in _typing(MODULES, "Other,") if i.label == "Press Element"]
    assert item.detail == "element, repeat"


def test_param_column_offers_elements_and_variables():
    items = _typing(MODULES, "Other,Press Element,", ELEMENTS)
    labels = [i.label for i in items]

    assert "btn" in labels
    # serial_id is bound by the Read Data row, not defined in an elements csv.
    assert "serial_id" in labels
    assert [i.text_edit.new_text for i in items if i.label == "btn"] == ["${btn}"]


def test_partial_placeholder_is_replaced_not_nested():
    line = "Other,Press Element,${b"
    (item,) = [i for i in _typing(MODULES, line, ELEMENTS) if i.label == "btn"]

    assert item.text_edit.new_text == "${btn}"
    assert item.text_edit.range.start.character == len("Other,Press Element,")
    assert item.text_edit.range.end.character == len(line)


@pytest.mark.parametrize("step", ["Run Loop", "Execute Module"])
def test_module_params_offer_bare_module_names(step):
    items = _typing(MODULES, f"Other,{step},", ELEMENTS)
    assert [i.label for i in items] == ["Login", "Other"]
    # A module is run by name, so no ${} wrapping.
    assert [i.text_edit.new_text for i in items] == ["Login", "Other"]


def test_run_loop_params_after_the_target_are_variables():
    assert "btn" in [i.label for i in _typing(MODULES, "Other,Run Loop,Login,", ELEMENTS)]


def test_condition_offers_modules_and_variables_by_parity():
    # Even params hold a condition, which may be a module or an expression.
    condition = _typing(MODULES, "Other,Condition,", ELEMENTS)
    assert [i.label for i in condition] == ["Login", "Other", "btn", "env", "serial_id"]

    # Odd params hold the target module to run, so no variables.
    target = _typing(MODULES, "Other,Condition,Login,", ELEMENTS)
    assert [i.label for i in target] == ["Login", "Other"]
    assert [i.text_edit.new_text for i in target] == ["Login", "Other"]


def test_condition_keeps_an_inverting_bang():
    (item,) = [i for i in _typing(MODULES, "Other,Condition,!Log", ELEMENTS) if i.label == "Login"]
    assert item.text_edit.new_text == "!Login"


def test_read_data_file_param_offers_data_files():
    data = ["data/users.csv", "data/config.json"]
    items = _typing(MODULES, "Other,Read Data,${out},", ELEMENTS, data=data)
    assert [i.label for i in items] == data

    # Param 0 names the variable to bind and param 2 is a query, so neither is a file.
    # Existing names stay on offer at param 0: rebinding one is legal and Run Loop
    # relies on it.
    assert "btn" in [
        i.label for i in _typing(MODULES, "Other,Read Data,", ELEMENTS, data=data)
    ]
    assert "btn" in [
        i.label
        for i in _typing(MODULES, "Other,Read Data,${out},f.csv,", ELEMENTS, data=data)
    ]


def test_invoke_api_offers_collection_dot_api():
    items = _typing(MODULES, "Other,Invoke API,", ELEMENTS, apis=["users.get_user"])
    assert [i.label for i in items] == ["users.get_user"]


def test_fixed_value_params_offer_their_values():
    scroll = _typing(MODULES, "Other,Scroll,", ELEMENTS)
    assert [i.label for i in scroll] == ["up", "down", "left", "right"]

    # Found by param name, so a param two positions in works the same.
    state = _typing(MODULES, "Other,Is Element,${btn},", ELEMENTS)
    assert [i.label for i in state] == ["visible", "invisible", "enabled", "disabled"]

    # A param with no fixed values still offers elements.
    assert "btn" in [i.label for i in _typing(MODULES, "Other,Scroll,up,", ELEMENTS)]


def test_fixed_values_need_the_catalog():
    assert "up" not in [
        i.label for i in _typing(MODULES, "Other,Scroll,", ELEMENTS, catalog=None)
    ]


def test_quoted_comma_does_not_shift_the_column():
    line = 'Other,Press Element,"//a[@x=\'1,2\']",'
    # Still a param column, so elements are offered rather than keywords.
    assert "btn" in [i.label for i in _typing(MODULES, line, ELEMENTS)]


def test_module_name_column_offers_existing_modules():
    labels = [i.label for i in _typing(MODULES, "", ELEMENTS)]
    assert labels == ["Login"]


def test_test_step_offers_modules():
    labels = [i.label for i in _typing(TESTS, "Case,", MODULES)]
    assert labels == ["Login"]


def test_test_case_column_offers_existing_cases_and_lifecycle_hooks():
    labels = [i.label for i in _typing(TESTS, "", MODULES)]
    assert labels == ["Smoke", "Suite Setup", "Suite Teardown", "Setup", "Teardown"]


def test_lifecycle_hooks_are_not_offered_twice():
    tests = TESTS + "Suite Setup,Login\n"
    labels = [i.label for i in _typing(tests, "", MODULES)]
    assert labels.count("Suite Setup") == 1


def test_element_name_column_offers_undefined_references():
    modules = MODULES + "Login,Press Element,${missing}\n"
    labels = [i.label for i in _typing(ELEMENTS, "", modules)]
    # btn and env are defined here already; serial_id is bound by Read Data.
    assert labels == ["missing"]


def test_element_id_column_offers_template_images():
    items = _typing(ELEMENTS, "name,", images=["btn.png"])
    assert [i.label for i in items] == ["btn.png"]
    # Without images in the project there is nothing to guess.
    assert _typing(ELEMENTS, "name,") == []


def test_modules_are_offered_without_a_catalog():
    labels = [i.label for i in _typing(MODULES, "Other,", catalog=None)]
    # Not "Other": `read_modules` drops a row with no step, so the half-typed row
    # defines nothing yet and offering it would only suggest calling itself.
    assert labels == ["Login"]
