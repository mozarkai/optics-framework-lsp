# How a suite behaves at run time

What optics does with each step, checked against optics-framework 1.10.4. The script has to
do the same.

## Steps and params

- A **test case** is a list of module names. A **module** is a list of steps. A step is a
  keyword and its params, or the name of another module.
- **Params fill the keyword's signature in order** (`keywords.py` in the package lists it). A
  cell holding `name=value` is a named param and fills that slot instead - unless it starts
  with `/` or `(`, which makes it a locator that happens to contain `=`.
- A **named param the keyword does not have**, or one given twice, is an error in optics.
  Report the step.
- An **empty cell** means "use the default".
- `event_name` exists only for optics' event store. Drop it and report it.

## `${name}`

- Only a **whole cell** `${name}` is resolved. `Hello ${name}` is the literal text.
- `name` is looked up in the **elements**. Any other name is a variable bound at run time
  (by `Read Data`, `Evaluate`, `Run Loop`, `Get Text`). A name neither defines is an error:
  refuse the script.
- In a **locator param** (`element`, `elements`) the element is passed whole: every
  locator it lists, tried in order.
- In **any other param** it is the element's **first value**, as text. `Enter Text,
  ${field}, ${user}` types the first value of `user`.

## Elements

- An element is a name and **one or more locators**. The same name on several rows, or
  `Element_ID_fallback` columns, adds fallbacks, tried in the order they appear.
- Each locator is checked against `references/locators.md`. One with no native form is
  dropped. An element left with none is unusable, and a step using it as a locator
  cannot run.

## `config.yaml`

- **Android:** the Appium capabilities `deviceName`, `appPackage` and `appActivity` set the
  device and the app. A value `ENV:NAME` is read from the environment when the script runs,
  and fails if it is unset.
- **iOS:** the same `appium` block with `platformName: iOS` - `bundleId` (or
  `appium:bundleId`) names the app, `udid` (or `appium:udid`) the device. See
  `references/ios.md` → "Configuration".

## Keyword behaviour that is easy to get wrong

| Keyword | What optics does |
| --- | --- |
| Assert Presence / Visibility | Fails the test unless `fail` is `False` (case-insensitive), which makes it a soft check |
| Validate Element | Fails the test. Defaults: 10 s, rule `all` |
| Validate Screen | Soft check - records, never fails. Defaults: 30 s, rule `any` |
| Assertions on several elements | Split on `\|`, then `any` or `all` of them |
| Press Element | `repeat` presses that many times; `index` picks the nth match. Offsets only apply to an OCR or image match, so they are ignored |
| Press by Coordinates | Ignores `repeat` |
| Press by Percentage | Honours `repeat` |
| Swipe / Scroll From Element | Starts at the element's top edge (up/down) or left edge (left/right), centred on the other axis, and moves `length` pixels |
| Select Dropdown Option | Waits up to `timeout` for the option, scrolling the open list |
| Launch App | Starts the app the step names, else the configured one |
| Force Terminate App | Terminates the named app, not the app under test |
