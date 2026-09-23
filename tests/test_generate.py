"""`generate`: a suite as a native script, and the account of what did not come across."""

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from optics_framework_lsp.generate import generate
from optics_framework_lsp.generate.targets import TARGETS
from optics_framework_lsp.keywords import KEYWORDS

CONFIG = """
driver_sources:
  - appium:
      enabled: true
      capabilities:
        appPackage: com.example.app
        appActivity: com.example.app.Main
        deviceName: emulator-5554
        platformName: Android
"""
# One xpath and one accessibility id, in each platform's dialect.
ANDROID = "Element_Name,Element_ID\nBtn,//android.widget.Button\nLabel,Sign in\n"
IOS = 'Element_Name,Element_ID\nBtn,"//XCUIElementTypeButton[@name=""Go""]"\nLabel,Sign in\n'
MODULES = (
    "module_name,module_step,param_1,param_2\n"
    "Open,Launch App,,\n"
    "Open,Press Element,${Btn},\n"
    "Open,Assert Presence,${Label},\n"
)
CASES = "test_case,test_step\nSign In,Open\n"


def _suite(elements: str = ANDROID, **extra) -> list[tuple[str, str]]:
    files = {
        "config.yaml": CONFIG,
        "test_data/elements.csv": elements,
        "modules/modules.csv": MODULES,
        "test_cases/test_cases.csv": CASES,
    }
    files.update(extra)
    return list(files.items())


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_every_keyword_is_either_emitted_or_explained(target):
    """The check that keeps a target's table from drifting the way `helper/generate.py` did:
    a keyword the catalog gains must be given a translation or a reason, not skipped."""
    backend = TARGETS[target]
    assert set(backend.EMIT) | set(backend.UNSUPPORTED) == set(KEYWORDS)
    assert not (set(backend.EMIT) & set(backend.UNSUPPORTED))


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_a_target_names_its_file_extension(target):
    assert generate(_suite(), target)["extension"].startswith(".")


def test_an_unknown_target_is_refused():
    with pytest.raises(ValueError, match="espresso"):
        generate(_suite(), target="espresso")


# ---------------------------------------------------------------- uiautomator2


def test_the_generated_python_is_valid():
    ast.parse(generate(_suite())["source"])


def test_a_module_becomes_a_function_and_a_test_case_calls_it():
    source = generate(_suite())["source"]
    assert "def open(d):" in source
    assert "def test_sign_in(d):" in source
    assert "    open(d)" in source


def test_a_locator_is_split_from_an_accessibility_id_at_run_time():
    """uiautomator2 can take an xpath, so both reach `_find` as plain strings."""
    source = generate(_suite())["source"]
    assert "'Btn': '//android.widget.Button'" in source
    assert "_find(d, ELEMENTS['Btn']).click()" in source


def test_the_appium_capabilities_become_the_script_constants():
    source = generate(_suite())["source"]
    assert "PACKAGE = 'com.example.app'" in source
    assert "ACTIVITY = 'com.example.app.Main'" in source
    assert "SERIAL = 'emulator-5554'" in source


def test_a_clean_suite_reports_nothing():
    assert generate(_suite())["unsupported"] == []


def test_a_variable_reference_reads_the_variable_store():
    modules = "module_name,module_step,param_1,param_2\nOpen,Enter Text,${Btn},${user}\n"
    source = generate(_suite(**{"modules/modules.csv": modules}))["source"]
    assert "_find(d, ELEMENTS['Btn']).set_text(VARS['user'])" in source


# ---------------------------------------------------------------------- shared


def test_an_unsupported_keyword_is_reported_with_its_reason_and_emits_nothing():
    modules = MODULES + "Open,Invoke API,login,\n"
    found = generate(_suite(**{"modules/modules.csv": modules}))
    assert "invoke_api" not in found["source"]
    (finding,) = found["unsupported"]
    assert finding["code"] == "unsupported-keyword"
    assert finding["uri"] == "modules/modules.csv"


def test_a_keyword_unsupported_on_one_target_only_says_so_per_target():
    """`press keycode` translates on android and has no ios form at all."""
    modules = "module_name,module_step,param_1\nOpen,Press Keycode,4\n"
    files = _suite(**{"modules/modules.csv": modules})
    assert generate(files, "uiautomator2")["unsupported"] == []
    reasons = [f["message"] for f in generate(files, "xcuitest")["unsupported"]]
    assert any("android keycodes" in reason for reason in reasons)


def test_an_image_template_is_reported_and_the_steps_using_it_are_too():
    """Reporting the element alone would leave a step emitting a call to nothing."""
    elements = ANDROID + "Logo,logo.png\n"
    modules = MODULES + "Open,Press Element,${Logo},\n"
    found = generate(_suite(elements, **{"modules/modules.csv": modules}))
    codes = [f["code"] for f in found["unsupported"]]
    assert codes == ["unusable-locator", "unusable-locator"]
    assert "logo.png" not in found["source"]


def test_params_the_translation_drops_are_named():
    """`press element`'s repeat has no native form; saying so beats trimming it in silence."""
    modules = "module_name,module_step,param_1,param_2\nOpen,Press Element,${Btn},3\n"
    found = generate(_suite(**{"modules/modules.csv": modules}))
    (finding,) = found["unsupported"]
    assert finding["code"] == "params-dropped"
    assert "repeat" in finding["message"]


def test_a_step_naming_a_module_becomes_a_call_to_it():
    """What `execute_module` does at run time, done at generation time instead."""
    modules = MODULES + "Login,Open,,\n"
    source = generate(_suite(**{"modules/modules.csv": modules}))["source"]
    assert "def login(d):" in source
    assert "    open(d)" in source


def test_a_step_that_is_neither_keyword_nor_module_is_reported():
    modules = "module_name,module_step,param_1\nOpen,Clik on Thing,\n"
    found = generate(_suite(**{"modules/modules.csv": modules}))
    assert found["unsupported"][0]["code"] == "unknown-step"


# -------------------------------------------------------------------- xcuitest


def test_an_xpath_is_carried_into_the_file_rather_than_translated():
    """No query is a translation of an xpath: its index counts per parent where a query
    flattens, and it was written against a tree a query does not walk. So the locator travels
    as text and is evaluated on the device, against a snapshot of the real hierarchy."""
    source = generate(_suite(IOS), "xcuitest")["source"]
    assert '"Btn": "//XCUIElementTypeButton[@name=\\"Go\\"]"' in source
    assert "func evaluate(_ raw: String) -> [Node]" in source
    assert "try? app.snapshot()" in source


def test_a_locator_is_resolved_by_name_so_a_wait_can_re_resolve():
    """An element taken once before a wait is a handle on nothing: the thing being waited
    for does not exist yet. So the waiting keywords carry the name, not the element."""
    modules = (
        "module_name,module_step,param_1,param_2\n"
        "Open,Assert Presence,${Btn},5\n"
        "Open,Press Element,${Btn},\n"
    )
    source = generate(_suite(IOS, **{"modules/modules.csv": modules}), "xcuitest")["source"]
    assert 'XCTAssertTrue(waitFor("Btn", Double("5") ?? 30), "Btn")' in source
    assert 'el("Btn").tap()' in source


def test_a_plain_string_needs_no_snapshot():
    """It names screen text or an accessibility id, which has no path to walk."""
    source = generate(_suite(IOS), "xcuitest")["source"]
    assert '"Label": "Sign in"' in source
    assert 'identifier == %@ OR label == %@ OR value == %@' in source


def test_an_element_param_that_is_not_a_declared_element_still_resolves():
    """It falls through the locator table and is looked up as text, which is what optics
    does with a bare string too."""
    modules = "module_name,module_step,param_1\nOpen,Press Element,Continue\n"
    source = generate(_suite(IOS, **{"modules/modules.csv": modules}), "xcuitest")["source"]
    assert 'el("Continue").tap()' in source


def test_a_locator_naming_a_type_ios_does_not_have_is_refused():
    """Carrying it through would leave a step that matches nothing on every run, silently.
    This is the whole of what can be judged here -- the path itself is the device's to read."""
    found = generate(_suite(ANDROID), "xcuitest")
    reasons = [f["message"] for f in found["unsupported"] if f["code"] == "unusable-locator"]
    assert any("not an XCUIElementType" in reason for reason in reasons)


def test_an_xpath_shape_the_evaluator_cannot_read_is_refused():
    elements = 'Element_Name,Element_ID\nOdd,"//XCUIElementTypeCell/following-sibling::x"\n'
    found = generate(_suite(elements, **{"modules/modules.csv": "module_name,module_step\n"}), "xcuitest")
    (finding,) = [f for f in found["unsupported"] if f["uri"].endswith("elements.csv")]
    assert finding["code"] == "unusable-locator"


def test_a_swipe_starts_where_the_suite_said():
    """It names a coordinate and a length; swiping the whole screen instead is a different
    gesture that happens to look similar."""
    modules = "module_name,module_step,param_1,param_2,param_3,param_4\nOpen,Swipe,40,80,up,150\n"
    source = generate(_suite(IOS, **{"modules/modules.csv": modules}), "xcuitest")["source"]
    assert 'swipeAt("40", "80", "up", Double("150") ?? 200)' in source
    assert "thenDragTo" in source


def test_a_swipe_without_a_length_still_has_one():
    modules = "module_name,module_step,param_1,param_2,param_3\nOpen,Swipe By Percentage,50,90,down\n"
    source = generate(_suite(IOS, **{"modules/modules.csv": modules}), "xcuitest")["source"]
    assert 'swipePercent("50", "90", "down", 200)' in source


def test_the_shapes_a_query_could_not_express_are_carried_through():
    """`last()`, a predicate mid-path, a grouped index -- all refused by the old translation,
    all ordinary to an evaluator."""
    elements = (
        "Element_Name,Element_ID\n"
        "Last,//XCUIElementTypeButton[last()]\n"
        "Grouped,(//XCUIElementTypeTextField)[4]\n"
        "Wild,//XCUIElementTypeTable/*[2]\n"
        'Fn,"//XCUIElementTypeStaticText[contains(@label,""paid"")]"\n'
    )
    found = generate(_suite(elements, **{"modules/modules.csv": "module_name,module_step\n"}), "xcuitest")
    assert [f for f in found["unsupported"] if f["uri"].endswith("elements.csv")] == []


def _ios_toolchain():
    """The simulator SDK and the XCTest swift overlay, or None where Xcode is not installed.

    `swiftc -parse` would run anywhere, but it only checks syntax -- it says nothing about
    whether `descendants(...).children(...)` is a call XCUIElementQuery actually has. Only a
    typecheck against the real SDK answers that, which is the whole risk in this target.
    """
    if shutil.which("xcrun") is None:
        return None
    sdk = subprocess.run(
        ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], capture_output=True, text=True
    )
    developer = (
        "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneSimulator.platform/Developer"
    )
    if sdk.returncode != 0 or not Path(f"{developer}/usr/lib/XCTest.swiftmodule").exists():
        return None
    return sdk.stdout.strip(), developer


@pytest.mark.skipif(_ios_toolchain() is None, reason="needs Xcode and the iOS simulator SDK")
def test_the_generated_swift_typechecks_against_the_ios_sdk(tmp_path):
    sdk, developer = _ios_toolchain()
    swift = tmp_path / "Generated.swift"
    swift.write_text(generate(_suite(IOS), "xcuitest")["source"])
    done = subprocess.run(
        ["xcrun", "swiftc", "-typecheck", "-sdk", sdk,
         "-target", "arm64-apple-ios17.0-simulator",
         "-F", f"{developer}/Library/Frameworks", "-I", f"{developer}/usr/lib", str(swift)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


# ------------------------------------------------------------------------- cli


def test_the_cli_writes_the_script_to_stdout_and_the_report_to_stderr(tmp_path):
    """So `optics-lsp generate . > suite.py` is a runnable file, not a file with a report
    stuck on the end of it."""
    (tmp_path / "modules").mkdir()
    (tmp_path / "config.yaml").write_text(CONFIG)
    (tmp_path / "elements.csv").write_text(ANDROID)
    (tmp_path / "modules" / "m.csv").write_text(MODULES + "Open,Invoke API,login,\n")
    (tmp_path / "cases.csv").write_text(CASES)

    done = subprocess.run(
        [sys.executable, "-m", "optics_framework_lsp.cli", "generate", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0
    ast.parse(done.stdout)
    assert "1 steps did not translate" in done.stderr
    assert "did not translate" not in done.stdout


def test_the_cli_takes_a_target(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG)
    (tmp_path / "elements.csv").write_text(IOS)
    (tmp_path / "m.csv").write_text(MODULES)
    (tmp_path / "cases.csv").write_text(CASES)

    done = subprocess.run(
        [sys.executable, "-m", "optics_framework_lsp.cli", "generate", str(tmp_path),
         "--target", "xcuitest"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0
    assert "import XCTest" in done.stdout
