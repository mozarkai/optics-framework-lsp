---
name: optics-to-native
description: Translate an optics-framework test suite (CSV or YAML) into a native test script - Python over uiautomator2 for Android, or Swift over XCUITest for iOS - and report every step that could not come across. Use when asked to convert, port or export an optics suite to a native Android or iOS test.
---

# optics → native script

You turn an optics suite into one self-contained script that drives the device
directly, without optics-framework, Appium or a server. The script has to do what optics
would do step for step, and anything it cannot do is reported, never approximated.

## Workflow

1. **Lint the suite.** `optics-lsp lint <suite>`. Stop on any error and show it: a suite
   optics itself would reject is not translated.
2. **Read the suite through the parser**, not by hand. `optics-lsp parse <suite>` prints
   the modules, test cases, steps, params, elements, API collections and error definitions
   as JSON, in both CSV and YAML. It does not give rows - read those from the files for the
   source map (`references/run-output.md`).
3. **Pick the target** from `config.yaml`: `appium` with `platformName: Android` →
   uiautomator2; `platformName: iOS` → XCUITest. A browser suite (`playwright` or
   `selenium` driver) is not translated - say so and stop.
4. **Read the keyword tables from the installed optics-lsp.** Find the package with
   `python -c "import optics_framework_lsp, os; print(os.path.dirname(optics_framework_lsp.__file__))"`,
   using the Python optics-lsp is installed into - for `uv tool install` that is
   `~/.local/share/uv/tools/optics-framework-lsp/bin/python`, not the system one. Then read:
   - `keywords.py` - every keyword optics has: params in signature order, how many are
     required, the defaults
   - `generate/targets/uiautomator2.py` or `generate/targets/xcuitest.py` - `EMIT` maps a
     keyword to how many params the translation reads and the code it writes (`p[0]`,
     `p[1]` … are the params in order); `UNSUPPORTED` maps a keyword to why it is refused.
     The helpers those lines call (`_to`, `_rule`, `_times` …) are in the same file.
   When a param is empty, use its default and drop that part of the call - the example
   scripts show the plain form.
5. **Read the references** for what you need:
   - `references/suite-semantics.md` - params, `${name}`, fallbacks, `ENV:`, `config.yaml`
   - `references/locators.md` - which locators each target can carry
   - `references/android.md` or `references/ios.md` - the script's layout
   - `references/flow-control.md` - `Condition`, `Run Loop`, `Evaluate`, `Date Evaluate`
     and the variable store
   - `references/data-and-api.md` - `Read Data` and `Invoke API`
   - `references/code-patterns.md` - the Python and Swift code for those six keywords:
     `if`/`else` for `Condition`, `for` loops for `Run Loop`, `requests` / `URLSession` for
     `Invoke API`. Copy these patterns rather than inventing new ones
   - `references/run-output.md` - error-code detection, report files, source map, waits
6. **Start from the example** for the target: `assets/uiautomator2_example.py` or
   `assets/xcuitest_example.swift`. Keep its runtime, and
   replace the settings, the `ELEMENTS` table, the module functions and the test case
   functions. The example is the translation of `examples/login/` (in this skill's folder)
   *before* step 7 - compare against it for the core; step 7 adds to it.
7. **Add what every script carries**, from `references/run-output.md`: the error
   definitions and the end-of-test check, the report files, the source-map comment and
   origin on every step, and the wait settings. These are the only changes allowed to the
   runtime: `main()` / the test runner, and the fixed sleeps and timeouts in the wait loops.
   Run the test cases **in suite order**, not alphabetically.
8. **Write a report** after the script: one line per step or element you could not
   translate, with file, row, step and reason. Say "0 steps did not translate" when there
   are none.
9. **Check the script**, and fix it until the check is clean.
   - Android: `uvx pyflakes <file>`. `'os' imported but unused` is expected when
     the script reads no environment variable.
   - iOS: type-check against the simulator SDK:
     ```
     DEV="$(xcrun --sdk iphonesimulator --show-sdk-platform-path)/Developer"
     xcrun swiftc -typecheck -sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)" \
       -target arm64-apple-ios17.0-simulator -F "$DEV/Library/Frameworks" -I "$DEV/usr/lib" <file>
     ```

## Hard rules

- **One function per module, one test function per test case** that calls its modules in
  order - never inline a module, even one used once. Modules are reused across test cases,
  `Condition` and `Run Loop` call them by name, and each test case is one result in the report.
- **Never invent a locator.** Only the locators the suite lists, in its order.
- **Never drop a param silently.** If a param has no native form, the step is reported.
- **Refuse the whole script** when a step cannot run because an element it uses as a
  locator has no usable locator, or a `${name}` it reads is defined nowhere. A script that
  silently skips a step tests less than the suite.
- **Don't edit the runtime's helpers** beyond what step 7 allows. They were checked on a real
  emulator and simulator. Add only the helpers the references describe (variable store, flow control, data, API,
  detection, reports, source map); for anything else, report the step.
- **Keywords come from `keywords.py` only.** A keyword not in it is unknown to optics.
- **Refused keywords:** `Condition`, `Run Loop`, `Evaluate`, `Date Evaluate`, `Read Data`
  and `Invoke API` are refused in the tables but translated with the references above.
  Every other keyword in `UNSUPPORTED` is refused, whatever it looks like it could become.
- **Reproduce optics, quirks included.** Where the references note optics behaving oddly
  (a condition's swallowed target error, `Date Evaluate` appending, a multi-row `Read Data`
  failing), the script does the same, so it passes and fails where optics would.
