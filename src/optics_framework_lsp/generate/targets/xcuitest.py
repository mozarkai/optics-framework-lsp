# What each keyword becomes in an XCUITest case, and why the rest cannot.
#
# Two things make this target unlike uiautomator2, and both shape what is below.
#
# XCTest has no xpath, and no query is a translation of one. Two reasons, both measured
# against a live app: an xpath index counts within each parent while a query flattens every
# match into one list, and the tree a query walks is not the tree a page source dumps -- a
# label inside a button is in the dump and is not reached the same way by a descendants
# query. So a locator with a path in it is not translated at all. It is carried into the
# generated file as text and evaluated there, against a snapshot of the hierarchy, and the
# match is walked back to a live element by its chain of child indexes. That correspondence
# is the one thing this rests on, and it holds: a snapshot's children and
# `children(matching: .any)` enumerate the same elements in the same order.
#
# And the code runs on the device, compiled. There is no host to defer to and no runtime
# evaluation, which is why `evaluate` and `execute script` are refused here for a stronger
# reason than on Android: Swift cannot do it at all.

from __future__ import annotations

import re

NAME = "xcuitest"
EXTENSION = ".swift"

_IMAGE = (".png", ".jpg", ".jpeg", ".bmp")

# What a predicate may key on: an element's own attributes, plus `name`, which is
# WebDriverAgent's and is the identifier or, failing that, the label. Anything else is
# refused rather than answered -- an unknown key raises inside NSPredicate, and a made-up
# answer for `visible` would quietly make `[@visible="false"]` match everything.
_ATTRIBUTES = ("name", "identifier", "label", "value", "type", "elementType")

# Every XCUIElement.ElementType and its raw value, read off XCUIElementTypes.h. The
# evaluator needs the number because Swift has no string initialiser for the enum.
_TYPE_IDS = {
    "Any": 0, "Other": 1, "Application": 2, "Group": 3, "Window": 4, "Sheet": 5, "Drawer": 6,
    "Alert": 7, "Dialog": 8, "Button": 9, "RadioButton": 10, "RadioGroup": 11, "CheckBox": 12,
    "DisclosureTriangle": 13, "PopUpButton": 14, "ComboBox": 15, "MenuButton": 16,
    "ToolbarButton": 17, "Popover": 18, "Keyboard": 19, "Key": 20, "NavigationBar": 21,
    "TabBar": 22, "TabGroup": 23, "Toolbar": 24, "StatusBar": 25, "Table": 26, "TableRow": 27,
    "TableColumn": 28, "Outline": 29, "OutlineRow": 30, "Browser": 31, "CollectionView": 32,
    "Slider": 33, "PageIndicator": 34, "ProgressIndicator": 35, "ActivityIndicator": 36,
    "SegmentedControl": 37, "Picker": 38, "PickerWheel": 39, "Switch": 40, "Toggle": 41, "Link":
    42, "Image": 43, "Icon": 44, "SearchField": 45, "ScrollView": 46, "ScrollBar": 47,
    "StaticText": 48, "TextField": 49, "SecureTextField": 50, "DatePicker": 51, "TextView": 52,
    "Menu": 53, "MenuItem": 54, "MenuBar": 55, "MenuBarItem": 56, "Map": 57, "WebView": 58,
    "IncrementArrow": 59, "DecrementArrow": 60, "Timeline": 61, "RatingIndicator": 62,
    "ValueIndicator": 63, "SplitGroup": 64, "Splitter": 65, "RelevanceIndicator": 66,
    "ColorWell": 67, "HelpTag": 68, "Matte": 69, "DockItem": 70, "Ruler": 71, "RulerMarker": 72,
    "Grid": 73, "LevelIndicator": 74, "Cell": 75, "LayoutArea": 76, "LayoutItem": 77, "Handle":
    78, "Stepper": 79, "Tab": 80, "TouchBar": 81, "StatusItem": 82
}


def _swift_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def func_name(text: str) -> str:
    """A block name as a swift identifier, lowerCamelCase."""
    parts = [part for part in re.split(r"[^0-9a-zA-Z]+", text.strip()) if part]
    if not parts:
        return "unnamed"
    head = parts[0].lower()
    name = head + "".join(part[:1].upper() + part[1:] for part in parts[1:])
    return name if not name[0].isdigit() else f"m{name}"


def literal(value: str) -> str:
    return _swift_string(value)


def element_ref(name: str) -> str:
    """Element params are passed by name and resolved at run time. Passing the name rather
    than an element is also what lets a param that is a variable or a bare literal reach the
    same lookup, and what lets a wait re-resolve instead of holding a handle on nothing."""
    return _swift_string(name)


def var_ref(name: str) -> str:
    return f'(vars[{_swift_string(name)}] ?? "")'


_STEP = re.compile(r"(//|/)(\*|[A-Za-z][\w.]*)((?:\[[^\]]*\])*)")
_ATTRIBUTE = re.compile(r"@([\w-]+)")


def _reads(locator: str) -> str | None:
    """Why the on-device evaluator would not read this xpath, or None if it would.

    It does not translate the path -- that happens on the device, against the real tree --
    but it does check the two things that can be known here: that the shape parses, and that
    every step names a type iOS has. Without the second, an android locator in an ios suite
    is carried through and quietly matches nothing on every run.
    """
    text = locator.strip()
    if text.startswith("(") and text.endswith("]"):
        text = text[1 : text.rindex(")")]
    at = 0
    while at < len(text):
        step = _STEP.match(text, at)
        if not step:
            return "is not an xpath shape the evaluator reads"
        name = step.group(2)
        if name != "*" and name.removeprefix("XCUIElementType") not in _TYPE_IDS:
            return f"names {name}, which is not an XCUIElementType"
        for attribute in _ATTRIBUTE.findall(step.group(3)):
            if attribute not in _ATTRIBUTES:
                return f"keys on @{attribute}, which an element does not carry"
        at = step.end()
    return None


def vet_locator(locator: str) -> str | None:
    """An image template has no native form. An xpath is carried through rather than
    translated, so the only question here is whether the device could read it."""
    if locator.lower().endswith(_IMAGE):
        return "is an image template; no native query can match it"
    if locator.startswith(("//", "(")):
        return _reads(locator)
    return None


def _one(call: str):
    return lambda p: [call.format(*p)]


def _num(p: list[str], i: int, fallback: int) -> str:
    """An optional numeric param, or the fallback when the suite left the cell empty."""
    return f"Double({p[i]}) ?? {fallback}" if len(p) > i and p[i] else str(fallback)


EMIT: dict[str, tuple[int, object]] = {
    # lifecycle
    "launch app": (0, _one("app.launch()")),
    "launch other app": (1, _one("XCUIApplication(bundleIdentifier: {0}).activate()")),
    "close and terminate app": (0, _one("app.terminate()")),
    "force terminate app": (1, _one("app.terminate()")),
    "quit": (0, _one("app.terminate()")),
    # pressing
    "press element": (1, _one("el({0}).tap()")),
    "press element with index": (2, _one("elAt({0}, {1}).tap()")),
    "detect and press": (2, lambda p: [f"pressIfPresent({p[0]}, {_num(p, 1, 30)})"]),
    "press by coordinates": (2, _one("tapAt({0}, {1})")),
    "press by percentage": (2, _one("tapPercent({0}, {1})")),
    "press checkbox": (1, _one("el({0}).tap()")),
    "press radio button": (1, _one("el({0}).tap()")),
    # text
    "enter text": (2, _one("typeInto({0}, {1})")),
    "enter number": (2, _one("typeInto({0}, {1})")),
    "enter text direct": (1, _one("app.typeText({0})")),
    "enter text using keyboard": (1, _one("app.typeText({0})")),
    "clear element text": (1, _one("clearText({0})")),
    "get text": (1, _one('vars["last_text"] = el({0}).label')),
    # assertions
    "assert presence": (2, lambda p: [f"XCTAssertTrue(waitFor({p[0]}, {_num(p, 1, 30)}), {p[0]})"]),
    "assert visibility": (2, lambda p: [f"XCTAssertTrue(waitHittable({p[0]}, {_num(p, 1, 30)}), {p[0]})"]),
    "validate element": (2, lambda p: [f"soft.append(waitFor({p[0]}, {_num(p, 1, 30)}))"]),
    "validate screen": (2, lambda p: [f"soft.append(waitFor({p[0]}, {_num(p, 1, 30)}))"]),
    "is element": (3, lambda p: [f"_ = isElement({p[0]}, {p[1]}, {_num(p, 2, 30)})"]),
    "assert equality": (2, _one("XCTAssertEqual({0}, {1})")),
    # movement
    "scroll": (1, _one("swipeScreen({0})")),
    "scroll from element": (3, _one("swipeFrom({0}, {1})")),
    "scroll until element appears": (3, _one("swipeUntil({0}, {1}, {2})")),
    "swipe until element appears": (3, _one("swipeUntil({0}, {1}, {2})")),
    "swipe from element": (3, _one("swipeFrom({0}, {1})")),
    "swipe": (4, lambda p: [f"swipeAt({p[0]}, {p[1]}, {p[2]}, {_num(p, 3, 200)})"]),
    "swipe by percentage": (4, lambda p: [f"swipePercent({p[0]}, {p[1]}, {p[2]}, {_num(p, 3, 200)})"]),
    # the one keyword iOS does better than Android, its name notwithstanding
    "swipe seekbar to right android": (1, _one("el({0}).adjust(toNormalizedSliderPosition: 1.0)")),
    "select dropdown option": (3, _one("el({0}).adjust(toPickerWheelValue: {1})")),
    # everything else
    "sleep": (1, _one("Thread.sleep(forTimeInterval: Double({0}) ?? 0)")),
    "capture screenshot": (0, _one("attachScreenshot()")),
    "capture pagesource": (0, _one("attachPageSource()")),
    "execute module": (1, _one("{0}()")),
}

UNSUPPORTED: dict[str, str] = {
    # no ios form at all
    "press keycode": "android keycodes have no ios concept; XCUIDevice presses only .home and the volume buttons",
    "get app version": "a ui test runs in its own process and cannot read the app's bundle; resolve it in ci instead",
    # compiled, on the device — these are harder here than on android
    "evaluate": "swift has no runtime expression evaluation",
    "execute script": "swift has no runtime code evaluation",
    "invoke api": "needs an http runtime; on ios the request would also leave from the device, not the host",
    "read data": "needs optics' csv query grammar, and the file bundled as a test resource",
    # the same gaps as every target
    "condition": "branch targets are not in the parse payload; expose them and this emits an if",
    "run loop": "loop target and count are not in the parse payload",
    "date evaluate": "parameter semantics are not exposed by parse",
    "get screen elements": "returns data a generated test has nowhere to put",
    "get interactive elements": "returns data a generated test has nowhere to put",
    "start appium session": "XCUITest has no driver session; XCUIApplication() is the whole setup",
    "initialise setup": "setUpWithError already does this",
    "get driver session id": "XCUITest has no session id",
}


_PRELUDE = '''\
import XCTest

final class GeneratedUITests: XCTestCase {
    var app: XCUIApplication!
    var vars: [String: String] = [:]
    var soft: [Bool] = []

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
    }

    override func tearDownWithError() throws {
        if !soft.isEmpty && soft.contains(false) {
            let passed = soft.filter { $0 }.count
            print("soft checks: \\(passed) of \\(soft.count) passed")
        }
    }
'''

_RESOLVER = '''    // MARK: locators

    /// One node of the accessibility hierarchy, captured so an xpath can be evaluated
    /// against the tree it was written against rather than approximated by a query.
    ///
    /// `path` is the node's position as a chain of child indexes, which is how a match is
    /// walked back to a live element: a snapshot's children and `children(matching: .any)`
    /// enumerate the same elements in the same order.
    /// NSObject so NSPredicate can read the attributes by name. `name` is
    /// WebDriverAgent's and is what the suites were written against: the identifier when
    /// there is one, the label otherwise.
    final class Node: NSObject {
        @objc let identifier: String, label: String, value: String, name: String
        @objc let type: String          // `XCUIElementTypeButton`, for a predicate to key on
        let typeId: UInt                // the same thing as the enum, for a node test
        let path: [Int], order: Int
        var children: [Node] = []
        init(typeId: UInt, type: String = "", identifier: String = "", label: String = "",
             value: String = "", path: [Int] = [], order: Int = 0) {
            self.typeId = typeId
            self.type = type
            self.identifier = identifier
            self.label = label
            self.value = value
            self.name = identifier.isEmpty ? label : identifier
            self.path = path
            self.order = order
        }
    }

    struct Step {
        let descendant: Bool
        let type: UInt?          // nil is `*`
        let predicates: [String]
    }

    /// Taken fresh for every lookup. Reusing one across steps would be faster -- it is the
    /// whole cost, since parsing and evaluating against it are free -- but how long a tree
    /// stays true is a property of the app under test, not something to guess at here.
    func snapshotTree() -> Node? {
        guard let root = try? app.snapshot() else { return nil }
        var counter = 0
        func build(_ s: XCUIElementSnapshot, _ path: [Int]) -> Node {
            let node = Node(typeId: s.elementType.rawValue,
                            type: TYPE_NAMES[s.elementType.rawValue] ?? "",
                            identifier: s.identifier, label: s.label,
                            value: (s.value as? String) ?? "", path: path, order: counter)
            counter += 1
            node.children = s.children.enumerated().map { build($1, path + [$0]) }
            return node
        }
        return build(root, [])
    }

    // ---------------------------------------------------------------- parsing

    /// An xpath as steps. Returns nil for a shape this does not read, which is reported as a
    /// miss rather than silently matching something else.
    func parseXPath(_ raw: String) -> (steps: [Step], outerIndex: Int?)? {
        var text = raw.trimmingCharacters(in: .whitespaces)
        var outer: Int? = nil
        // `(//a/b)[2]` groups the whole path before indexing it, unlike `//a/b[2]`.
        if text.hasPrefix("("), let close = text.lastIndex(of: ")") {
            let after = String(text[text.index(after: close)...])
            if after.hasPrefix("["), after.hasSuffix("]") {
                outer = Int(after.dropFirst().dropLast())
                if outer == nil { return nil }
            } else if !after.isEmpty {
                return nil
            }
            text = String(text[text.index(after: text.startIndex)..<close])
        }

        var steps: [Step] = []
        var chars = Array(text), at = 0
        while at < chars.count {
            guard chars[at] == "/" else { return nil }
            var descendant = false
            at += 1
            if at < chars.count && chars[at] == "/" { descendant = true; at += 1 }

            var name = ""
            while at < chars.count && (chars[at].isLetter || chars[at].isNumber || chars[at] == "*") {
                name.append(chars[at]); at += 1
            }
            if name.isEmpty { return nil }

            var predicates: [String] = []
            while at < chars.count && chars[at] == "[" {
                var depth = 0, body = ""
                while at < chars.count {
                    if chars[at] == "[" { depth += 1; if depth == 1 { at += 1; continue } }
                    if chars[at] == "]" { depth -= 1; if depth == 0 { at += 1; break } }
                    body.append(chars[at]); at += 1
                }
                if depth != 0 { return nil }
                predicates.append(body.trimmingCharacters(in: .whitespaces))
            }

            if name == "*" {
                steps.append(Step(descendant: descendant, type: nil, predicates: predicates))
            } else {
                guard let id = TYPE_IDS[name] else { return nil }
                steps.append(Step(descendant: descendant, type: id, predicates: predicates))
            }
        }
        return steps.isEmpty ? nil : (steps, outer)
    }

    // ------------------------------------------------------------- evaluation

    func descendants(of node: Node) -> [Node] {
        var out: [Node] = []
        for child in node.children { out.append(child); out += descendants(of: child) }
        return out
    }

    /// One step against one context node.
    ///
    /// `a//b[2]` is `a/descendant-or-self::node()/child::b[2]`: every node under `a` is a
    /// parent in turn, and the index counts within *that* parent's children. Flattening the
    /// descendants first and indexing the result is the thing a query does and xpath does
    /// not, and it is what made `//Other/Other[2]` and `//Button[last()]` pick wrong.
    func apply(_ step: Step, to context: Node) -> [Node] {
        let parents = step.descendant ? [context] + descendants(of: context) : [context]
        var out: [Node] = []
        for parent in parents {
            var candidates = parent.children
            if let wanted = step.type { candidates = candidates.filter { $0.typeId == wanted } }
            for predicate in step.predicates {
                if predicate == "last()" {
                    candidates = candidates.isEmpty ? [] : [candidates[candidates.count - 1]]
                } else if let n = Int(predicate) {
                    candidates = (n >= 1 && n <= candidates.count) ? [candidates[n - 1]] : []
                } else if let test = self.predicate(predicate) {
                    candidates = candidates.filter { test.evaluate(with: $0) }
                } else {
                    return []
                }
            }
            out += candidates
        }
        return out
    }

    func evaluate(_ raw: String) -> [Node] {
        guard let parsed = parseXPath(raw), let root = snapshotTree() else { return [] }
        // The document node, whose only child is the application -- so a leading `//` reaches
        // the application itself, and every step is the same rule with no special case.
        let document = Node(typeId: 0)
        document.children = [root]
        var context = [document]
        for step in parsed.steps {
            var next: [Node] = []
            for node in context { next += apply(step, to: node) }
            var seen = Set<Int>()
            context = next.sorted { $0.order < $1.order }.filter { seen.insert($0.order).inserted }
            if context.isEmpty { return [] }
        }
        if let n = parsed.outerIndex {
            return (n >= 1 && n <= context.count) ? [context[n - 1]] : []
        }
        return context
    }

    // ------------------------------------------------------------- predicates

    /// An xpath predicate as an NSPredicate, which is the same test written the way
    /// Foundation already evaluates it -- so parentheses, precedence and quoting are its
    /// problem rather than this file's. Only the spelling differs:
    ///
    ///     @a="x" and contains(@b, 'y')   ->   a == %@ AND b CONTAINS %@
    ///
    /// Values leave as arguments rather than staying in the format, so one holding a quote
    /// cannot reshape the expression.
    func predicate(_ raw: String) -> NSPredicate? {
        var format = "", args: [Any] = []
        var at = raw.startIndex
        while at < raw.endIndex {
            let c = raw[at]
            if c == "\\"" || c == "'" {
                let from = raw.index(after: at)
                guard let close = raw[from...].firstIndex(of: c) else { return nil }
                args.append(String(raw[from..<close]))
                format += "%@"
                at = raw.index(after: close)
            } else {
                format.append(c)
                at = raw.index(after: at)
            }
        }
        // An attribute Node does not carry would raise on evaluation rather than return
        // false, so it stops here instead. The `@` of a `%@` placeholder is not one: it is
        // followed by no name, which is what tells the two apart.
        var rest = format[...]
        while let at = rest.firstIndex(of: "@") {
            rest = rest[rest.index(after: at)...]
            let key = String(rest.prefix { $0.isLetter })
            if !key.isEmpty, !ATTRIBUTES.contains(key) { return nil }
        }
        for (fn, op) in [("contains", "CONTAINS"), ("starts-with", "BEGINSWITH"),
                         ("ends-with", "ENDSWITH")] {
            format = format.replacingOccurrences(
                of: "\\(fn)\\\\(\\\\s*@?([A-Za-z]+)\\\\s*,\\\\s*%@\\\\s*\\\\)",
                with: "$1 \\(op) %@", options: .regularExpression)
        }
        format = format
            .replacingOccurrences(of: "@(?=[A-Za-z])", with: "", options: .regularExpression)
            .replacingOccurrences(of: "elementType", with: "type")
            .replacingOccurrences(of: "!=", with: "<NE>")
            .replacingOccurrences(of: "=", with: "==")
            .replacingOccurrences(of: "<NE>", with: "!=")
            .replacingOccurrences(of: " and ", with: " AND ")
            .replacingOccurrences(of: " or ", with: " OR ")
        return NSPredicate(format: format, argumentArray: args)
    }

    // ---------------------------------------------------------------- lookup

    func element(at path: [Int]) -> XCUIElement {
        var element: XCUIElement = app
        for index in path { element = element.children(matching: .any).element(boundBy: index) }
        return element
    }

    /// A query that matches nothing, so a miss reads as "does not exist" and says which
    /// locator missed rather than trapping.
    func noMatch(_ locator: String) -> XCUIElement {
        return app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", "no match for \\(locator)")).firstMatch
    }

    /// The nth element a locator names. An xpath is evaluated against a fresh snapshot; a
    /// plain string is screen text or an accessibility id, which needs no tree walk.
    func resolve(_ name: String, _ index: Int = 0) -> XCUIElement {
        let locator = ELEMENTS[name] ?? name
        if locator.hasPrefix("//") || locator.hasPrefix("(") {
            let hits = evaluate(locator)
            guard index < hits.count else { return noMatch(locator) }
            return element(at: hits[index].path)
        }
        let query = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ OR label == %@ OR value == %@", locator, locator, locator))
        return index == 0 ? query.firstMatch : query.element(boundBy: index)
    }

    func el(_ name: String) -> XCUIElement { return resolve(name) }

    /// Whether a locator matches anything, answered from the tree. An assertion about
    /// presence does not need an XCUIElement, and materialising one costs another query.
    func matches(_ name: String) -> Bool {
        let locator = ELEMENTS[name] ?? name
        if locator.hasPrefix("//") || locator.hasPrefix("(") { return !evaluate(locator).isEmpty }
        return el(name).exists
    }

    func elAt(_ name: String, _ index: String) -> XCUIElement {
        return resolve(name, Int(index) ?? 0)
    }

    /// Waiting re-resolves: the element a locator names does not exist yet, so an XCUIElement
    /// taken once before the wait would be a handle on nothing.
    func waitUntil(_ name: String, _ timeout: Double, _ ready: (String) -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if ready(name) { return true }
            Thread.sleep(forTimeInterval: 0.3)
        } while Date() < deadline
        return false
    }
'''

_HELPERS = '''
    // MARK: waiting

    /// Present is in the tree. Each of these re-resolves through `el`, because the point of
    /// a wait is that the element is not there yet.
    func waitFor(_ name: String, _ timeout: Double) -> Bool {
        return waitUntil(name, timeout) { self.matches($0) }
    }

    /// Visible is on screen, which XCTest reports as hittable.
    func waitHittable(_ name: String, _ timeout: Double) -> Bool {
        // Hittable is a property of the element, so this one does have to resolve.
        return waitUntil(name, timeout) { let e = self.el($0); return e.exists && e.isHittable }
    }

    /// Tolerant press: a miss is not a failure, as `detect_and_press` treats it.
    func pressIfPresent(_ name: String, _ timeout: Double) {
        if waitFor(name, timeout) { el(name).tap() }
    }

    func isElement(_ name: String, _ state: String, _ timeout: Double) -> Bool {
        switch state.lowercased() {
        case "visible", "present", "exists":
            return waitFor(name, timeout)
        case "enabled":
            return waitUntil(name, timeout) { let e = self.el($0); return e.exists && e.isEnabled }
        case "hittable":
            return waitHittable(name, timeout)
        case "invisible", "absent", "gone":
            return !waitFor(name, timeout)
        default:
            // A state the suite named that no platform has: a bug in the suite, not a miss.
            fatalError("unknown element state: \\(state)")
        }
    }

    // MARK: acting

    func typeInto(_ name: String, _ text: String) {
        let element = el(name)
        element.tap()
        element.typeText(text)
    }

    /// iOS has no clear primitive; counting the value and deleting it is the usual way.
    func clearText(_ name: String) {
        let element = el(name)
        let count = (element.value as? String)?.count ?? 0
        element.tap()
        element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: count))
    }

    func tapAt(_ x: String, _ y: String) {
        let dx = Double(x) ?? 0
        let dy = Double(y) ?? 0
        app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
           .withOffset(CGVector(dx: dx, dy: dy)).tap()
    }

    func tapPercent(_ x: String, _ y: String) {
        let dx = (Double(x) ?? 0) / 100
        let dy = (Double(y) ?? 0) / 100
        app.coordinate(withNormalizedOffset: CGVector(dx: dx, dy: dy)).tap()
    }

    func swipeScreen(_ direction: String) {
        switch direction.lowercased() {
        case "up": app.swipeUp()
        case "down": app.swipeDown()
        case "left": app.swipeLeft()
        default: app.swipeRight()
        }
    }

    func swipeFrom(_ name: String, _ direction: String) {
        let element = el(name)
        switch direction.lowercased() {
        case "up": element.swipeUp()
        case "down": element.swipeDown()
        case "left": element.swipeLeft()
        default: element.swipeRight()
        }
    }

    /// A swipe that starts where the suite said, rather than in the middle of the screen.
    /// `swipeScreen` is the whole-screen gesture and is a different thing: these drag from a
    /// point, which is what a suite naming coordinates is asking for.
    func swipeAt(_ x: String, _ y: String, _ direction: String, _ length: Double) {
        let origin = app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            .withOffset(CGVector(dx: Double(x) ?? 0, dy: Double(y) ?? 0))
        drag(origin, direction, length)
    }

    func swipePercent(_ x: String, _ y: String, _ direction: String, _ length: Double) {
        let origin = app.coordinate(withNormalizedOffset: CGVector(
            dx: (Double(x) ?? 0) / 100, dy: (Double(y) ?? 0) / 100))
        drag(origin, direction, length)
    }

    func drag(_ origin: XCUICoordinate, _ direction: String, _ length: Double) {
        let step: CGVector
        switch direction.lowercased() {
        case "up": step = CGVector(dx: 0, dy: -length)
        case "down": step = CGVector(dx: 0, dy: length)
        case "left": step = CGVector(dx: -length, dy: 0)
        default: step = CGVector(dx: length, dy: 0)
        }
        origin.press(forDuration: 0.1, thenDragTo: origin.withOffset(step))
    }

    func swipeUntil(_ name: String, _ direction: String, _ timeout: String) {
        let deadline = Date().addingTimeInterval(Double(timeout) ?? 30)
        while !matches(name) {
            XCTAssertLessThan(Date(), deadline, "\\(name) never appeared")
            swipeScreen(direction)
        }
    }

    func attachScreenshot() {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.lifetime = .keepAlways
        add(shot)
    }

    /// debugDescription carries every element's role, label, identifier and frame -- not a
    /// parseable tree like Android's, but the same information.
    func attachPageSource() {
        let dump = XCTAttachment(string: app.debugDescription)
        dump.lifetime = .keepAlways
        add(dump)
    }
'''

def render(config: dict, elements: dict[str, str], modules: list, cases: list) -> str:
    """One XCTestCase class: the locator table, the resolver, a method per module, a test
    per case."""
    out = [
        "// Generated by `optics-lsp generate --target xcuitest`. Do not edit — regenerate instead.",
        "//",
        "// This drives the device through XCTest, so the fallbacks optics applies when a",
        "// locator misses (ocr, image templates, self-heal) are not here. A locator either",
        "// matches or the step fails.",
        "",
        _PRELUDE,
        "    // MARK: elements",
        "",
        "    /// Locators as the suite wrote them. An xpath is not translated: it is evaluated",
        "    /// against a snapshot of the live hierarchy, which is the tree it was written for.",
        "    let ELEMENTS: [String: String] = [",
    ]
    out += [
        f"        {_swift_string(name)}: {_swift_string(locator)},"
        for name, locator in elements.items()
    ]
    out += [
        "    ]",
        "",
        f"    let ATTRIBUTES: Set<String> = {list(_ATTRIBUTES)!r}".replace("'", '"'),
        "",
        "    let TYPE_IDS: [String: UInt] = [",
    ]
    out += _wrapped(
        f"{_swift_string('XCUIElementType' + name)}: {id}," for name, id in _TYPE_IDS.items()
    )
    out += [
        "    ]",
        "",
        "    /// The same table read the other way, for `@type`. Derived rather than written",
        "    /// out again, so the two cannot disagree.",
        "    lazy var TYPE_NAMES: [UInt: String] = "
        "Dictionary(uniqueKeysWithValues: TYPE_IDS.map { ($1, $0) })",
        _RESOLVER,
        _HELPERS,
    ]

    out += ["    // MARK: modules", ""]
    for name, body in modules:
        out += [f"    /// {name}", f"    func {func_name(name)}() {{"]
        out += [f"        {line}" for line in body]
        out += ["    }", ""]
    out += ["    // MARK: test cases", ""]
    for name, body in cases:
        out += [f"    /// {name}", f"    func test{func_name(name)[:1].upper()}{func_name(name)[1:]}() {{"]
        out += [f"        {line}" for line in body]
        out += ["    }", ""]
    out += ["}", ""]
    return "\n".join(out)


def _wrapped(entries) -> list[str]:
    """Dictionary entries, filled across lines so the generated file stays readable."""
    lines, row = [], "       "
    for entry in entries:
        if len(row) + len(entry) > 95:
            lines.append(row)
            row = "       "
        row += " " + entry
    return lines + [row]
