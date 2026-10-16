import xml.etree.ElementTree as ET

from optics_framework_lsp.xpaths import Xpaths, literal


def _of(xml, pick):
    root = ET.fromstring(xml)
    return Xpaths(root).of(pick(root))


def test_a_unique_attribute_is_enough():
    xml = '<r><a name="x"/><a name="y"/></r>'
    assert _of(xml, lambda r: r[0]) == '//a[@name="x"]'


def test_the_unique_attributes_come_before_the_ones_that_may_repeat():
    xml = '<r><a name="id" text="t"/><a name="other" text="t"/></r>'
    assert _of(xml, lambda r: r[0]) == '//a[@name="id"]'


def test_two_attributes_together_are_used_when_neither_is_unique_alone():
    xml = '<r><a resource-id="r" text="1"/><a resource-id="r" text="2"/><a resource-id="s" text="1"/></r>'
    assert _of(xml, lambda r: r[0]) == '//a[@resource-id="r" and @text="1"]'


def test_a_repeated_value_is_numbered_among_its_peers():
    xml = '<r><a text="Next"/><a text="Next"/></r>'
    assert _of(xml, lambda r: r[1]) == '(//a[@text="Next"])[2]'


def test_a_tag_that_occurs_once_needs_no_attribute():
    assert _of("<r><a/><b/></r>", lambda r: r[1]) == "//b"


def test_with_no_unique_attribute_the_path_starts_at_the_nearest_parent_that_has_one():
    xml = '<r><app name="App"><w/><w><t name="list"><c/><c/></t></w></app></r>'
    assert _of(xml, lambda r: r[0][1][0][1]) == '//t[@name="list"]/c[2]'


def test_the_path_from_the_top_is_long_when_nothing_on_the_way_is_unique():
    xml = "<r><w><o><o><b/></o><o/></o></w><w><o><o><b/></o></o></w></r>"
    root = ET.fromstring(xml)

    assert Xpaths(root).of(root[0][0][0][0]) == "/r/w[1]/o/o[1]/b"
    assert Xpaths(root).of(root[1][0][0][0]) == "/r/w[2]/o/o/b"


def test_a_value_with_both_kinds_of_quote_is_written_with_concat():
    assert literal("a") == '"a"'
    assert literal('a"b') == "'a\"b'"
    assert literal("it's \"x\"") == """concat("it's ", '"', "x", '"', "")"""
