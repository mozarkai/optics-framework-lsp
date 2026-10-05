from pathlib import Path

import pytest

from optics_framework_lsp.generate import generate

SKILL = Path(__file__).parent.parent / "skills" / "optics-to-native"
EXAMPLE = sorted((SKILL / "examples" / "login").iterdir())


@pytest.mark.parametrize("target,asset", [("uiautomator2", "uiautomator2_example.py"), ("xcuitest", "xcuitest_example.swift")])
def test_the_skills_example_script_is_what_the_generator_writes(target, asset):
    files = [(p.name, p.read_text()) for p in EXAMPLE]
    assert generate(files, target)["source"] == (SKILL / "assets" / asset).read_text()
