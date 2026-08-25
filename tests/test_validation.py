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


def test_read_data_declares_a_variable():
    found = _check(**{
        MODULES: "module_name,module_step,param_1,param_2\n"
                 "M,Read Data,serial_id,${env_var}\n"
                 "M,Press Element,${serial_id}\n",
        ELEMENTS: "element_name,element_id\nenv_var,ENV:X\n",
    })
    assert found == {}


def test_declaration_written_as_a_placeholder():
    found = _check(**{
        MODULES: "module_name,module_step,param_1,param_2,param_3\n"
                 "M,Date Evaluate,${new_date},${today},+1 day\n"
                 "M,Press Element,${new_date}\n",
        ELEMENTS: "element_name,element_id\ntoday,2020-01-01\n",
    })
    assert found == {}


def test_run_loop_declares_its_loop_variables():
    found = _check(**{
        MODULES: "module_name,module_step,param_1,param_2,param_3\n"
                 "M,Run Loop,Target,mobile_number,${List}\n"
                 "Target,Press Element,${mobile_number}\n",
        ELEMENTS: "element_name,element_id\nList,1|2|3\n",
    })
    assert found == {}


def test_undefined_element_is_now_an_error():
    (diagnostic,) = _check(**{
        MODULES: "module_name,module_step,param_1\nM,Press Element,${nope}\n",
    })[MODULES]
    assert diagnostic.code == "element-not-found"
    assert diagnostic.severity == DiagnosticSeverity.Error


def _targets(modules: str):
    found = validate(parse_csv_sources([("file:///w/m.csv", modules)]))
    return [d.message for d in found.get("file:///w/m.csv", []) if d.code == "module-not-found"]


HEADER = "module_name,module_step,param_1,param_2,param_3,param_4\n"
REAL = "Real,Sleep,1\n"


def test_execute_module_and_run_loop_targets_must_exist():
    assert _targets(HEADER + REAL + "M,Execute Module,Typo\n") == ["Module 'Typo' not found"]
    assert _targets(HEADER + REAL + "M,Run Loop,Typo,2\n") == ["Module 'Typo' not found"]
    assert _targets(HEADER + REAL + "M,Execute Module,Real\n") == []


def test_condition_checks_targets_but_not_conditions():
    # Even params hold a condition, which may be an expression rather than a module.
    assert _targets(HEADER + REAL + "M,Condition,${x} == 5,Real\n") == []
    # Odd params are the module to run.
    assert _targets(HEADER + REAL + "M,Condition,${x} == 5,Typo\n") == [
        "Module 'Typo' not found"
    ]


def test_condition_checks_a_bare_else_target():
    # An odd count means the last param is the else-target, so it is a module.
    assert _targets(HEADER + REAL + "M,Condition,${x} == 5,Real,Typo\n") == [
        "Module 'Typo' not found"
    ]
    assert _targets(HEADER + REAL + "M,Condition,${x} == 5,Real,Real\n") == []


def test_a_variable_target_is_reported_like_any_other():
    # The runner hands params to the keyword untouched, so ${chosen} never resolves.
    assert _targets(HEADER + REAL + "M,Execute Module,${chosen}\n") == [
        "Module '${chosen}' not found"
    ]


def test_blank_cells_do_not_shift_the_target():
    # `read_modules` drops empty cells, so trailing commas must not move the else-target.
    assert _targets(HEADER + REAL + "M,Execute Module,Real,,,\n") == []


SPACED = "module_name,module_step,param_1,param_2\n"


def _codes(modules: str, catalog=None):
    found = validate(parse_csv_sources([("file:///w/m.csv", modules)]), catalog)
    return [d.code for d in found.get("file:///w/m.csv", [])]


def test_extra_spaces_in_a_keyword_are_not_an_error():
    """`_execute_single_keyword` collapses whitespace, so the runner accepts these."""
    from optics_framework_lsp.keyword_catalog import Keyword

    catalog = {"press element": Keyword(required=1, variadic=False, params=["element"])}
    for step in ("Press Element", "Press  Element", "press element", "PRESS ELEMENT"):
        assert _codes(SPACED + f"M,{step},x\n", catalog) == [], step


def test_extra_spaces_do_not_hide_a_declaration():
    # Read Data binds serial_id, so ${serial_id} below must not be element-not-found.
    modules = SPACED + "M,Read  Data,serial_id,f.csv\nM,Press Element,${serial_id}\n"
    assert "element-not-found" not in _codes(modules)


def test_a_row_repeated_with_all_its_locators_is_a_warning():
    found = _check(**{
        ELEMENTS: "element_name,element_id,element_id_text\nbtn,//a,Save\nbtn,//a,Save\n",
    })
    assert [d.code for d in found[ELEMENTS]] == ["duplicate-element"] * 2


def test_rows_sharing_only_their_first_locator_are_still_fallbacks():
    # `//a` twice, but the text fallback differs, so the pair is not a plain repeat.
    found = _check(**{
        ELEMENTS: "element_name,element_id,element_id_text\nbtn,//a,Save\nbtn,//a,Cancel\n",
    })
    assert found.get(ELEMENTS, []) == []
