"""Does a generated script find the element its locator named?

Nothing static answers that. The generated Swift type-checks whether or not its queries are
right, and a locator that silently matches the wrong element passes every check a compiler
can make. So this drives a real app on a real simulator or emulator and compares, per
locator, against a real xpath engine.

The comparison is the point. Locators are not hand-written: the fixture's own accessibility
tree is dumped, parsed, and every locator shape a suite uses is instantiated against it. The
expected answer comes from evaluating that xpath with lxml over the same tree, so a
disagreement is the generator being wrong rather than the fixture being odd.

    uv run --with lxml python tests/differential/harness.py ios
    uv run --with lxml python tests/differential/harness.py android

Needs Xcode and a booted simulator, or adb and a running emulator. Neither is available in
CI, which is why this is a script rather than a pytest case.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
import time
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from optics_framework_lsp.generate import generate  # noqa: E402
from optics_framework_lsp.generate.targets import TARGETS  # noqa: E402

HERE = Path(__file__).parent

# Android drives whatever is in front of it, because the comparison is against that same
# dump. Settings is launched only so a run is repeatable.
PACKAGE = "com.android.settings"

# `XCUIElementTypeButton, 0x…, {{x, y}, {w, h}}, identifier: 'a', label: 'b'`
_IOS_LINE = re.compile(r"^(\s*)→?\s*(\w[\w ]*?)(?: \(Main\))?, 0x[0-9a-f]+,(.*)$")


def ios_tree(dump: str) -> etree._Element:
    """XCTest's `debugDescription` as the XML a page source would have held."""
    body = dump.split("Element subtree:")[1].split("Path to element:")[0]
    root, stack = None, []
    for line in body.splitlines():
        found = _IOS_LINE.match(line)
        if not found:
            continue
        indent, kind, rest = len(found.group(1)), found.group(2).strip(), found.group(3)
        attributes = {}
        for key in ("identifier", "label", "value"):
            at = re.search(rf"{key}: '([^']*)'", rest) or re.search(rf"{key}: ([^,]+)$", rest)
            if at:
                attributes[key] = at.group(1).strip()
        node = etree.Element(f"XCUIElementType{kind}", **attributes)
        # WebDriverAgent reports `name` as the identifier, falling back to the label, and
        # the element type as an attribute as well as the tag.
        node.set("name", attributes.get("identifier") or attributes.get("label", ""))
        node.set("type", f"XCUIElementType{kind}")
        node.set("elementType", f"XCUIElementType{kind}")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].append(node)
        else:
            root = node
        stack.append((indent, node))
    return root


def android_tree(dump: str) -> etree._Element:
    """uiautomator's hierarchy is already XML; only the node names need lifting out of
    `class`, which is how uiautomator2's own xpath support reads it."""
    source = etree.fromstring(dump.encode())

    def convert(node):
        made = etree.Element(node.get("class") or "node", **dict(node.attrib))
        for child in node:
            made.append(convert(child))
        return made

    return convert(source[0]) if len(source) else convert(source)


def named(node) -> str:
    """How a test says which element it landed on."""
    for key in ("identifier", "resource-id", "content-desc", "label", "text", "name"):
        if node.get(key):
            return node.get(key)
    return ""


def locators(root, attributes: tuple[str, ...]) -> list[str]:
    """Every locator shape a suite uses, instantiated against this tree.

    `attributes` differs by platform and is not cosmetic: `name` is WebDriverAgent's
    invention and Android has no such attribute, so a locator naming it would be testing the
    harness rather than the generator.
    """
    out = []

    def joined(steps) -> str:
        path = f"//{steps[0][0]}"
        for tag, index in steps[1:]:
            path += f"/{tag}" + (f"[{index}]" if index else "")
        return path

    def path_of(node):
        steps, cursor = [], node
        while cursor is not None:
            parent = cursor.getparent()
            if parent is None:
                steps.append((cursor.tag, None))
                break
            same = [c for c in parent if c.tag == cursor.tag]
            steps.append((cursor.tag, same.index(cursor) + 1 if len(same) > 1 else None))
            cursor = parent
        return list(reversed(steps))

    # The tree keeps every node, because the script resolves against the same one. Locators
    # are not taken from the status bar: it holds a clock, whose text differs between the
    # dump the expected answers came from and the dump the script reads, and that is a
    # moving screen rather than a disagreement.
    for node in (n for n in root.iter() if named(n) and n.get("package") != "com.android.systemui"):
        for key in attributes:
            if node.get(key):
                out.append(f'//{node.tag}[@{key}="{node.get(key)}"]')
        steps = path_of(node)
        out.append(joined(steps))
        out += [joined(steps[-keep:]) for keep in (2, 3, 4) if len(steps) > keep]
    for tag in sorted({n.tag for n in root.iter() if n.get("package") != "com.android.systemui"}):
        out += [f"//{tag}", f"//{tag}[1]"]
    return sorted(set(out))


# `name` is WebDriverAgent's invention and Android has none, so the two differ. Android
# keeps to `resource-id`: text and content descriptions move while the screen is read.
ATTRIBUTES = {
    "xcuitest": ("name", "identifier", "label", "value", "type"),
    "uiautomator2": ("resource-id",),
}


def cases(root, target: str) -> list[tuple[str, str]]:
    """Locator and the element an xpath engine says it names, for the ones this target
    carries and an xpath engine can answer."""
    tree, vet = etree.ElementTree(root), TARGETS[target].vet_locator
    found = []
    for locator in locators(root, ATTRIBUTES[target]):
        if vet(locator):
            continue
        try:
            hits = tree.xpath(locator)
        except etree.XPathEvalError:
            continue
        if hits and named(hits[0]):
            found.append((locator, named(hits[0])))
    return found


def write_suite(into: Path, found: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The locators as a suite on disk, and that suite as `generate` takes it."""
    into.mkdir(parents=True, exist_ok=True)
    (into / "test_data").mkdir(exist_ok=True)
    (into / "modules").mkdir(exist_ok=True)
    (into / "test_cases").mkdir(exist_ok=True)
    with open(into / "test_data" / "elements.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Element_Name", "Element_ID"])
        writer.writerows([f"e{i}", locator] for i, (locator, _) in enumerate(found))
    (into / "modules" / "modules.csv").write_text("module_name,module_step\nNoop,Launch App\n")
    (into / "test_cases" / "cases.csv").write_text("test_case,test_step\nSmoke,Noop\n")
    return [(str(f.relative_to(into)), f.read_text()) for f in sorted(into.rglob("*.csv"))]


def run(command: list[str], **kwargs) -> str:
    done = subprocess.run(command, capture_output=True, text=True, **kwargs)
    return done.stdout + done.stderr


def report(found: list, mismatches: list[str]) -> int:
    print(f"\n{len(found) - len(mismatches)} of {len(found)} locators agree")
    for line in mismatches:
        print(f"  - {line}")
    return 1 if mismatches else 0


def ios(simulator: str) -> int:
    """Drive the checked-in fixture app on a simulator and compare every shape."""
    project = HERE / "ios" / "Fixture.xcodeproj"
    destination = f"platform=iOS Simulator,name={simulator}"

    def xcodebuild(*args: str) -> str:
        return run(["xcodebuild", *args, "-project", str(project), "-scheme", "Fixture",
                    "-destination", destination])

    probe = HERE / "ios" / "UITests" / "Probe.swift"
    probe.parent.mkdir(parents=True, exist_ok=True)
    (probe.parent / "Generated.swift").write_text("import XCTest\n")
    probe.write_text(_IOS_PROBE)
    dump = xcodebuild("test", "-only-testing:FixtureAppUITests/Probe")
    if "===TREE-START===" not in dump:
        print(dump[-3000:])
        return 1
    root = ios_tree(dump.split("===TREE-START===")[1].split("===TREE-END===")[0])

    found = cases(root, "xcuitest")
    source = generate(write_suite(HERE / "build" / "suite", found), "xcuitest")["source"]
    (probe.parent / "Generated.swift").write_text(
        source.replace("final class GeneratedUITests", "class GeneratedUITests"))
    probe.write_text(_IOS_VERIFY.replace("<checks>", "\n".join(
        f'        check("e{i}", {expected!r}, {locator!r})'.replace("'", '"')
        for i, (locator, expected) in enumerate(found))))

    output = xcodebuild("test", "-only-testing:FixtureAppUITests/Verify")
    mismatches = [line.strip()[2:] for line in output.splitlines() if line.strip().startswith("- //")]
    return report(found, mismatches)


def android() -> int:
    """A smoke run, not a differential -- and the difference is the point.

    The xcuitest target translates nothing and resolves locators itself, so on iOS there is a
    real second implementation to disagree with an xpath engine. uiautomator2 has xpath
    natively: the generated script hands the locator to `d.xpath()`, which dumps the
    hierarchy and evaluates it with lxml. Comparing that against lxml would be comparing lxml
    with itself.

    So what is worth checking here is that a generated script runs at all -- imports,
    connects, and finds what its locators name on a live device.
    """
    import importlib.util
    import uiautomator2

    device = uiautomator2.connect()
    # An emulator left alone sleeps, and a sleeping one has nothing to read.
    run(["adb", "shell", "input", "keyevent", "KEYCODE_WAKEUP"])
    # Home first. An app left in the foreground across runs can reach a state where the
    # window is focused and drawn and yet no node tree is reported for it -- `adb exec-out
    # uiautomator dump` shows the same nothing, so it is the device and not this. Leaving
    # the app clears it, where `force-stop` does not; `force-stop` also races a following
    # `am start`, delivering the intent to an app being killed.
    run(["adb", "shell", "input", "keyevent", "KEYCODE_HOME"])
    run(["adb", "shell", "am", "start", "-a", "android.settings.SETTINGS"])

    # Wait for a screen that is both drawn and still. Either test alone is passed by a
    # screen that is no use: the one being left behind is perfectly stable, and the app's
    # first frame reports itself foreground before it has drawn anything.
    previous, root, found = None, None, []
    for attempt in range(40):
        root = android_tree(device.dump_hierarchy())
        settled = etree.tostring(root)
        if settled == previous:
            found = cases(root, "uiautomator2")
            if found:
                break
            # Stable and empty is the window having gone away -- connecting to the device
            # can take it with it. Ask for the app again rather than waiting out the clock.
            run(["adb", "shell", "am", "start", "-a", "android.settings.SETTINGS"])
        previous = settled
        time.sleep(0.5)

    if not found:
        packages = {n.get("package") for n in root.iter()} if root is not None else set()
        print(f"no locators to check after {attempt + 1} dumps; last screen held "
              f"{len(list(root.iter())) if root is not None else 0} nodes from {packages or '{}'}")
        return 1

    script = HERE / "build" / "generated.py"
    script.write_text(generate(write_suite(HERE / "build" / "suite", found), "uiautomator2")["source"])

    # The generated `_find` is the thing under test, so it is imported rather than restated.
    spec = importlib.util.spec_from_file_location("generated", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    mismatches = []
    for locator, expected in found:
        try:
            element = module._find(device, locator)
            info = element.info if hasattr(element, "info") else element.get().info
            got = info.get("resourceName") or info.get("contentDescription") or info.get("text") or ""
        except Exception as error:  # a miss is an answer, and it is the wrong one
            got = f"NO MATCH ({type(error).__name__})"
        if (got or "").split("/")[-1] != expected.split("/")[-1]:
            mismatches.append(f"{locator}\n     dump said:   {expected}\n     script gave: {got}")
    return report(found, mismatches)


_IOS_PROBE = '''import XCTest

final class Probe: XCTestCase {
    func testDump() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["Alpha"].waitForExistence(timeout: 30))
        print("===TREE-START===")
        print(app.debugDescription)
        print("===TREE-END===")
    }
}
'''

_IOS_VERIFY = '''import XCTest

/// Each generated lookup against the live app, checked against what an xpath engine said the
/// same locator names in the same tree.
final class Verify: GeneratedUITests {
    var failures: [String] = []

    func check(_ name: String, _ expected: String, _ locator: String) {
        let element = el(name)
        guard element.exists else {
            failures.append("- \\(locator)\\n     xpath said: \\(expected)\\n     query gave: NO MATCH")
            return
        }
        let got = element.identifier.isEmpty ? element.label : element.identifier
        if got != expected {
            failures.append("- \\(locator)\\n     xpath said: \\(expected)\\n     query gave: \\(got)")
        }
    }

    func testEveryShape() {
        app.launch()
        XCTAssertTrue(app.buttons["Alpha"].waitForExistence(timeout: 30))
<checks>
        failures.forEach { print($0) }
        XCTAssertEqual(failures.count, 0)
    }
}
'''


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ios"
    if target == "ios":
        raise SystemExit(ios(sys.argv[2] if len(sys.argv) > 2 else "iPhone 17 Pro"))
    if target == "android":
        raise SystemExit(android())
    raise SystemExit(f"unknown target {target}; try ios or android")
