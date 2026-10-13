# What a run leaves behind

Error-code detection, the report files, mapping failures back to the suite, and waits. Every
script writes these the same way so a CI job - or App Studio - can read any of them.

All output goes to the folder in `EXEC_OUTPUT`, default `./output` (iOS: the test's
`XCTAttachment`s plus the same files in `EXEC_OUTPUT`, default `NSTemporaryDirectory()/output`;
on iOS a failing step ends the test case, and `tearDownWithError` writes its result).

## Error-code detection

The suite's error definitions are any CSV whose header has `error_code` and `match_string`
(`description`, `severity` optional; a row missing either required cell is dropped; a later
row with the same code wins). Carry them into the script as a table.

**At the end of every test case**, whether its steps passed or not:

1. Capture the page source.
2. Turn it into text: for each element, the non-empty values of `text`, `content-desc`,
   `label`, `value`, `hint`, `name`, joined with spaces.
3. For each definition, **case-insensitive substring**: `match_string` in the text →
   matched on `match_string`; else the code itself in the text → matched on `code`.
4. Any match **fails the test case** with the reason
   `"; ".join(f"{code}: {description or match_string}")` - this takes precedence over a
   step failure's reason.
5. Append the matches to the `detected` list of `detected_errors_<session>.json` (one file
   per session, rewritten whole each time):

```json
{"timestamp": "2026-10-05T19:02:13", "detected": [
  {"error_code": "E_SESSION", "matched_on": "match_string", "match_string": "Session expired",
   "description": "Kicked back to the login screen", "severity": "high",
   "detected_at": "end_of_test", "test_case": "Login"}]}
```

`<session>` is `SESSION_ID` from the environment, else a timestamp. The file is written only
when a test case matched something; a clean run leaves none.

## Report files

**`test_report.json`** - one suite, one entry per test case:

```json
{"testSuites": [{"name": "Test Cases", "status": "PASS", "type": "testSuite",
  "start": "2026-10-05T19:02:13.000000", "end": "...", "duration": "12.345000",
  "id": "s1-s1-s1-s1-s1", "appVersion": null,
  "testCases": [{"name": "Login", "status": "PASS", "type": "testCase", "testSuite": "Test Cases",
    "start": "...", "end": "...", "duration": "3.100000", "id": "s1-s1-s1-s1-s1-t1",
    "reason": "Test completed successfully",
    "steps": [{"name": "Sign In", "status": "PASS", "type": "step", "start": "...", "end": "...",
      "duration": "1.200000", "testSuite": "Test Cases", "testCase": "Login",
      "owner": "OpticsKeywords.ActionKeywords", "subSteps": []}]}]}]}
```

- Statuses `PASS` / `FAIL` / `ERROR` / `SKIP`; a step after the failing one is `NOT RUN`.
- Times `%Y-%m-%dT%H:%M:%S.%f`; durations strings with six decimals.
- `reason`: `Test completed successfully` on pass, else the failure message.
- One step per module. `owner` is the optics class that defines the keyword of the module's
  first step, under `OpticsKeywords.`. Read off optics 1.10.5:
  - `ActionKeywords`: Clear Element Text, Detect And Press, Enter Number, Enter Text, Enter
    Text Direct, Enter Text Using Keyboard, Execute Script, Get Text, Press By Coordinates,
    Press By Percentage, Press Checkbox, Press Element, Press Element With Index, Press
    Keycode, Press Radio Button, Scroll, Scroll From Element, Scroll Until Element Appears,
    Select Dropdown Option, Sleep, Swipe, Swipe By Percentage, Swipe From Element, Swipe
    Seekbar To Right Android, Swipe Until Element Appears
  - `AppManagement`: Close And Terminate App, Force Terminate App, Get App Version, Get Driver
    Session Id, Initialise Setup, Launch App, Launch Other App, Quit, Start Appium Session
  - `Verifier`: Assert Equality, Assert Presence, Assert Visibility, **Capture Pagesource,
    Capture Screenshot**, Get Interactive Elements, Get Screen Elements, Is Element, Validate
    Element, Validate Screen
  - `FlowControl`: Condition, Date Evaluate, Evaluate, Execute Module, Invoke API, Read Data,
    Run Loop

  A module that is only another module's call is `FlowControl`.
- `FAIL` for an assertion (`AssertionError`), `ERROR` for any other exception.

**`junit-results.xml`** - `<testsuites>` > `<testsuite tests failures errors skipped time>` >
one `<testcase name classname time>` per test case, with `<failure message>` for a `FAIL`
and `<error message>` for an `ERROR`.

**Screenshots** - `post-<%Y-%m-%dT%H-%M-%S-%f>-failure.jpg` when a test case fails, and
`post-<ts>-<keyword>.jpg` (the keyword as the suite writes it, spaces kept) after each
action step - a step whose keyword's owner is `ActionKeywords` or `AppManagement`, except
`Sleep` - unless `ENABLE_POST_SCREENSHOT` is `0`, `false` or `no`. A screenshot that cannot
be taken (the app was just closed) never fails the step. The file names are the skill's own:
optics 1.10.4 writes `<ts>-<keyword>.jpg` and `pre_<keyword>.jpg` files instead, and nothing
reads them for a result, so they are not part of the pass/fail behaviour.

## Source map

Every emitted step line ends with where it came from, and a failure names it:

```python
    _find(d, ELEMENTS['login_button']).click()  # modules.csv:7 Press Element
```

- Before each step, set the current origin (`_origin("modules.csv:7 Press Element")` on
  Android, `at = "modules.csv:7 Press Element"` on iOS); the failure message and the
  report's `reason` start with it: `modules.csv:7 Press Element: none of [...] matched`.
- Only steps set an origin; a test function's module calls get the comment only.
- The origin is the step's file and **line number as an editor shows it** (1-based, header
  and blank lines included; YAML: its line). A module's steps come in file order, so its nth
  step in `optics-lsp parse` is the nth non-blank row of that module; a module split across
  files keeps each part's own file.

## Waits

optics has no global wait setting - each keyword's timeout is its own param, with these
defaults:

| | Default |
| --- | --- |
| Assert Presence / Visibility, Validate Screen, Detect And Press, Select Dropdown Option | 30 s |
| Validate Element | 10 s |
| Between steps | 0.1 s (`halt_duration`) |

Keep the per-keyword defaults, and make the script's own waits settings read once at the top:

| Setting | Env var | Default |
| --- | --- | --- |
| How long a find waits for an element | `OPTICS_WAIT_TIMEOUT` | 20 s |
| How often a wait re-checks | `OPTICS_POLL_INTERVAL` | 0.2 s Android, 0.3 s iOS |
| Pause between steps | `OPTICS_STEP_DELAY` | 0.1 s |

Android: set `d.settings["wait_timeout"]` and the `time.sleep` in the wait loops from them.
iOS: `IMPLICIT_WAIT` and the `Thread.sleep` in `waitUntil` from
`ProcessInfo.processInfo.environment`.
