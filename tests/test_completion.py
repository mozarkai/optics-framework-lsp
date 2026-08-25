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


def _sig(base: str, line: str):
    return signature(
        base + line, Position(line=base.count("\n"), character=len(line)), CATALOG
    )


def test_signature_marks_the_active_param():
    help_ = _sig(MODULES, "Other,Press Element,")

    assert help_.signatures[0].label == "Press Element(element, repeat='1')"
    assert help_.active_parameter == 0
    assert _sig(MODULES, "Other,Press Element,${btn},").active_parameter == 1

    # A client highlights by matching the label, so it has to be a substring of the whole.
    labels = [p.label for p in help_.signatures[0].parameters]
    assert labels == ["element", "repeat='1'"]
    assert all(p in help_.signatures[0].label for p in labels)


def test_signature_stops_at_the_last_param():
    assert _sig(MODULES, "Other,Press Element,${btn},1,extra,").active_parameter == 1


def test_no_signature_for_unknown_or_module_steps():
    assert _sig(MODULES, "Other,Login,") is None
    assert _sig(MODULES, "Other,Nope,") is None
    # Nor while still typing the step name itself.
    assert _sig(MODULES, "Other,Press") is None



def test_accepting_a_param_past_the_header_widens_it():
    # MODULES declares param_1 and param_2, so a third param is not covered.
    (item,) = [
        i for i in _typing(MODULES, "Other,Press Element,${btn},x,", ELEMENTS)
        if i.label == "env"
    ]
    (edit,) = item.additional_text_edits
    assert edit.new_text == ",param_3"
    assert edit.range.start == Position(line=0, character=len(MODULES.splitlines()[0]))
    assert edit.range.start == edit.range.end  # an insert, nothing replaced


def test_two_params_past_the_header_add_both():
    (item,) = [
        i for i in _typing(MODULES, "Other,Press Element,${btn},x,y,", ELEMENTS)
        if i.label == "env"
    ]
    assert item.additional_text_edits[0].new_text == ",param_3,param_4"


def test_a_param_the_header_covers_is_left_alone():
    (item,) = [
        i for i in _typing(MODULES, "Other,Press Element,", ELEMENTS) if i.label == "env"
    ]
    assert item.additional_text_edits is None


def test_the_header_row_itself_is_never_widened():
    header = "module_name,module_step,param_1,param_2"
    items = complete(
        header + ",x,",
        Position(line=0, character=len(header) + 3),
        parse_csv_sources([("file:///w/0.csv", header)]),
        CATALOG,
    )
    assert all(i.additional_text_edits is None for i in items)


M_URI, T_URI, E_URI = "file:///w/m.csv", "file:///w/t.csv", "file:///w/e.csv"

M_SRC = (
    "module_name,module_step,param_1,param_2\n"
    "Login,Press Element,${btn}\n"
    "Login,Execute Module,Helper\n"
    "Helper,Sleep,1\n"
    "Guard,Condition,!Helper,Login\n"
    "Guard,Helper\n"
)
T_SRC = "test_case,test_step\nTC,Login\n"
E_SRC = "element_name,element_id\nbtn,//a\nbtn,btn.png\n"


def _definition(text, line, character, catalog=None, modules=M_SRC):
    from optics_framework_lsp.completion import definition

    sources = [(M_URI, modules), (T_URI, T_SRC), (E_URI, E_SRC)]
    ast = parse_csv_sources(sources)
    return definition(text, Position(line=line, character=character), ast, catalog)


def test_a_test_step_goes_to_its_module():
    (found,) = _definition(T_SRC, 1, 5)
    assert (found.uri, found.range.start.line) == (M_URI, 1)


def test_a_module_param_goes_to_the_nested_module():
    (found,) = _definition(M_SRC, 2, 25)
    assert (found.uri, found.range.start.line) == (M_URI, 3)


def test_a_variable_goes_to_every_row_that_defines_it():
    # Both rows are locators for `btn`, and the runner tries each in turn.
    found = _definition(M_SRC, 1, 25)
    assert [(f.uri, f.range.start.line) for f in found] == [(E_URI, 1), (E_URI, 2)]


def test_a_nested_module_step_finds_its_definition():
    # A step names a keyword or, failing that, another module to run.
    (found,) = _definition(M_SRC, 5, 8)
    assert (found.uri, found.range.start.line) == (M_URI, 3)


def test_a_keyword_wins_over_a_module_of_the_same_name():
    # `_execute_single_keyword` tries the keyword map first, so `Sleep` is not the module.
    named = M_SRC + "Sleep,Sleep\n"
    assert _definition(named, 6, 8, {"sleep": None}, named) == []
    assert len(_definition(named, 6, 8, None, named)) == 1


def test_an_inverted_condition_still_finds_its_module():
    (found,) = _definition(M_SRC, 4, 20)
    assert (found.uri, found.range.start.line) == (M_URI, 3)


def test_a_keyword_has_nowhere_to_go():
    assert _definition(M_SRC, 1, 15) == []


def test_the_header_is_not_a_reference():
    # Column 1 of the header is `module_step`, which is in a step column but names nothing.
    assert _definition(M_SRC, 0, 15) == []


DOCS = {
    "press element": Keyword(
        required=1,
        variadic=False,
        params=["element", "repeat"],
        doc="Press a specified element.\n\n:param element: What to press.",
        defaults={"repeat": "'1'"},
    ),
    "sleep": Keyword(required=1, variadic=False, params=["seconds"]),
}


def _hover(line, character, catalog=DOCS):
    from optics_framework_lsp.completion import hover

    return hover(M_SRC, Position(line=line, character=character), catalog)


def test_hover_shows_the_signature_and_docstring():
    found = _hover(1, 15)
    # Plain text, or markdown would fold the `:param x:` lines into one paragraph.
    assert found.contents.kind == MarkupKind.PlainText
    # An omitted cell falls back to the default, which is nowhere in the csv.
    assert found.contents.value.startswith("Press Element(element, repeat='1')\n\n")
    assert ":param element: What to press." in found.contents.value


def test_hover_without_a_docstring_is_just_the_signature():
    assert _hover(3, 10).contents.value == "Sleep(seconds)"


def test_hover_needs_the_catalog():
    assert _hover(1, 15, None) is None


def test_hover_only_answers_in_the_step_column():
    # Column 2 holds ${btn}, not a keyword.
    assert _hover(1, 24) is None


def _accept(rows: str, line: int, character: int, label: str) -> str:
    """The chosen item's edit applied to its row, as an editor would apply it."""
    ast = parse_csv_sources([("file:///w/m.csv", rows), ("file:///w/e.csv", ELEMENTS)])
    (item,) = [
        i
        for i in complete(rows, Position(line=line, character=character), ast, CATALOG)
        if i.label == label
    ]
    row, edit = rows.splitlines()[line], item.text_edit
    return row[: edit.range.start.character] + edit.new_text + row[edit.range.end.character :]


PAIRED = "module_name,module_step,param_1\nLogin,Press Element,${}\n"


def test_an_auto_paired_brace_is_not_doubled():
    # The editor closes the brace as `${|}`, and the item carries its own.
    where = len("Login,Press Element,${")
    assert _accept(PAIRED, 1, where, "btn") == "Login,Press Element,${btn}"


def test_a_partly_typed_name_inside_a_pair_is_replaced_whole():
    rows = "module_name,module_step,param_1\nLogin,Press Element,${bt}\n"
    assert _accept(rows, 1, len("Login,Press Element,${bt"), "btn") == "Login,Press Element,${btn}"


def test_without_a_pair_nothing_extra_is_eaten():
    rows = "module_name,module_step,param_1\nLogin,Press Element,${\n"
    assert _accept(rows, 1, len("Login,Press Element,${"), "btn") == "Login,Press Element,${btn}"


def test_a_brace_further_along_the_row_is_left_alone():
    rows = "module_name,module_step,param_1,param_2\nLogin,Press Element,${,x}\n"
    assert _accept(rows, 1, len("Login,Press Element,${"), "btn") == "Login,Press Element,${btn},x}"


def test_a_bare_name_never_eats_a_following_brace():
    # Only ${...} items bring their own closing brace; a module name does not.
    rows = "module_name,module_step,param_1\nLogin,Sleep,1\nOther,Execute Module,}\n"
    where = len("Other,Execute Module,")
    assert _accept(rows, 2, where, "Login") == "Other,Execute Module,Login}"


def test_images_are_offered_in_any_element_id_column():
    # `read_elements` reads every `element_id*` column, so completion must too.
    header = "Element_Name,Element_ID_xpath,Element_ID\n"
    items = complete(
        header + "btn,//a,",
        Position(line=1, character=len("btn,//a,")),
        parse_csv_sources([("file:///w/e.csv", header)]),
        None,
        images=["btn.png"],
    )
    assert [i.label for i in items] == ["btn.png"]
