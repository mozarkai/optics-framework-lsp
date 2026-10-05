# iOS script (XCUITest)

One Swift file holding one `XCTestCase`. `assets/xcuitest_example.swift` is the shape to
copy:

| Part | What goes there |
| --- | --- |
| Header comment, `import XCTest`, the class line | Unchanged |
| `app`, `vars`, `soft`, `setUpWithError` | Unchanged |
| `// MARK: elements` → `ELEMENTS` | Every usable element: `"name": ["locator", "fallback", ...]` in suite order, with refused locators left out |
| `IMPLICIT_WAIT`, `ATTRIBUTES`, `TYPE_IDS` | Unchanged |
| `// MARK: locators`, `waiting`, `acting` | Unchanged - the runtime, including the on-device xpath resolver |
| `// MARK: modules` | One `func <name>()` per module, one line per step |
| `// MARK: test cases` | One `func test<Name>()` per test case, calling its modules in order |

## Names

- A function name is the block name in lowerCamelCase (`Sign In` → `signIn`), with `m` in
  front if it starts with a digit. A test case is `test` + UpperCamelCase (`Login` → `testLogin`).
- Clashes with each other, with a Swift keyword, or with a name the runtime declares get
  `_2`, `_3` … in suite order. Calls use the assigned name.

## Values

- A literal param is a Swift string: `"demo_user"`.
- A locator param holding an element is passed by **name**, as a string: `el("login_button")`.
  The runtime looks the name up in `ELEMENTS` at run time, so a wait re-resolves instead of
  holding a stale handle.
- A value param holding an element is its first value, inlined as a literal.
- A run-time variable is `(vars["name"] ?? "")`.

## How an xpath runs

XCTest has no xpath, and a query is not a translation of one: an xpath index counts within
each parent while a query flattens every match into one list, and the tree a query walks is
not the tree a page source shows. So **an xpath is never rewritten into a query.** Put it in
`ELEMENTS` exactly as the suite wrote it; the runtime evaluates it on the device each time a
step needs it:

1. `snapshotTree()` captures the live hierarchy as `Node`s - type, `name`, `identifier`,
   `label`, `value`, and the node's `path` as a chain of child indexes.
2. `parseXPath(_:)` splits the xpath into steps; `evaluate(_:in:)` runs them against the
   snapshot, `apply(_:to:)` doing one step against one context node.
3. `predicate(_:)` turns each `[...]` test into an `NSPredicate`.
4. `element(at:)` walks a match's `path` back to a live `XCUIElement` through
   `children(matching: .any)`, which enumerates in the same order as the snapshot.
5. `lookup(_:_:_:)` does this for one locator; a plain string is matched on
   `identifier`, `label` or `value` instead. `resolve(_:_:)` tries an element's locators
   in order and returns the first that exists.

Steps call it by element name only: `el("login_button")`, `elAt("row", "2")`,
`waitFor(...)`, `matches(...)`. Never build an `XCUIElementQuery` in a step.

What the evaluator reads - anything else makes it match nothing, so refuse the locator
instead:

| Part | Supported |
| --- | --- |
| Steps | `/child` and `//descendant` |
| Node test | `*`, or a full type name: `XCUIElementTypeButton`, not `Button` |
| Index | `[2]` (1-based, within each parent), `[last()]`, and `(//path)[2]` over the whole result |
| Predicate attributes | `@name`, `@identifier`, `@label`, `@value`, `@type`, `@elementType` |
| Predicate operators | `=`, `!=`, `and`, `or`, `contains(@a,'x')`, `starts-with(@a,'x')`, `ends-with(@a,'x')`, with single or double quotes |


## Configuration

From `config.yaml`'s `appium` capabilities (also accepted with an `appium:` prefix):

- `bundleId` → `BUNDLE_ID`. In `setUpWithError` create the app with
  `XCUIApplication(bundleIdentifier: BUNDLE_ID)` instead of `XCUIApplication()`, so every
  step drives that app; with no `bundleId`, keep `XCUIApplication()` (the UI-test target's
  own app). A `Launch App` step naming a bundle id still overrides it.
- `ENV:NAME` values are read with `ProcessInfo.processInfo.environment["NAME"]` and fail the
  test when unset - pass them through the test plan's environment variables.
- `udid` is not set in code: it picks the device, so put it in the run command,
  `xcodebuild test -destination 'id=<udid>'`, and say so in the report.

## Running it

Add the file to an existing Xcode UI-test target, then run the tests on a simulator or
device.
