"""`generate`: a suite as a native script, and the account of what did not come across."""

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from optics_framework_lsp.generate import as_text, generate
from optics_framework_lsp.generate.locators import kind, normalise
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
    assert "'Btn': ['//android.widget.Button']" in source
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


BASE = {"uiautomator2": ANDROID, "xcuitest": IOS}


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_no_script_is_written_when_a_step_uses_an_element_with_no_usable_locator(target):
    """A script without that step would pass while testing less than the suite does."""
    elements = BASE[target] + "Logo,logo.png\n"
    modules = MODULES + "Open,Press Element,${Logo},\n"
    found = generate(_suite(elements, **{"modules/modules.csv": modules}), target)
    assert found["source"] is None
    assert sorted(f["code"] for f in found["unsupported"]) == ["needs-unusable-element", "unusable-locator"]


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_an_element_nothing_uses_is_reported_but_does_not_stop_the_script(target):
    """Element tables are shared between suites; a row this one never touches is not its
    problem to block on."""
    found = generate(_suite(BASE[target] + "Logo,logo.png\n"), target)
    assert found["source"] is not None
    assert [f["code"] for f in found["unsupported"]] == ["unusable-locator"]


def test_a_reference_inside_a_longer_cell_is_left_as_the_runner_leaves_it():
    """The runner resolves a cell only when it is one whole `${name}`; `${a}|${b}` reaches
    the keyword as text. Resolving it here would make the script do what optics does not,
    and it is not a use of the element that could block the script either."""
    elements = ANDROID + "Logo,logo.png\n"
    modules = MODULES + "Open,Assert Presence,${Btn}|${Logo},\n"
    found = generate(_suite(elements, **{"modules/modules.csv": modules}))
    assert found["source"] is not None
    assert "'${Btn}|${Logo}'" in found["source"]
    assert "needs-unusable-element" not in [f["code"] for f in found["unsupported"]]


def test_the_cli_writes_nothing_and_fails_when_the_script_is_refused(tmp_path):
    """So `optics-lsp generate . > suite.py` fails where it can be seen, rather than leaving a
    partial script behind with a zero exit."""
    (tmp_path / "config.yaml").write_text(CONFIG)
    (tmp_path / "elements.csv").write_text(ANDROID + "Logo,logo.png\n")
    (tmp_path / "m.csv").write_text(MODULES + "Open,Press Element,${Logo},\n")
    (tmp_path / "cases.csv").write_text(CASES)

    done = subprocess.run(
        [sys.executable, "-m", "optics_framework_lsp.cli", "generate", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert done.returncode == 1
    assert done.stdout == ""
    assert "no script written" in done.stderr


def test_a_refusal_names_each_element_every_reason_and_the_steps_that_need_it():
    """Enough to fix the suite from the message alone, with the blocking cause first and what
    would not have blocked kept apart from it."""
    elements = ANDROID + "Logo,logo.png\nLogo,.brand\nUnused,unused.png\n"
    modules = MODULES + "Open,Press Element,${Logo},\nOpen,Invoke API,login,\n"
    body = generate(_suite(elements, **{"modules/modules.csv": modules}))
    text = as_text(body)
    first, _, rest = text.partition("\n")
    assert first.startswith("error: no script written") and "1 element(s)" in first
    blocking, _, after = rest.partition("Also not translatable")
    assert "logo.png" in blocking and ".brand" in blocking
    assert "image template" in blocking and "css selector" in blocking
    assert "needed by" in blocking and "Press Element" in blocking
    assert "Unused" not in blocking and "Invoke API" not in blocking
    assert "Unused" in after and "Invoke API" in after


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
    assert '"Btn": ["//XCUIElementTypeButton[@name=\\"Go\\"]"]' in source
    assert "func evaluate(_ raw: String, in root: Node) -> [Node]" in source
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
    assert 'XCTAssertTrue(waitForAll("Btn", Double("5") ?? 30, "any"), "Btn")' in source
    assert 'el("Btn").tap()' in source


def test_a_plain_string_needs_no_snapshot():
    """It names screen text or an accessibility id, which has no path to walk."""
    source = generate(_suite(IOS), "xcuitest")["source"]
    assert '"Label": ["Sign in"]' in source
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
@pytest.mark.parametrize("suite", ["plain", "colliding", "keywords", "launch"])
def test_the_generated_swift_typechecks_against_the_ios_sdk(tmp_path, suite):
    sdk, developer = _ios_toolchain()
    swift = tmp_path / "Generated.swift"
    files = {"plain": _suite, "colliding": _colliding, "keywords": _keyword_suite, "launch": _launch_suite}[suite](IOS)
    swift.write_text(generate(files, "xcuitest")["source"])
    done = subprocess.run(
        ["xcrun", "swiftc", "-typecheck", "-sdk", sdk,
         "-target", "arm64-apple-ios17.0-simulator",
         "-F", f"{developer}/Library/Frameworks", "-I", f"{developer}/usr/lib", str(swift)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


# ------------------------------------------------------------------------ kinds


@pytest.mark.parametrize(
    "locator,expected",
    [
        ("Payment successful!", "text"),
        ("#91", "text"),                      # not a css id: a digit cannot start one
        ("text=Continue", "text"),
        ("text_only:Continue", "text_only"),
        ("paynow.png", "image"),
        ("css=button.primary", "css"),
        ("#login_btn", "css"),
        ("input[name='user']", "css"),
        ("//XCUIElementTypeButton", "xpath"),
        ("xpath=//a/b", "xpath"),
        ("id:login_btn", "id"),
        ("android.widget.Button", "klass"),
        ("XCUIElementTypeButton", "klass"),
    ],
)
def test_a_locator_is_sorted_as_the_framework_sorts_it(locator, expected):
    """`determine_element_type` decides this before any strategy sees a locator, and a
    generated script that guesses differently looks for the wrong thing."""
    assert kind(locator) == expected


@pytest.mark.parametrize(
    "locator,expected",
    [
        ("xpath=//a/b", "//a/b"),
        ("text=Continue", "Continue"),
        ("android.widget.Button", "//android.widget.Button"),
        ("XCUIElementTypeButton", "//XCUIElementTypeButton"),
        ("Payment successful!", "Payment successful!"),
    ],
)
def test_a_prefix_the_framework_owns_does_not_travel(locator, expected):
    """`text=` and `xpath=` name how to read the rest, not what is on screen. A class is the
    node test of the path that finds one, so it is written that way rather than looked up
    some second way."""
    assert normalise(locator) == expected


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize(
    "locator", ["text_only:Continue", "paynow.png", "css=button.primary", "#login_btn", "id:x"]
)
def test_a_kind_with_no_native_form_is_refused_rather_than_matched_as_text(target, locator):
    """Each of these used to fall through as an accessibility id, so the generated lookup
    searched for the framework's own prefix and could never match -- and said nothing."""
    elements = f'Element_Name,Element_ID\nOdd,"{locator}"\n'
    found = generate(_suite(elements, **{"modules/modules.csv": "module_name,module_step\n"}), target)
    (finding,) = [f for f in found["unsupported"] if f["uri"].endswith("elements.csv")]
    assert finding["code"] == "unusable-locator"


def test_each_target_refuses_the_other_platform_s_classes():
    ios = 'Element_Name,Element_ID\nC,XCUIElementTypeSecureTextField\n'
    android = 'Element_Name,Element_ID\nC,android.widget.Button\n'
    empty = {"modules/modules.csv": "module_name,module_step\n"}

    def refused(elements, target):
        found = generate(_suite(elements, **empty), target)["unsupported"]
        return [f for f in found if f["uri"].endswith("elements.csv")]

    assert refused(ios, "xcuitest") == []
    assert refused(android, "uiautomator2") == []
    assert "not an XCUIElementType" in refused(android, "xcuitest")[0]["message"]
    assert "is an ios class" in refused(ios, "uiautomator2")[0]["message"]


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


# ---------------------------------------------------------------- fallbacks

FALLBACK = {
    "uiautomator2": 'Element_Name,Element_ID,Element_ID_2\nBtn,btn.png,//android.widget.Button\n',
    "xcuitest": 'Element_Name,Element_ID,Element_ID_2\nBtn,btn.png,//XCUIElementTypeButton\n',
}


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_an_unsupported_first_locator_leaves_the_supported_one_behind_it(target):
    """The image is dropped and said so; the element is not, because the path behind it is
    enough — which is what optics would have fallen back to anyway."""
    body = generate(_suite(FALLBACK[target]), target)
    codes = [f["code"] for f in body["unsupported"]]
    assert "unusable-locator" not in codes
    [dropped] = [f for f in body["unsupported"] if f["code"] == "locator-dropped"]
    assert "btn.png" in dropped["message"] and "image" in dropped["message"]


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_an_element_with_only_unsupported_locators_is_still_unusable(target):
    elements = "Element_Name,Element_ID,Element_ID_2\nBtn,btn.png,.card\n"
    codes = [f["code"] for f in generate(_suite(elements), target)["unsupported"]]
    assert "unusable-locator" in codes
    assert "locator-dropped" not in codes


def test_every_supported_locator_travels_in_the_suites_order():
    elements = "Element_Name,Element_ID,Element_ID_2\nBtn,//android.widget.Button,Go\n"
    source = generate(_suite(elements), "uiautomator2")["source"]
    assert "'Btn': ['//android.widget.Button', 'Go']," in source
    ast.parse(source)
    elements = "Element_Name,Element_ID,Element_ID_2\nBtn,//XCUIElementTypeButton,Go\n"
    source = generate(_suite(elements), "xcuitest")["source"]
    assert '"Btn": ["//XCUIElementTypeButton", "Go"],' in source


def test_a_name_on_two_rows_is_one_element_with_both_locators():
    """`read_elements` extends a name's list per row rather than keeping the first."""
    elements = "Element_Name,Element_ID\nBtn,//android.widget.Button\nBtn,Go\n"
    source = generate(_suite(elements), "uiautomator2")["source"]
    assert "'Btn': ['//android.widget.Button', 'Go']," in source


class _Selector:
    def __init__(self, device, locator):
        self.device, self.locator = device, locator

    @property
    def exists(self):
        self.device.checked.append(self.locator)
        return self.locator in self.device.present


class _Device:
    """Just enough of a uiautomator2 device for the lookup helpers to run against."""

    def __init__(self, *present):
        self.present, self.checked = set(present), []
        self.settings = {"wait_timeout": 0.5}

    def xpath(self, locator):
        return _Selector(self, locator)

    def __call__(self, description):
        return _Selector(self, description)


def _helpers():
    """The generated script's own helpers, run here rather than read."""
    sys.modules.setdefault("uiautomator2", type(sys)("uiautomator2"))
    source = generate(_suite(), "uiautomator2")["source"]
    scope: dict = {"__file__": "generated.py"}
    exec(source.split("ELEMENTS = {")[0], scope)
    return scope


def test_the_first_locator_that_matches_wins_in_the_suites_order():
    helpers = _helpers()
    device = _Device("//b", "Go")
    assert helpers["_find"](device, ["//a", "//b", "Go"]).locator == "//b"
    assert device.checked == ["//a", "//b"]


def test_a_fallback_is_polled_inside_the_one_wait_not_after_it():
    """A miss on every locator costs one timeout, not one per locator."""
    import time

    helpers = _helpers()
    started = time.time()
    assert not helpers["_wait"](_Device(), [["//a", "//b", "//c"]], 0.5)
    assert time.time() - started < 1.0
    with pytest.raises(AssertionError, match="none of"):
        helpers["_find"](_Device(), ["//a", "//b"])


def test_an_assertion_counts_an_element_with_fallbacks_as_one_entry():
    helpers = _helpers()
    assert helpers["_split"](["//a", "Go"]) == [["//a", "Go"]]
    assert helpers["_split"]("//a | Go") == ["//a", "Go"]
    assert helpers["_wait"](_Device("Go"), [["//a", "Go"]], 0.1, "all")


# ------------------------------------------------------- several locators in one cell

def test_an_assertion_splits_its_cell_on_a_bar_as_the_verifier_does():
    """`_assert_common` splits on `|`, whatever its docstring says; a comma is part of a
    locator, and `//a[@text="1,2"]` must reach the device whole."""
    helpers = _helpers()
    assert helpers["_split"]('//a[@text="1,2"]') == ['//a[@text="1,2"]']
    assert helpers["_split"]("Login|Welcome") == ["Login", "Welcome"]


def test_the_any_and_all_rules_hold_as_the_verifier_reads_them():
    helpers = _helpers()
    device = _Device("Login")
    assert helpers["_wait"](device, ["Login", "Welcome"], 0.1, "ANY")
    assert not helpers["_wait"](device, ["Login", "Welcome"], 0.1, "all")


def test_the_ios_target_splits_the_cell_and_honours_the_rule():
    """It used to take the whole cell as one locator and drop the rule."""
    modules = "module_name,module_step,param_1,param_2,param_3\nOpen,Assert Presence,Login|Welcome,10,all\n"
    found = generate(_suite(IOS, **{"modules/modules.csv": modules}), "xcuitest")
    assert 'waitForAll("Login|Welcome", Double("10") ?? 30, "all")' in found["source"]
    assert "params-dropped" not in [f["code"] for f in found["unsupported"]]


VALUE_STEPS = (
    "module_name,module_step,param_1,param_2\n"
    "Open,Enter Text,${Btn},${user}\n"
    "Open,Sleep,${five},\n"
)


EXPECTED = {
    "uiautomator2": ["_find(d, ELEMENTS['Btn']).set_text('alex')", "time.sleep(float('5'))"],
    "xcuitest": ['typeInto("Btn", "alex")', 'Thread.sleep(forTimeInterval: Double("5") ?? 0)'],
}


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_an_element_in_a_value_param_is_its_first_value(target):
    """optics loads variables as elements, so `${user}` here is a value, not a locator."""
    elements = BASE[target] + "user,alex\nuser,other\nfive,5\n"
    source = generate(_suite(elements, **{"modules/modules.csv": VALUE_STEPS}), target)["source"]
    for line in EXPECTED[target]:
        assert line in source


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_a_name_used_only_as_a_value_is_not_vetted_as_a_locator(target):
    """`.Main` reads as css and `logo.png` as an image, but as values they are only text."""
    elements = BASE[target] + "act,.Main\npic,logo.png\n"
    steps = "module_name,module_step,param_1,param_2\nOpen,Enter Text,${Btn},${act}\nOpen,Enter Text,${Btn},${pic}\n"
    body = generate(_suite(elements, **{"modules/modules.csv": steps}), target)
    assert body["source"] is not None and body["unsupported"] == []
    assert TARGETS[target].literal(".Main") in body["source"]


def test_a_refused_locator_blocks_only_the_step_that_uses_it_as_one():
    elements = ANDROID + "pic,logo.png\n"
    steps = "module_name,module_step,param_1,param_2\nOpen,Enter Text,${Btn},${pic}\nOpen,Press Element,${pic},\n"
    body = generate(_suite(elements, **{"modules/modules.csv": steps}))
    [needs] = [f for f in body["unsupported"] if f["code"] == "needs-unusable-element"]
    assert needs["step"] == "Press Element"


def test_a_value_is_the_raw_first_value_even_when_that_locator_is_refused():
    elements = ANDROID + "both,logo.png\nboth,//android.widget.Image\n"
    steps = "module_name,module_step,param_1,param_2\nOpen,Enter Text,${Btn},${both}\nOpen,Press Element,${both},\n"
    source = generate(_suite(elements, **{"modules/modules.csv": steps}))["source"]
    assert "set_text('logo.png')" in source
    assert "'both': ['//android.widget.Image']" in source


NAMED = "module_name,module_step,param_1,param_2,param_3\n"


def test_a_named_param_fills_its_own_slot_and_leaves_the_rest_to_default():
    steps = NAMED + "Open,Assert Presence,${Btn},rule=all,\n"
    source = generate(_suite(ANDROID, **{"modules/modules.csv": steps}))["source"]
    assert "assert _wait(d, _split(ELEMENTS['Btn']), 30, 'all')" in source


def test_a_named_param_can_hold_a_reference():
    steps = NAMED + "Open,Assert Presence,${Btn},timeout_str=${five},\n"
    source = generate(_suite(ANDROID + "five,5\n", **{"modules/modules.csv": steps}))["source"]
    assert "float('5')" in source


def test_a_locator_holding_an_equals_sign_stays_positional():
    """The runner treats a cell starting with `/` or `(` as positional, whatever it holds."""
    elements = 'Element_Name,Element_ID\nBtn,"//android.widget.Button[@text=\'a\']"\n'
    steps = NAMED + "Open,Press Element,//android.widget.Button[@text='a'],,\n"
    body = generate(_suite(elements, **{"modules/modules.csv": steps}))
    assert "invalid-param" not in [f["code"] for f in body["unsupported"]]


def test_a_named_param_the_keyword_lacks_or_repeats_is_refused_as_optics_would():
    steps = NAMED + "Open,Assert Presence,${Btn},nosuch=1,\nOpen,Assert Presence,${Btn},5,timeout_str=6\n"
    body = generate(_suite(ANDROID, **{"modules/modules.csv": steps}))
    messages = [f["message"] for f in body["unsupported"] if f["code"] == "invalid-param"]
    assert any("has no param nosuch" in m for m in messages)
    assert any("given timeout_str twice" in m for m in messages)


def test_a_named_locator_param_is_vetted_as_a_locator():
    steps = NAMED + "Open,Press Element,element=${pic},,\n"
    body = generate(_suite(ANDROID + "pic,logo.png\n", **{"modules/modules.csv": steps}))
    assert body["source"] is None


COLLIDING = (
    "module_name,module_step,param_1\n"
    "Click on Yes Button,Press Element,${Btn}\n"
    "Click On Yes Button!,Assert Presence,${Label}\n"
    "Main,Launch App,\n"
    "el,Close And Terminate App,\n"
    "Both,Click on Yes Button,\n"
    "Both,Click On Yes Button!,\n"
)


def _colliding(elements: str = ANDROID):
    cases = "test_case,test_step\nSign In,Both\nSign in!,Main\nSign in!,el\n"
    return _suite(elements, **{"modules/modules.csv": COLLIDING, "test_cases/test_cases.csv": cases})


def _functions(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    return {f.name: ast.get_source_segment(source, f) for f in tree.body if isinstance(f, ast.FunctionDef)}


def test_names_that_map_to_one_identifier_each_keep_their_own_function():
    source = generate(_colliding())["source"]
    names = [f.name for f in ast.parse(source).body if isinstance(f, ast.FunctionDef)]
    assert len(names) == len(set(names))
    functions = _functions(source)
    assert ".click()" in functions["click_on_yes_button"]
    assert ".click()" not in functions["click_on_yes_button_2"]
    assert "click_on_yes_button(d)\n    click_on_yes_button_2(d)" in functions["both"]
    assert {"test_sign_in", "test_sign_in_2"} <= set(functions)


def test_a_module_named_main_leaves_the_entry_point_alone():
    functions = _functions(generate(_colliding())["source"])
    assert "u2.connect" in functions["main"]
    assert "main_2(d)" in functions["test_sign_in_2"]


def test_swift_names_that_collide_get_their_own_methods():
    source = generate(_colliding(IOS), "xcuitest")["source"]
    assert "func clickOnYesButton() {" in source and "func clickOnYesButton_2() {" in source
    assert "clickOnYesButton()\n        clickOnYesButton_2()" in source
    assert "func el_2() {" in source and "el_2()" in source
    assert "func testSignIn() {" in source and "func testSignIn_2() {" in source


def test_a_test_case_name_written_in_two_files_is_two_tests():
    again = {"test_cases/more.csv": "test_case,test_step\nSign In,Open\n"}
    functions = _functions(generate(_suite(**again))["source"])
    assert {"test_sign_in", "test_sign_in_2"} <= set(functions)


def _keyword_suite(elements: str = ANDROID):
    modules = MODULES + "".join(f"{name},Launch App,,\n" for name in ("Return", "If", "class"))
    cases = CASES + "".join(f"{name},{name}\n" for name in ("Return", "If", "class"))
    return _suite(elements, **{"modules/modules.csv": modules, "test_cases/test_cases.csv": cases})


def test_a_module_named_after_a_python_keyword_still_compiles():
    compile(generate(_keyword_suite(), "uiautomator2")["source"], "generated.py", "exec")


def test_a_module_named_after_a_swift_keyword_is_not_given_the_keyword():
    source = generate(_keyword_suite(IOS), "xcuitest")["source"]
    assert "func return(" not in source and "func if(" not in source and "func class(" not in source


def _launch_suite(elements: str = ANDROID, cells: str = "com.example.other,"):
    return _suite(elements, **{"modules/modules.csv": NAMED + f"Open,Launch App,{cells},\n"})


def _launch(target: str, cells: str):
    return generate(_launch_suite(IOS if target == "xcuitest" else ANDROID, cells), target)


def test_launch_app_starts_the_package_and_activity_the_step_names():
    body = _launch("uiautomator2", "com.other,com.other.Main")
    assert "d.app_start('com.other', 'com.other.Main', stop=True)" in body["source"]
    assert "params-dropped" not in [f["code"] for f in body["unsupported"]]


def test_launch_app_falls_back_to_the_configured_app_for_what_the_step_leaves_out():
    assert "d.app_start(PACKAGE, ACTIVITY, stop=True)" in _launch("uiautomator2", ",")["source"]
    assert "d.app_start('com.other', ACTIVITY, stop=True)" in _launch("uiautomator2", "com.other,")["source"]


def test_launch_app_on_ios_launches_the_named_bundle_and_drives_it_afterwards():
    body = _launch("xcuitest", "com.other,com.other.Main")
    assert 'app = XCUIApplication(bundleIdentifier: "com.other")\n        app.launch()' in body["source"]
    assert "params-dropped" not in [f["code"] for f in body["unsupported"]]


def test_launch_app_on_ios_without_a_bundle_launches_the_default_app():
    source = _launch("xcuitest", ",")["source"]
    assert "bundleIdentifier" not in source.split("func open")[1].split("func ")[0]
    assert "app.launch()" in source
