# Following and moving a name in a yaml suite, and across the two formats.

from lsprotocol.types import Position

from optics_framework_lsp import completion, rename as renaming
from optics_framework_lsp.keyword_catalog import Keyword
from optics_framework_lsp.parser import parse_sources

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

# --- rename ------------------------------------------------------------------
def _applied(edits, uri, text):
    lines = text.splitlines()
    for edit in sorted(edits.get(uri, []), key=lambda e: -e.range.start.character):
        row = edit.range.start.line
        lines[row] = (
            lines[row][: edit.range.start.character]
            + edit.new_text
            + lines[row][edit.range.end.character :]
        )
    return "\n".join(lines)

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

NESTED = (
    "Modules:\n"
    "  - Outer:\n"
    "      - Inner\n"
    "  - Inner:\n"
    "      - Launch App\n"
)

# --- goto and references -----------------------------------------------------
def test_goto_reaches_a_module_from_a_test_step():
    found = completion.definition(SUITE, _at("Open It", 2), _ast(), CATALOG, uri=YAML_URI)
    assert [at.range.start.line for at in found] == [4]

def test_goto_reaches_an_element_from_a_param():
    found = completion.definition(SUITE, _at("${save}", 3), _ast(), CATALOG, uri=YAML_URI)
    assert [at.range.start.line for at in found] == [8]

def test_references_to_a_module_find_the_test_step():
    found = completion.references(SUITE, _at("- Open It:", 4), _ast(), CATALOG, uri=YAML_URI)
    assert [at.range.start.line for at in found] == [2]

def test_references_to_an_element_include_its_declaration():
    found = completion.references(
        SUITE, _at("save: //a"), _ast(), CATALOG, uri=YAML_URI, include_declaration=True
    )
    assert [at.range.start.line for at in found] == [6, 8]

def test_references_to_a_keyword_are_its_uses():
    found = completion.references(SUITE, _at("Launch App", 2), _ast(), CATALOG, uri=YAML_URI)
    assert [at.range.start.line for at in found] == [5]

def test_renaming_a_module_moves_its_definition_and_its_uses():
    sources = [(YAML_URI, SUITE)]
    edits = renaming.rename(sources, CATALOG, SUITE, _at("- Open It:", 4), "Start", uri=YAML_URI)
    assert edits is not None
    got = _applied(edits, YAML_URI, SUITE)
    assert "  - Start:" in got and "      - Start" in got

def test_renaming_an_element_moves_only_the_name_inside_its_braces():
    edits = renaming.rename(
        [(YAML_URI, SUITE)], CATALOG, SUITE, _at("${save}", 3), "button", uri=YAML_URI
    )
    assert edits is not None
    got = _applied(edits, YAML_URI, SUITE)
    assert "${button}" in got and "  button: //a" in got

def test_a_keyword_is_not_renameable():
    assert renaming.prepare(SUITE, _at("Launch App", 2), CATALOG, uri=YAML_URI) is None

def test_prepare_offers_the_name_without_its_braces():
    found = renaming.prepare(SUITE, _at("${save}", 3), CATALOG, uri=YAML_URI)
    assert found is not None
    assert (found.start.character, found.end.character) == (24, 28)

def test_a_rename_crosses_the_two_formats():
    """The runner keys by name and picks a reader per file, so one name spans both."""
    csv = "test_case,test_step\nTC,Open It\n"
    sources = [(CSV_URI, csv), (YAML_URI, SUITE)]
    edits = renaming.rename(sources, CATALOG, SUITE, _at("- Open It:", 4), "Start", uri=YAML_URI)
    assert edits is not None and set(edits) == {CSV_URI, YAML_URI}
    assert _applied(edits, CSV_URI, csv).endswith("TC,Start")

def test_a_rename_driven_from_the_csv_side_edits_the_yaml():
    """The other direction of the same question: the cursor may sit in either format."""
    csv = "test_case,test_step\nTC,Open It\n"
    sources = [(CSV_URI, csv), (YAML_URI, SUITE)]
    edits = renaming.rename(
        sources, CATALOG, csv, Position(line=1, character=4), "Start", uri=CSV_URI
    )
    assert edits is not None and set(edits) == {CSV_URI, YAML_URI}
    assert "  - Start:" in _applied(edits, YAML_URI, SUITE)

def test_renaming_a_test_case_moves_its_name():
    edits = renaming.rename(
        [(YAML_URI, SUITE)], CATALOG, SUITE, _at("- Add Contact:", 4), "Added",
        uri=YAML_URI,
    )
    assert edits is not None
    assert "  - Added:" in _applied(edits, YAML_URI, SUITE)

def test_renaming_a_module_reaches_a_nested_call_in_another_module():
    """A step may name a module rather than a keyword, and that is a use like any other."""
    edits = renaming.rename(
        [(YAML_URI, NESTED)], CATALOG, NESTED, _at("- Inner:", 4, NESTED), "Deeper",
        uri=YAML_URI,
    )
    assert edits is not None
    got = _applied(edits, YAML_URI, NESTED)
    assert "      - Deeper" in got and "  - Deeper:" in got

def test_renaming_an_element_reaches_a_name_a_step_binds():
    """`Run Loop` binds every other param after its target, and those are bare words."""
    text = (
        "Modules:\n"
        "  - M:\n"
        "      - Run Loop ${target} i ${items}\n"
        "Elements:\n"
        "  target: //a\n"
        "  items: //b\n"
    )
    edits = renaming.rename(
        [(YAML_URI, text)], CATALOG, text, _at("i ${items}", 0, text), "index", uri=YAML_URI
    )
    assert edits is not None
    assert "Run Loop ${target} index ${items}" in _applied(edits, YAML_URI, text)

def test_renaming_an_element_inside_a_quoted_param_moves_the_name_alone():
    """The span covers the quotes the reader strips, so an edit measured from its start
    lands one character early and leaves `element="$button}"` behind."""
    text = 'Modules:\n  - M:\n      - Press Element element="${save}"\nElements:\n  save: //a\n'
    edits = renaming.rename(
        [(YAML_URI, text)], CATALOG, text, _at("${save}", 2, text), "button", uri=YAML_URI
    )
    assert edits is not None
    got = _applied(edits, YAML_URI, text)
    assert 'Press Element element="${button}"' in got and "  button: //a" in got

def test_renaming_a_module_reaches_one_a_param_names():
    """`target=` runs the module wherever it is written, so that is a call site too."""
    text = (
        "Modules:\n"
        "  - M:\n"
        '      - Run Loop target="Other" 2\n'
        "  - Other:\n"
        "      - Launch App\n"
    )
    edits = renaming.rename(
        [(YAML_URI, text)], CATALOG, text, _at("- Other:", 4, text), "Later", uri=YAML_URI
    )
    assert edits is not None
    got = _applied(edits, YAML_URI, text)
    assert 'Run Loop target="Later" 2' in got and "  - Later:" in got

def test_references_reach_a_module_in_a_condition_target():
    found = completion.references(
        CONDITION, _at("- Target:", 4, CONDITION), _ast((YAML_URI, CONDITION)),
        CATALOG, uri=YAML_URI,
    )
    assert [at.range.start.line for at in found] == [2]

def test_renaming_a_condition_target_keeps_its_inverting_bang():
    ast_sources = [(YAML_URI, CONDITION)]
    edits = renaming.rename(
        ast_sources, CATALOG, CONDITION, _at("- Target:", 4, CONDITION), "Other",
        uri=YAML_URI,
    )
    assert edits is not None
    got = _applied(edits, YAML_URI, CONDITION)
    assert "Condition ${flag} Other ${other} !Other" in got
