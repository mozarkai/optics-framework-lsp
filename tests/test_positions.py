# Columns on the wire, for both formats.
#
# A client counts a line in utf-16 code units and Python counts code points. They agree
# until a character outside the basic plane, which is one code point and two units — so
# every column we emit after one lands early unless it is converted.

from lsprotocol.types import Position

from optics_framework_lsp import completion, rename as renaming
from optics_framework_lsp.keyword_catalog import CATALOG
from optics_framework_lsp.parser import parse_sources
from optics_framework_lsp.positions import from_utf16, to_utf16
from optics_framework_lsp.symbols import symbols
from optics_framework_lsp.tokens import LEGEND, tokens

CSV_URI = "file:///w/e.csv"
YAML_URI = "file:///w/s.yaml"


def _units(line: str, index: int) -> int:
    """What a client would count, worked out the long way round."""
    return len(line[:index].encode("utf-16-le")) // 2


def test_a_line_of_ascii_needs_no_conversion():
    assert (to_utf16("plain text", 6), from_utf16("plain text", 6)) == (6, 6)


def test_a_character_outside_the_basic_plane_is_two_units():
    line = "a🎉b"
    assert [to_utf16(line, i) for i in range(4)] == [0, 1, 3, 4]


def test_the_conversion_round_trips():
    line = "      - Press Element ${🎉} ${b}"
    for index in range(len(line) + 1):
        assert from_utf16(line, to_utf16(line, index)) == index


def test_a_column_the_client_sends_is_read_as_a_code_point():
    """The other direction: a cursor past an emoji must land on the right word."""
    text = "module_name,module_step\n🎉M,Press Element\n"
    row = text.splitlines()[1]
    found = completion.hover(
        text, Position(line=1, character=_units(row, row.index("Press"))), CATALOG
    )
    assert found is not None and found.contents.value.startswith("Press Element(")


ELEMENTS = "element_name,element_id\n🎉btn,//a\n"


def test_a_csv_locator_token_is_measured_in_units():
    row = ELEMENTS.splitlines()[1]
    data = tokens(ELEMENTS, parse_sources([(CSV_URI, ELEMENTS)]), CATALOG, uri=CSV_URI)

    line = char = 0
    for i in range(0, len(data), 5):
        delta_line, delta_char, _, kind, _ = data[i : i + 5]
        line += delta_line
        char = delta_char if delta_line else char + delta_char
        if line == 1 and LEGEND[kind] == "string":
            assert char == _units(row, row.index("//a"))
            return
    raise AssertionError("no locator token")


def test_a_csv_outline_is_measured_in_units():
    """`symbols` is handed an ast and no text, so the server converts on its behalf."""
    from optics_framework_lsp.server import _reencode

    row = ELEMENTS.splitlines()[1]
    outline = symbols(parse_sources([(CSV_URI, ELEMENTS)]))
    _reencode(outline, ELEMENTS.splitlines())

    (locator,) = outline[0].children or []
    assert locator.range.start.character == _units(row, row.index("//a"))


def test_a_csv_completion_replaces_the_right_span():
    text = "module_name,module_step\n🎉M,Press El"
    row = text.splitlines()[1]
    got = completion.complete(
        text,
        Position(line=1, character=_units(row, len(row))),
        parse_sources([(CSV_URI, text)]),
        CATALOG,
        uri=CSV_URI,
    )
    edit = next(i for i in got if i.label == "Press Element").text_edit
    assert edit is not None
    assert edit.range.start.character == _units(row, row.index("Press El"))


SUITE = (
    "Modules:\n"
    "  - M:\n"
    "      - Press Element ${🎉} ${btn}\n"
    "Elements:\n"
    "  btn: //a\n"
    "  '🎉': //b\n"
)


def test_a_yaml_rename_edits_the_right_span():
    row = SUITE.splitlines()[2]
    at = Position(line=2, character=_units(row, row.index("${btn}") + 2))
    edits = renaming.rename([(YAML_URI, SUITE)], CATALOG, SUITE, at, "saved", uri=YAML_URI)

    assert edits is not None
    (edit,) = [e for e in edits[YAML_URI] if e.range.start.line == 2]
    assert edit.range.start.character == _units(row, row.index("${btn}") + 2)


def test_a_yaml_token_after_one_is_measured_in_units():
    row = SUITE.splitlines()[2]
    data = tokens(SUITE, parse_sources([(YAML_URI, SUITE)]), CATALOG, uri=YAML_URI)

    line = char = 0
    seen = []
    for i in range(0, len(data), 5):
        delta_line, delta_char, length, kind, _ = data[i : i + 5]
        line += delta_line
        char = delta_char if delta_line else char + delta_char
        if line == 2 and LEGEND[kind] == "variable":
            seen.append((char, length))
    # The length is units too: `${🎉}` is four code points and five of them.
    assert seen == [
        (_units(row, row.index("${🎉}")), 5),
        (_units(row, row.index("${btn}")), 6),
    ]
