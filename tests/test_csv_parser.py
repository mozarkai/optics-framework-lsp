from optics_framework_lsp.parser.csv_parser import parse_csv_sources


def _texts(element):
    return [locator.text for locator in element.locators]


def _parse(content: str, uri: str = "file:///w/x.csv"):
    return parse_csv_sources([(uri, content)])


def test_test_cases_group_into_blocks():
    ast = _parse(
        "test_case,test_step\n"
        "Valid Login,Open App\n"
        "Valid Login,Submit Credentials\n"
        "Bad Login,Open App\n"
    )
    assert [b.name for b in ast.test_cases] == ["Valid Login", "Bad Login"]

    first = ast.test_cases[0]
    assert first.start_row == 2
    assert [s.step_name for s in first.steps] == ["Open App", "Submit Credentials"]
    assert [s.row for s in first.steps] == [2, 3]


def test_module_params_are_captured():
    ast = _parse(
        "module_name,module_step,param_1,param_2\n"
        "Login,Launch Application\n"
        "Login,Press Element,${login_button}\n"
        "Login,Enter Text,${user_field},admin\n"
    )
    (module,) = ast.modules
    assert module.name == "Login"
    assert [s.step_name for s in module.steps] == [
        "Launch Application",
        "Press Element",
        "Enter Text",
    ]
    assert module.steps[0].params == []
    assert module.steps[1].params == ["${login_button}"]
    assert module.steps[2].params == ["${user_field}", "admin"]


def test_elements_are_collected():
    ast = _parse(
        "element_name,element_id\n"
        "login_button,//*[@id='login']\n"
        "user_field,Username\n"
    )
    assert [(e.name, _texts(e), e.row) for e in ast.elements] == [
        ("login_button", ["//*[@id='login']"], 2),
        ("user_field", ["Username"], 3),
    ]


def test_blank_line_ignored_but_whitespace_line_flagged():
    ast = _parse(
        "element_name,element_id\n"
        "a,1\n"
        "\n"
        "   \n"
        "b,2\n"
    )
    assert [(i.kind, i.row) for i in ast.csv_issues] == [("whitespace-only-line", 4)]
    assert [e.name for e in ast.elements] == ["a", "b"]


def test_column_count_issues():
    ast = _parse(
        "test_case,test_step\n"
        "OnlyOneColumn\n"
        "Case A,Step A,extra,more\n"
    )
    assert [(i.kind, i.row) for i in ast.csv_issues] == [
        ("too-few-columns", 2),
        ("too-many-columns", 3),
    ]
    assert [b.name for b in ast.test_cases] == ["Case A"]


def test_quotes_inside_values_do_not_abort_parse():
    ast = _parse(
        "element_name,element_id\n"
        "btn,//button[@class=\"go\"]\n"
    )
    assert _texts(ast.elements[0]) == ['//button[@class="go"]']


def test_unknown_headers_produce_nothing():
    ast = _parse("foo,bar\n1,2\n")
    assert ast.test_cases == []
    assert ast.modules == []
    assert ast.elements == []
    assert ast.csv_issues == []


CAPITALISED = (
    "Element_Name,Element_ID_xpath,Element_ID,Element_Text\n"
    "alarm_tab,//a,alarm.png,Alarm\n"
)


def test_headers_are_matched_case_insensitively():
    """`read_csv_headers` lowercases before classifying; every shipped sample is capitalised."""
    ast = parse_csv_sources([("file:///w/e.csv", CAPITALISED)])
    assert [e.name for e in ast.elements] == ["alarm_tab"]
    # Recognised, so it is not left as an unknown file with column complaints.
    assert ast.csv_issues == []


def test_capitalised_modules_and_test_cases_too():
    ast = parse_csv_sources([
        ("file:///w/m.csv", "Module_Name,Module_Step,Param_1\nLogin,Press Element,${btn}\n"),
        ("file:///w/t.csv", "Test_Case,Test_Step\nSmoke,Login\n"),
    ])
    assert [m.name for m in ast.modules] == ["Login"]
    assert [t.name for t in ast.test_cases] == ["Smoke"]
    assert ast.modules[0].steps[0].params == ["${btn}"]


def test_a_locator_in_any_element_id_column_counts():
    """`read_elements` keeps every `element_id*` column, so one row can hold several."""
    ast = parse_csv_sources([(
        "file:///w/e.csv",
        "Element_Name,Element_ID_xpath,Element_ID,Element_Text\n"
        'minute_list,"[""00"",""01""]",,\n'
        "btn,,btn.png,Save\n",
    )])
    # `Element_Text` is not a locator column, so `Save` is not among btn's ids.
    assert [(e.name, _texts(e)) for e in ast.elements] == [
        ("minute_list", ['["00","01"]']),
        ("btn", ["btn.png"]),
    ]


def test_several_locators_on_one_row_are_all_kept():
    """The framework's own calendar sample writes an xpath and a text fallback."""
    ast = parse_csv_sources([(
        "file:///w/e.csv",
        "Element_Name,Element_ID,Element_ID_text\n"
        "calendar_app,//android.widget.TextView,Calendar\n",
    )])
    (element,) = ast.elements
    assert _texts(element) == ["//android.widget.TextView", "Calendar"]


def test_a_row_missing_its_name_is_dropped_not_continued():
    """`read_test_cases` and `read_modules` need both cells, so a nameless row is
    skipped rather than joining the block above it."""
    ast = _parse(
        "test_case,test_step\n"
        "TC One,Step A\n"
        ",Step B\n"
        "TC One,Step C\n"
    )
    (block,) = ast.test_cases
    assert [s.step_name for s in block.steps] == ["Step A", "Step C"]

    ast = _parse(
        "module_name,module_step,param_1\n"
        "M,Sleep,1\n"
        ",Sleep,2\n"
    )
    (module,) = ast.modules
    assert [s.params for s in module.steps] == [["1"]]


def test_a_named_row_with_no_step_contributes_nothing():
    """The reader never creates the key, so a block whose only row lacks a step does
    not exist — a step naming it has to report module-not-found."""
    ast = _parse(
        "test_case,test_step\n"
        "TC One,Step A\n"
        "TC One,\n"
    )
    (block,) = ast.test_cases
    assert [s.step_name for s in block.steps] == ["Step A"]

    ast = _parse(
        "module_name,module_step,param_1\n"
        "Real,Sleep,1\n"
        "Stub,\n"
    )
    assert [m.name for m in ast.modules] == ["Real"]


def test_only_param_columns_are_params():
    """`read_modules` collects `param_*` cells only, so a notes column never reaches the
    keyword and does not shift the params after it."""
    ast = _parse(
        "module_name,module_step,param_1,notes,param_2\n"
        "M,Enter Text,${field},IGNORE ME,hello\n"
    )
    (step,) = ast.modules[0].steps
    assert step.params == ["${field}", "hello"]

    # A trailing comma in the header row makes an unnamed column; it is not a param.
    ast = _parse("module_name,module_step,param_1,\nM,Sleep,5,STRAY\n")
    assert ast.modules[0].steps[0].params == ["5"]

    # Params named something else entirely never reach the keyword at all, and the
    # underscore is required: the reader tests `startswith("param_")`.
    for header in ("arg1", "param1", "params"):
        ast = _parse(f"module_name,module_step,{header}\nM,Sleep,5\n")
        assert ast.modules[0].steps[0].params == [], header


def test_a_blank_param_cell_holds_no_place():
    ast = _parse(
        "module_name,module_step,param_1,param_2\n"
        "M,Enter Text,,hello\n"
    )
    assert ast.modules[0].steps[0].params == ["hello"]
