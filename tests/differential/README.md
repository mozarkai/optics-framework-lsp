# Differential harness

Does a generated script find the element its locator named?

Nothing static answers that. The generated Swift type-checks whether or not its queries are
right, and a locator that quietly matches the wrong element passes every check a compiler can
make. So this drives a real app on a simulator or emulator and compares, per locator, against
a real xpath engine.

Locators are not hand-written. The app's own accessibility tree is dumped, parsed, and every
locator shape a suite uses is instantiated against it — bare types, attribute predicates,
absolute paths from the root with sibling indexes, and those paths truncated to their last few
steps. The expected answer comes from evaluating that same xpath with lxml over that same
tree, so a disagreement is the generator being wrong rather than the fixture being odd.

```console
$ uv run --with lxml python tests/differential/harness.py ios
204 of 204 locators agree

$ uv run --with lxml --with uiautomator2 python tests/differential/harness.py android
28 of 28 locators agree
```

Neither runs in CI — one needs Xcode and a booted simulator, the other adb and a running
emulator — which is why this is a script rather than a pytest case.

## The two halves are not the same test

**iOS is a differential.** The xcuitest target translates nothing: it carries the locator into
the generated file and resolves it there, against a snapshot of the hierarchy. That is a second
xpath implementation, and this is what disagrees with the first.

**Android is a smoke run.** uiautomator2 has xpath natively — the generated script hands the
locator to `d.xpath()`, which dumps the hierarchy and evaluates it with lxml. Comparing that
against lxml would be comparing lxml with itself. What is worth checking is that a generated
script runs at all: imports, connects, and finds what its locators name on a live device.

## The fixtures

iOS uses the app under `ios/`, which is checked in: chains deep enough to matter, repeated
siblings so an index means something, identifiers that disagree with labels, and text fields so
`@value` has something to match. Its content is deliberately nothing — the harness asserts on
structure, and inventing an app would only invite reading meaning into it.

Android uses whatever is on screen, because the comparison is against that same dump. Settings
is launched for repeatability, and the harness waits for the screen to stop moving before
reading it: a dump taken mid-transition describes a screen that is already gone.
