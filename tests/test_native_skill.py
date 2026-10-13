from pathlib import Path

import pytest

from optics_framework_lsp.generate import generate

SKILL = Path(__file__).parent.parent / "skills" / "optics-to-native"
EXAMPLE = sorted((SKILL / "examples" / "login").iterdir())


@pytest.mark.parametrize("target,asset", [("uiautomator2", "uiautomator2_example.py"), ("xcuitest", "xcuitest_example.swift")])
def test_the_skills_example_script_is_what_the_generator_writes(target, asset):
    files = [(p.name, p.read_text()) for p in EXAMPLE]
    assert generate(files, target)["source"] == (SKILL / "assets" / asset).read_text()


def _skill_files(folder):
    return {p.relative_to(SKILL).as_posix() for p in (SKILL / folder).iterdir() if p.is_file()}


def test_every_reference_and_asset_is_named_in_the_skill():
    text = (SKILL / "SKILL.md").read_text()
    assert [f for f in sorted(_skill_files("references") | _skill_files("assets")) if f not in text] == []


def test_every_python_snippet_in_the_skill_compiles():
    import re
    import textwrap

    for path in sorted(SKILL.rglob("*.md")):
        for block in re.findall(r"```python\n(.*?)```", path.read_text(), re.S):
            compile(textwrap.dedent(block), path.name, "exec")


def test_the_run_output_asset_compiles():
    compile((SKILL / "assets" / "uiautomator2_run_output.py").read_text(), "run_output", "exec")
