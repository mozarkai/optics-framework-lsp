from lsprotocol.types import DiagnosticSeverity

from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.validation import validate

TESTS = "file:///w/tests.csv"
MODULES = "file:///w/modules.csv"
ELEMENTS = "file:///w/elements.csv"


def _check(**files: str):
    return validate(parse_csv_sources(list(files.items())))


def test_unknown_module_is_an_error():
    found = _check(**{
        TESTS: "test_case,test_step\nTC,Login\nTC,Missing Module\n",
        MODULES: "module_name,module_step\nLogin,Launch Application\n",
    })
    (diag,) = found[TESTS]
    assert diag.code == "module-not-found"
    assert diag.severity == DiagnosticSeverity.Error
    assert diag.line == 2
    assert "Missing Module" in diag.message


def test_element_refs_in_params_are_checked():
    found = _check(**{
        MODULES: "module_name,module_step,param_1\n"
                 "Login,Press Element,${known}\n"
                 "Login,Press Element,${unknown}\n",
        ELEMENTS: "element_name,element_id\nknown,//a\n",
    })
    (diag,) = found[MODULES]
    assert diag.code == "element-not-found"
    assert "unknown" in diag.message
    assert diag.line == 2


def test_repeating_an_element_with_another_id_is_a_fallback_not_a_duplicate():
    """`_add_or_merge_element` gathers the ids into one list and tries each in turn."""
    found = _check(**{
        ELEMENTS: "element_name,element_id\nbtn,//a\nbtn,btn.png\n",
    })
    assert found.get(ELEMENTS, []) == []


def test_repeating_an_element_with_the_same_id_is_a_warning():
    found = _check(**{
        ELEMENTS: "element_name,element_id\nbtn,//a\nbtn,//a\n",
    })
    assert [d.severity for d in found[ELEMENTS]] == [DiagnosticSeverity.Warning] * 2
    assert {d.code for d in found[ELEMENTS]} == {"duplicate-element"}


def test_only_the_repeated_id_rows_are_flagged():
    found = _check(**{
        ELEMENTS: "element_name,element_id\nbtn,//a\nbtn,//a\nbtn,btn.png\n",
    })
    # Rows 2 and 3 repeat //a; the image on row 4 is a genuine fallback.
    assert [d.line for d in found[ELEMENTS]] == [1, 2]


OTHER_MODULES = "file:///w/more.csv"


def test_a_module_split_by_another_block_is_one_module():
    """`read_modules` keys by name, so rows split apart still merge into one."""
    found = _check(**{
        MODULES: "module_name,module_step\nLogin,Launch Application\n"
                 "Other,Launch Application\nLogin,Launch Application\n",
    })
    assert found == {}

    ast = parse_csv_sources([(MODULES, "module_name,module_step\nLogin,Sleep\n"
                                       "Other,Sleep\nLogin,Sleep\n")])
    (login, other) = ast.modules
    assert (login.name, [s.row for s in login.steps]) == ("Login", [2, 4])
    assert (other.name, [s.row for s in other.steps]) == ("Other", [3])


def test_the_same_module_in_two_files_overwrites_and_is_a_warning():
    # `add_module_definition` assigns, so the second file's definition simply wins.
    found = _check(**{
        MODULES: "module_name,module_step\nLogin,Launch Application\n",
        OTHER_MODULES: "module_name,module_step\nLogin,Launch Application\n",
    })
    assert [d.code for d in found[MODULES]] == ["duplicate-module"]
    assert found[MODULES][0].severity == DiagnosticSeverity.Warning
    assert found[MODULES][0].message == "Duplicate module 'Login', see more.csv line 2"
    assert found[OTHER_MODULES][0].message == "Duplicate module 'Login', see modules.csv line 2"


def test_the_same_test_case_in_two_files_is_a_warning():
    # `merge_dicts` keeps the value from the second source.
    found = _check(**{
        TESTS: "test_case,test_step\nTC,Login\n",
        "file:///w/more_tests.csv": "test_case,test_step\nTC,Login\n",
        MODULES: "module_name,module_step\nLogin,Launch Application\n",
    })
    assert [d.code for d in found[TESTS]] == ["duplicate-test-case"]


def test_an_element_shared_between_two_files_is_the_platform_pattern():
    # Elements merge into one list across files, unlike modules, so this is fine.
    assert _check(**{
        ELEMENTS: "element_name,element_id\nbtn,//ard\n",
        "file:///w/ios.csv": "element_name,element_id\nbtn,//ios\n",
    }) == {}


def test_the_same_locator_in_two_files_is_not_a_duplicate_either():
    # `_add_or_merge_element` dedups across files, so the list ends up with one `//a`.
    # Within one file `read_elements` extends without dedup, which is why that warns.
    assert _check(**{
        ELEMENTS: "element_name,element_id\nbtn,//a\n",
        "file:///w/ios.csv": "element_name,element_id\nbtn,//a\n",
    }) == {}


def test_csv_issues_become_diagnostics():
    found = _check(**{
        ELEMENTS: "element_name,element_id\na,1\n   \nb,2,extra\n",
    })
    assert {d.code for d in found[ELEMENTS]} == {
        "csv-whitespace-line",
        "csv-too-many-columns",
    }


def test_unrecognised_csv_is_left_alone():
    assert _check(**{"file:///w/caps.csv": "device,os\nonly-one-column\n"}) == {}


def test_clean_workspace_has_no_diagnostics():
    assert _check(**{
        TESTS: "test_case,test_step\nTC,Login\n",
        MODULES: "module_name,module_step,param_1\nLogin,Press Element,${btn}\n",
        ELEMENTS: "element_name,element_id\nbtn,//a\n",
    }) == {}
