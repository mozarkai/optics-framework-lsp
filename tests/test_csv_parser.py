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
