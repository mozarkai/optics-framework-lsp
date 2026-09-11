# What a yaml suite offers where the cursor is, and what it says about a keyword.

from lsprotocol.types import InsertTextFormat, Position

from optics_framework_lsp import completion
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
    # `direction` is one of the param names `PARAM_VALUES` knows the values of.
    "scroll": Keyword(params=["direction"], required=1, variadic=False, defaults={}, doc=""),
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

def _complete(text, line, character, ast=None, **kwargs):
    got = completion.complete(
        text,
        Position(line=line, character=character),
        ast or _ast(),
        CATALOG,
        uri=YAML_URI,
        **kwargs,
    )
    return [item.label for item in got]

COMMENTED = (
    "# NOTE: only `Suite Setup` is worth using here.\n"
    "# (helper/execute.py:356) explains why.\n"
    "Modules:\n"
    "  # --- lifecycle ---\n"
    "  - Open It:\n"
    "      - Launch App\n"
)

# --- completion --------------------------------------------------------------
def test_an_empty_yaml_offers_the_three_sections():
    assert _complete("", 0, 0) == ["Test Cases:", "Modules:", "Elements:"]

def test_a_section_already_written_is_not_offered_again():
    assert _complete("Modules:\n", 1, 0) == ["Test Cases:", "Elements:"]

def test_a_section_in_the_wrong_case_is_still_offered():
    """It is not a section the file has: the reader never finds it."""
    assert "Modules:" in _complete("modules:\n", 1, 0)

def test_a_test_case_step_offers_modules():
    assert _complete("Test Cases:\n  - TC:\n      - ", 2, 8) == ["Open It"]

def test_a_module_step_offers_keywords_and_modules():
    got = _complete("Modules:\n  - M:\n      - ", 2, 8)
    assert got[0] == "Open It"
    assert "Press Element" in got and "Launch App" in got

def test_a_half_typed_keyword_is_replaced_whole():
    text = "Modules:\n  - M:\n      - Press El"
    got = completion.complete(
        text, Position(line=2, character=16), _ast(), CATALOG, uri=YAML_URI
    )
    edit = next(i.text_edit for i in got if i.label == "Press Element")
    assert (edit.range.start.character, edit.range.end.character) == (8, 16)

def _item(text, line, character, label, **kwargs):
    got = completion.complete(
        text, Position(line=line, character=character), _ast(), CATALOG, uri=YAML_URI, **kwargs
    )
    return next(i for i in got if i.label == label)

def test_a_keyword_arrives_with_its_required_params():
    """Tab walks the holes, so the step is finished by typing values rather than names."""
    item = _item("Modules:\n  - M:\n      - ", 2, 8, "Enter Text", snippets=True)
    assert item.text_edit.new_text == 'Enter Text element="${1:element}" text="${2:text}"'
    assert item.insert_text_format == InsertTextFormat.Snippet

def test_a_param_with_fixed_values_arrives_as_a_choice():
    item = _item("Modules:\n  - M:\n      - ", 2, 8, "Scroll", snippets=True)
    assert item.text_edit.new_text == 'Scroll direction="${1|up,down,left,right|}"'

def test_an_optional_param_is_left_out():
    """`index` defaults, so writing it would be noise to delete."""
    item = _item("Modules:\n  - M:\n      - ", 2, 8, "Press Element", snippets=True)
    assert item.text_edit.new_text == 'Press Element element="${1:element}"'

def test_a_keyword_needing_nothing_stays_a_plain_insert():
    item = _item("Modules:\n  - M:\n      - ", 2, 8, "Launch App", snippets=True)
    assert item.text_edit.new_text == "Launch App" and item.insert_text_format is None

def test_a_client_without_snippet_support_gets_the_name_alone():
    item = _item("Modules:\n  - M:\n      - ", 2, 8, "Enter Text")
    assert item.text_edit.new_text == "Enter Text" and item.insert_text_format is None

def test_a_csv_never_gets_a_snippet():
    """Each param is its own cell there, so there is nothing to walk."""
    got = completion.complete(
        "module_name,module_step\nM,",
        Position(line=1, character=2),
        _ast(),
        CATALOG,
        uri=CSV_URI,
        snippets=True,
    )
    item = next(i for i in got if i.label == "Enter Text")
    assert item.text_edit.new_text == "Enter Text"

STEP = "Modules:\n  - M:\n      - {}\nElements:\n  save: //a\n"

def _offered(step, **kwargs):
    """A step with `|` for the cursor: what is offered there."""
    text = STEP.format(step.replace("|", ""))
    where = Position(line=2, character=len("      - ") + step.index("|"))
    return completion.complete(text, where, _ast((YAML_URI, text)), CATALOG, uri=YAML_URI, **kwargs)

def _applied(step, label, **kwargs):
    """The step line after accepting `label`, which is what checks the edit's range."""
    line = "      - " + step.replace("|", "")
    edit = next(i.text_edit for i in _offered(step, **kwargs) if i.label == label)
    got = line[: edit.range.start.character] + edit.new_text + line[edit.range.end.character :]
    return got[len("      - ") :]

def test_a_ref_inside_a_named_param_is_completed_in_place():
    """The `name="` is not part of what is being typed, so replacing the whole token
    would both nest and stop the client from matching what was typed against it."""
    assert _applied('Press Element element="${|}"', "save") == 'Press Element element="${save}"'

def test_a_named_param_offers_what_that_param_holds():
    assert [i.label for i in _offered('Scroll direction="|"')] == ["up", "down", "left", "right"]
    assert _applied('Scroll direction="|"', "up") == 'Scroll direction="up"'

def test_the_name_decides_the_slot_rather_than_the_position():
    """`element` is press element's first param wherever it is written. By position this
    token is the second, `index`, which holds a number and so offers nothing."""
    assert [i.label for i in _offered('Press Element index="0" element="${|}"')] == ["save"]
    assert _offered('Press Element ${save} index="|"') == []

def test_a_positional_beside_a_named_param_binds_by_its_own_count():
    """`index=` took the second slot, so the bare token is still the first, the element --
    counting tokens instead would read it as the second and offer nothing."""
    assert [i.label for i in _offered('Press Element index="0" ${|}')] == ["save"]

def test_a_literal_param_still_reaches_the_variables_behind_a_dollar():
    """The gate is on what is typed in the value, which `duration="` is not part of."""
    assert [i.label for i in _offered('Sleep duration="${|}"')] == ["save"]
    assert _offered('Sleep duration="|"') == []

def test_a_locator_that_merely_holds_an_equals_is_one_value():
    """`text=` is no param of press element, so the token is the element, as the runner
    reads it -- completing inside it must not treat `text` as a name."""
    assert _applied('Press Element text=|', "save") == "Press Element ${save}"

def test_a_quoted_positional_value_is_completed_inside_its_quotes():
    assert _applied('Press Element "${|}"', "save") == 'Press Element "${save}"'

def test_a_param_slot_offers_the_projects_variables():
    assert _complete("Modules:\n  - M:\n      - Press Element ", 2, 24) == ["save"]

def test_a_params_documented_values_win_over_variables():
    got = _complete("Modules:\n  - M:\n      - Read Data ${x} ", 2, 25, data_files=["d.csv"])
    assert got == ["d.csv"]

def test_a_literal_param_offers_nothing_until_a_variable_is_started():
    # `index` is a number. Nothing belongs there, but `Press Element ${save} ${n}` is how
    # a yaml writes one, so the elements stay reachable behind the `$`.
    line = "Modules:\n  - M:\n      - Press Element ${save} "
    assert _complete(line, 2, 31) == []
    assert _complete(line + "${", 2, 33) == ["save"]

def test_an_element_name_offers_what_is_used_but_undefined():
    ast = _ast((YAML_URI, "Modules:\n  - M:\n      - Press Element ${gone}\n"))
    assert _complete("Elements:\n  ", 1, 2, ast=ast) == ["gone"]

def test_an_element_locator_offers_template_images():
    assert _complete("Elements:\n  a: ", 1, 5, images=["alarm.png"]) == ["alarm.png"]

# --- hover and signature help ------------------------------------------------
def test_hover_answers_anywhere_inside_a_multi_word_keyword():
    for offset in (0, 7, 12):
        found = completion.hover(SUITE, _at("Press Element", offset), CATALOG, uri=YAML_URI)
        assert found is not None and found.contents.value.startswith("Press Element(")

def test_hover_is_silent_on_a_param():
    assert completion.hover(SUITE, _at("${save}", 2), CATALOG, uri=YAML_URI) is None

def test_signature_help_marks_the_word_the_cursor_is_on():
    text = "Modules:\n  - M:\n      - Enter Text ${f} "
    found = completion.signature(text, Position(line=2, character=25), CATALOG, uri=YAML_URI)
    assert found is not None and found.active_parameter == 1

def test_a_comment_holding_a_colon_is_not_a_section():
    """A real suite documents itself, and `# NOTE: ...` at the left margin otherwise
    reads as a key — which would leave every line under it in no section at all."""
    from optics_framework_lsp.yaml_cursor import sections

    assert [key for _, key in sections(COMMENTED.splitlines())] == ["Modules"]

def test_completion_still_knows_the_section_under_a_commented_header():
    got = _complete(COMMENTED + "      - ", 6, 8, ast=_ast((YAML_URI, COMMENTED)))
    assert "Launch App" in got and "Open It" in got

def test_flow_style_parses_but_offers_no_navigation():
    """A deliberate limit. The parser reads flow style, so diagnostics and the outline
    work, but the cursor scan is built on indentation and cannot see into one line — so
    hover, goto and rename stay quiet rather than answering wrongly. Nothing writes
    suites this way: no sample, no doc and no `optics init` output does."""
    flow = "Modules: [{M: ['Press Element ${btn}']}]\nElements: {btn: //a}\n"
    ast = _ast((YAML_URI, flow))
    assert [b.name for b in ast.modules] == ["M"]

    inside = Position(line=0, character=flow.index("Press Element") + 2)
    assert completion.hover(flow, inside, CATALOG, uri=YAML_URI) is None
    assert completion.definition(flow, inside, ast, CATALOG, uri=YAML_URI) == []
