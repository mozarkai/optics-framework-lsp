# File kind comes from top-level keys, not filename

from optics_framework_lsp.parser.ast import kinds_of
from optics_framework_lsp.parser.yaml_parser import parse_yaml_sources

URI = "file:///w/suite.yaml"


def _parse(content, uri=URI):
    return parse_yaml_sources([(uri, content)])


def _issues(ast):
    return [(i.kind, i.row) for i in ast.issues]


SUITE = (
    "Test Cases:\n"
    "  - Add Contact:\n"
    "      - Launch App Module\n"
    "      - Save It\n"
    "Modules:\n"
    "  - Launch App Module:\n"
    "      - Launch App\n"
    "  - Save It:\n"
    "      - Press Element ${save}\n"
    "Elements:\n"
    "  save: //a\n"
)


def test_the_three_sections_are_read():
    ast = _parse(SUITE)
    assert [b.name for b in ast.test_cases] == ["Add Contact"]
    assert [s.step_name for s in ast.test_cases[0].steps] == ["Launch App Module", "Save It"]
    assert [b.name for b in ast.modules] == ["Launch App Module", "Save It"]
    assert [e.name for e in ast.elements] == ["save"]
    assert not ast.issues


def test_one_file_can_be_every_kind_at_once():
    """`_categorize_file_by_content` appends to each collection independently."""
    assert kinds_of(_parse(SUITE), URI) == {"test_cases", "modules", "elements"}


def test_rows_are_the_lines_the_names_are_on():
    ast = _parse(SUITE)
    assert ast.test_cases[0].start_row == 2
    assert [s.row for s in ast.test_cases[0].steps] == [3, 4]
    assert [b.start_row for b in ast.modules] == [6, 8]
    assert ast.elements[0].row == 11


def test_a_name_repeated_is_one_block():
    """`read_modules` keys by name, so two items sharing one merge as they do in a csv."""
    ast = _parse("Modules:\n  - M:\n      - Launch App\n  - M:\n      - Quit\n")
    assert [b.name for b in ast.modules] == ["M"]
    assert [s.row for s in ast.modules[0].steps] == [3, 5]


# `_parse_module_step` ends the keyword name at the longest run of leading words the
# catalog names, and takes the rest as `.split()` params. A `${...}` is the fallback, for
# a name the catalog does not know.
def test_a_step_splits_at_its_first_variable():
    ast = _parse("Modules:\n  - M:\n      - Enter Text ${f} hello\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Enter Text", ["${f}", "hello"])


def test_a_step_whose_first_param_is_a_literal_still_splits():
    """The catalog ends the name, so `Sleep 5` is the keyword `Sleep` with one param —
    it used to be read as a keyword named `sleep 5`, which nothing answers to."""
    ast = _parse("Modules:\n  - M:\n      - Sleep 5\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Sleep", ["5"])


def test_the_longest_catalog_match_wins():
    """Or `Swipe By Percentage 50 50 20` would be read as `Swipe`."""
    ast = _parse("Modules:\n  - M:\n      - Swipe By Percentage 50 50 20\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Swipe By Percentage", ["50", "50", "20"])


def test_slug_form_is_a_keyword_too():
    ast = _parse("Modules:\n  - M:\n      - press_element ${btn}\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("press_element", ["${btn}"])


def test_a_name_the_catalog_does_not_know_falls_back_to_the_variable():
    """So a misspelt keyword still reports the name alone rather than the whole line."""
    ast = _parse("Modules:\n  - M:\n      - Slep ${btn}\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Slep", ["${btn}"])


def test_a_step_the_catalog_cannot_claim_at_all_stays_whole():
    """Which is how a step naming another module reaches the runner."""
    ast = _parse("Modules:\n  - M:\n      - Login Flow\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Login Flow", [])


def test_a_module_name_wins_over_the_catalog():
    """`_parse_module_step` checks the project's module names before the catalogue, so a
    module called `Sleep Well` is that module and not `Sleep` with a param."""
    ast = _parse("Modules:\n  - M:\n      - Sleep Well\n  - Sleep Well:\n      - Launch App\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Sleep Well", [])


def test_a_module_name_from_another_file_wins_too():
    """`_load_modules` gathers the names across every module file before parsing one."""
    ast = parse_yaml_sources([
        (URI, "Modules:\n  - M:\n      - Sleep Well\n"),
        ("file:///w/other.yaml", "Modules:\n  - Sleep Well:\n      - Launch App\n"),
    ])
    assert [(s.step_name, s.params) for s in ast.modules[0].steps] == [("Sleep Well", [])]


def test_a_module_name_is_matched_by_its_slug():
    """`_matched_module_name` falls back to the slug, so a step may name the module in
    another case. The step keeps the text as written — the spans point at the source."""
    ast = _parse("Modules:\n  - M:\n      - sleep well\n  - Sleep Well:\n      - Launch App\n")
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("sleep well", [])


def test_a_mis_cased_modules_key_defines_no_names():
    """`read_module_names` does `data.get("Modules")`, so the section reads as nothing —
    the same gap that already makes its blocks unreadable."""
    ast = parse_yaml_sources([
        (URI, "Modules:\n  - M:\n      - Sleep Well\n"),
        ("file:///w/other.yaml", "modules:\n  - Sleep Well:\n      - Launch App\n"),
    ])
    assert [(s.step_name, s.params) for s in ast.modules[0].steps] == [("Sleep", ["Well"])]


def test_a_step_that_is_only_a_variable_is_dropped():
    """`_process_module_steps` keeps nothing when the keyword came out empty."""
    assert _parse("Modules:\n  - M:\n      - ${f}\n").modules[0].steps == []


def test_spans_point_at_the_keyword_and_each_param():
    ast = _parse("Modules:\n  - M:\n      - Enter Text ${f} hi\n")
    step = ast.modules[0].steps[0]
    line = "      - Enter Text ${f} hi"
    assert step.name_span is not None
    assert line[slice(*step.name_span)] == "Enter Text"
    assert [line[slice(*s)] for s in step.param_spans] == ["${f}", "hi"]


def test_a_quoted_value_holds_its_space():
    """The only way a param can contain one: `param_str.split()` is quote-aware now."""
    ast = _parse('Modules:\n  - M:\n      - Enter Text ${f} text="two words"\n')
    step = ast.modules[0].steps[0]
    assert (step.step_name, step.params) == ("Enter Text", ["${f}", "text=two words"])


def test_a_quoted_positional_value_holds_its_space():
    ast = _parse('Modules:\n  - M:\n      - Enter Text ${f} "two words"\n')
    assert ast.modules[0].steps[0].params == ["${f}", "two words"]


def test_a_locator_keeps_the_quotes_inside_it():
    """They do not wrap the value, so they are part of it — unwrapping them would break
    every double-quoted xpath."""
    ast = _parse('Modules:\n  - M:\n      - Press Element //*[@text="a b"]\n')
    assert ast.modules[0].steps[0].params == ['//*[@text="a b"]']


def test_an_unbalanced_quote_splits_as_before():
    ast = _parse('Modules:\n  - M:\n      - Enter Text ${f} text="abc\n')
    assert ast.modules[0].steps[0].params == ["${f}", 'text="abc']


def test_a_quoted_param_span_covers_its_quotes():
    """The step carries what the runner is given; the span covers what was written."""
    ast = _parse('Modules:\n  - M:\n      - Enter Text ${f} text="two words"\n')
    step = ast.modules[0].steps[0]
    line = '      - Enter Text ${f} text="two words"'
    assert [line[slice(*span)] for span in step.param_spans] == ["${f}", 'text="two words"']
    assert step.params[1] == "text=two words"


def test_a_quoted_step_is_measured_past_its_quote():
    ast = _parse("Modules:\n  - M:\n      - 'Enter Text ${f}'\n")
    step = ast.modules[0].steps[0]
    line = "      - 'Enter Text ${f}'"
    assert step.name_span is not None
    assert line[slice(*step.name_span)] == "Enter Text"


def test_a_block_scalar_has_no_spans():
    """Its value is no contiguous run of the source, so no offset inside it is safe."""
    ast = _parse("Modules:\n  - M:\n      - >-\n          Press Element ${f}\n")
    step = ast.modules[0].steps[0]
    assert step.step_name == "Press Element"
    assert step.name_span is None and step.param_spans == []


def test_an_element_takes_one_locator_or_a_fallback_list():
    ast = _parse("Elements:\n  one: //a\n  many:\n    - //b\n    - //c\n")
    assert [(e.name, [l.text for l in e.locators]) for e in ast.elements] == [
        ("one", ["//a"]),
        ("many", ["//b", "//c"]),
    ]


def test_each_fallback_locator_carries_its_own_row():
    """A csv writes them across one row; a yaml gives each a line of its own."""
    ast = _parse("Elements:\n  many:\n    - //b\n    - //c\n")
    assert [l.row for l in ast.elements[0].locators] == [3, 4]


def test_an_element_with_nothing_under_it_is_dropped():
    assert _parse("Elements:\n  empty:\n  ok: //a\n").elements[0].name == "ok"


def test_malformed_yaml_is_an_issue_and_nothing_is_read():
    """`read_file` logs and returns `{}`, so the file loads as empty rather than failing."""
    ast = _parse("Modules:\n  - M:\n   - bad indent\n")
    assert [k for k, _ in _issues(ast)] == ["yaml-parse-error"]
    assert ast.modules == [] and ast.kinds == {}


def test_a_section_key_in_the_wrong_case_is_found_but_not_read():
    ast = _parse("test_cases:\n  - TC:\n      - M\n")
    assert _issues(ast) == [("yaml-section-key-case", 1)]
    # Classified, so the file is not reported as one we skipped.
    assert kinds_of(ast, URI) == {"test_cases"}
    assert ast.test_cases == []


def test_the_exact_key_is_read_even_beside_a_misspelt_one():
    ast = _parse("Modules:\n  - M:\n      - Launch App\nmodules:\n  - N:\n      - Quit\n")
    assert [b.name for b in ast.modules] == ["M"]
    assert _issues(ast) == [("yaml-section-key-case", 4)]


def test_a_section_written_as_a_mapping_is_an_issue():
    """What `optics generate` accepts and the runner does not: it raises on `.items()`."""
    ast = _parse("Test Cases:\n  TC:\n    - M\n")
    assert _issues(ast) == [("yaml-section-shape", 2)]
    assert ast.test_cases == []


def test_elements_written_as_a_list_is_an_issue():
    """`read_elements` calls `.items()` on it, so a list there takes the load down too."""
    ast = _parse("Elements:\n  - btn: //a\n")
    assert _issues(ast) == [("yaml-section-shape", 2)]
    assert ast.elements == []


def test_a_test_case_step_that_is_not_a_string_is_an_issue():
    ast = _parse("Test Cases:\n  - TC:\n      - M\n      - 42\n")
    assert _issues(ast) == [("yaml-step-not-a-string", 4)]
    assert [s.step_name for s in ast.test_cases[0].steps] == ["M"]


def test_an_item_that_is_not_a_mapping_is_an_issue():
    ast = _parse("Modules:\n  - just a string\n")
    assert _issues(ast) == [("yaml-section-shape", 2)]


def test_a_step_that_is_not_a_string_is_an_issue():
    ast = _parse("Modules:\n  - M:\n      - Launch App\n      - 42\n")
    assert _issues(ast) == [("yaml-step-not-a-string", 4)]
    assert [s.step_name for s in ast.modules[0].steps] == ["Launch App"]


def test_error_definitions_are_reported_as_unread():
    """There is no yaml reader for them: `_load_error_definitions` hardcodes the csv one."""
    ast = _parse("Error Definitions:\n  - ERR_001: boom\n")
    assert _issues(ast) == [("yaml-error-definitions-unread", 1)]
    assert ast.error_definitions == []


def test_an_api_file_is_classified_but_holds_no_suite():
    ast = _parse("api:\n  collections: {}\n")
    assert kinds_of(ast, URI) == {"api"}
    assert not ast.issues


def test_a_config_is_recognised_by_its_keys_not_its_name():
    """`_is_config_file` looks for these two; the runner never checks a basename."""
    ast = _parse("driver_sources:\n  - appium\nelements_sources:\n  - x\n", "file:///w/x.yml")
    assert kinds_of(ast, "file:///w/x.yml") == {"config"}


def test_flow_style_is_read_the_same_as_block_style():
    """`safe_load` does not care which is written, so neither may we."""
    ast = _parse("Modules: [{M: [Launch App]}]\nElements: {btn: //a}\n")
    assert [(b.name, [s.step_name for s in b.steps]) for b in ast.modules] == [
        ("M", ["Launch App"])
    ]
    assert [e.name for e in ast.elements] == ["btn"]


def test_a_tab_is_the_parse_error_yaml_says_it_is():
    """Both as indentation and inside a step, which `safe_load` rejects the same way."""
    for text in ("Modules:\n\t- M:\n", "Modules:\n  - M:\n      - Press\t${b}\n"):
        assert [k for k, _ in _issues(_parse(text))] == ["yaml-parse-error"]


def test_an_unrelated_yaml_is_left_alone():
    ast = _parse("services:\n  web:\n    image: nginx\n", "file:///w/compose.yml")
    assert ast.kinds == {} and not ast.issues


def test_a_document_that_is_not_a_mapping_is_left_alone():
    assert _parse("- just\n- a list\n").kinds == {}
