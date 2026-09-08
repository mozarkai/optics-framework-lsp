# What a yaml suite reports, outlines and highlights, and how the linter sees it.

from lsprotocol.types import Position

from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.lint import report
from optics_framework_lsp.parser import parse_sources
from optics_framework_lsp.symbols import symbols
from optics_framework_lsp.tokens import LEGEND, tokens
from optics_framework_lsp.validation import validate

CATALOG = {
    "launch app": Keyword(params=[], required=0, variadic=False, defaults={}, doc="Opens it."),
    "press element": Keyword(
        params=["element", "index"], required=1, variadic=False,
        defaults={"index": "0"}, doc="Presses it.",
    ),
    "enter text": Keyword(
        params=["element", "text"], required=2, variadic=False, defaults={}, doc="",
    ),
    "sleep": Keyword(params=["duration"], required=1, variadic=False, defaults={}, doc=""),
    "read data": Keyword(
        params=["name", "path"], required=2, variadic=False, defaults={}, doc="",
    ),
    # Variadic, and it binds every other param after its target — the one keyword whose
    # bound names are bare words rather than `${...}`.
    "run loop": Keyword(
        params=["target"], required=1, variadic=True, defaults={}, doc="",
    ),
    "condition": Keyword(
        params=["condition"], required=1, variadic=True, defaults={}, doc="",
    ),
}

YAML_URI = "file:///w/suite.yaml"

CSV_URI = "file:///w/test_cases.csv"

SUITE = (
    "Test Cases:\n"
    "  - Add Contact:\n"
    "      - Open It\n"
    "Modules:\n"
    "  - Open It:\n"
    "      - Launch App\n"
    "      - Press Element ${save}\n"
    "Elements:\n"
    "  save: //a\n"
)

def _ast(*sources):
    return parse_sources(list(sources) or [(YAML_URI, SUITE)])

def _at(marker, offset=0, text=SUITE):
    """A position at `offset` into the first line holding `marker`."""
    for line, content in enumerate(text.splitlines()):
        if marker in content:
            return Position(line=line, character=content.index(marker) + offset)
    raise AssertionError(marker)

# --- diagnostics -------------------------------------------------------------
def _codes(*sources):
    found = validate(parse_sources(list(sources)), CATALOG)
    return sorted((uri, f.code, f.row) for uri, fs in found.items() for f in fs)

CONDITION = (
    "Modules:\n"
    "  - Go:\n"
    "      - Condition ${flag} Target ${other} !Target\n"
    "  - Target:\n"
    "      - Launch App\n"
    "Elements:\n"
    "  flag: //x\n"
    "  other: //y\n"
)

def _marked(text, ast=None):
    data = tokens(text, ast or _ast(), CATALOG, uri=YAML_URI)
    lines, line, char, found = text.splitlines(), 0, 0, []
    for i in range(0, len(data), 5):
        delta_line, delta_char, length, kind, mods = data[i : i + 5]
        line += delta_line
        char = delta_char if delta_line else char + delta_char
        found.append((lines[line][char : char + length], LEGEND[kind], mods))
    return found

def test_a_clean_yaml_suite_is_quiet():
    assert _codes((YAML_URI, SUITE)) == []

def test_a_literal_param_is_reported_as_the_yaml_trap_it_is():
    """`Sleep 5` becomes the keyword `sleep 5`, which nothing answers to."""
    got = _codes((YAML_URI, "Modules:\n  - M:\n      - Sleep 5\n"))
    assert got == [(YAML_URI, "yaml-step-without-variable", 3)]

def test_a_real_multi_word_keyword_is_not_reported():
    assert _codes((YAML_URI, "Modules:\n  - M:\n      - Launch App\n")) == []

def test_an_unknown_one_word_step_is_still_a_plain_keyword_miss():
    got = _codes((YAML_URI, "Modules:\n  - M:\n      - Nonsense\n"))
    assert got == [(YAML_URI, "keyword-not-found", 3)]

def test_a_csv_step_with_a_space_is_never_the_yaml_trap():
    csv = "module_name,module_step\nM,Sleep 5\n"
    got = _codes(("file:///w/m.csv", csv))
    assert got == [("file:///w/m.csv", "keyword-not-found", 2)]

def test_the_wrong_case_key_says_which_key_was_wanted():
    found = validate(parse_sources([(YAML_URI, "modules:\n  - M:\n      - Launch App\n")]), CATALOG)
    message = found[YAML_URI][0].message
    assert "`modules`" in message and "`Modules`" in message

def test_names_resolve_across_the_two_formats():
    """A module defined in yaml, called from a csv, is not a missing module."""
    assert _codes(
        (CSV_URI, "test_case,test_step\nTC,Open It\n"),
        (YAML_URI, SUITE),
    ) == []

def test_condition_alternates_by_parity_over_words_not_columns():
    """The trickiest param rule, and the one where a yaml's word split differs most from
    a csv's cells: `runs_at` counts the words after the keyword."""
    step = _ast((YAML_URI, CONDITION)).modules[0].steps[0]
    assert step.params == ["${flag}", "Target", "${other}", "!Target"]

def test_a_condition_target_is_highlighted_as_a_module():
    marked = _marked(CONDITION, _ast((YAML_URI, CONDITION)))
    assert ("Target", "function", 0) in marked
    # The `!` is the runner's own inversion, not part of the name.
    assert ("!", "operator", 0) in marked

def test_a_data_file_param_is_a_string_beside_the_name_it_binds():
    """A bound name has to be written `${rows}` here: a bare one before any `${...}` is
    swallowed into the keyword, so yaml can only ever declare in the braced form."""
    text = "Modules:\n  - M:\n      - Read Data ${rows} data.csv\n"
    marked = _marked(text, _ast((YAML_URI, text)))
    assert ("${rows}", "variable", 0) in marked and ("data.csv", "string", 0) in marked

def test_a_module_defined_in_both_formats_is_a_duplicate_in_both():
    """The runner keys by name across every file it finds, whatever each one is."""
    csv = "module_name,module_step\nShared,Launch App\n"
    yaml = "Modules:\n  - Shared:\n      - Launch App\n"
    got = _codes((CSV_URI, csv), (YAML_URI, yaml))
    assert got == [
        (YAML_URI, "duplicate-module", 2),
        (CSV_URI, "duplicate-module", 2),
    ]

def test_an_element_may_be_defined_in_one_format_and_read_in_the_other():
    csv = "element_name,element_id\nbtn,//a\n"
    yaml = "Modules:\n  - M:\n      - Press Element ${btn}\n"
    assert _codes((CSV_URI, csv), (YAML_URI, yaml)) == []

# --- outline and highlighting ------------------------------------------------
def test_a_yaml_outline_holds_every_section_at_once():
    outline = symbols(_ast())
    assert [s.name for s in outline] == ["Add Contact", "Open It", "save"]
    assert [c.name for c in outline[1].children] == ["Launch App", "Press Element"]

def test_fallback_locators_nest_under_the_element_on_their_own_lines():
    ast = _ast((YAML_URI, "Elements:\n  many:\n    - //b\n    - //c\n"))
    element = symbols(ast)[0]
    assert [c.range.start.line for c in element.children] == [2, 3]

def test_workspace_symbols_name_each_kind_apart_in_one_file():
    """A yaml may hold every section, so the container has to be the symbol's own kind:
    `WorkspaceSymbol` has no `detail` to say it anywhere else."""
    multi = _ast((YAML_URI, "Test Cases:\n  - TC:\n      - M\nModules:\n  - M:\n      - Launch App\nElements:\n  e: //a\n"))
    from optics_framework_lsp.symbols import workspace_symbols

    got = {s.name: s.container_name for s in workspace_symbols(multi, "")}
    assert got == {"TC": "test_cases", "M": "modules", "e": "elements"}

def test_the_section_keys_are_highlighted_as_a_csv_header_is():
    assert ("Test Cases", "keyword", 0) in _marked(SUITE)

def test_a_step_is_a_method_when_a_keyword_answers_to_it():
    assert ("Press Element", "method", 1) in _marked(SUITE)

def test_a_step_naming_a_module_is_a_function():
    assert ("Open It", "function", 0) in _marked(SUITE)

def test_a_variable_param_is_highlighted_inside_its_braces():
    assert ("${save}", "variable", 0) in _marked(SUITE)

def test_an_element_and_its_locator_are_named_apart():
    marked = _marked(SUITE)
    assert ("save", "variable", 0) in marked and ("//a", "string", 0) in marked

def test_only_this_files_tokens_are_emitted():
    """`tokens` is handed the whole project's ast, so the per-file filter is what stops
    another file's spans landing at those offsets in this document."""
    other = "Modules:\n  - Elsewhere:\n      - Launch App\nElements:\n  gone: //z\n"
    ast = _ast((YAML_URI, SUITE), ("file:///w/other.yaml", other))
    marked = [text for text, _, _ in _marked(SUITE, ast)]
    assert "Open It" in marked
    assert "Elsewhere" not in marked and "gone" not in marked

# --- the linter --------------------------------------------------------------
def test_the_report_analyses_both_formats_and_names_every_kind():
    body = report(
        [
            ("suite.yaml", SUITE),
            ("test_cases.csv", "test_case,test_step\nTC,Open It\n"),
            ("users.csv", "name,age\nbob,3\n"),
            ("compose.yml", "services:\n  web:\n    image: nginx\n"),
        ],
        CATALOG,
    )
    assert body["analyzed"] == {
        "suite.yaml": "test_cases,modules,elements",
        "test_cases.csv": "test_cases",
    }
    assert body["skipped"] == ["compose.yml", "users.csv"]
    assert body["status"] == "PASS"
