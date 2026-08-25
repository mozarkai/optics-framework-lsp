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
