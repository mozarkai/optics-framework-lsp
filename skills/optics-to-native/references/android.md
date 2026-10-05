# Android script (uiautomator2)

One Python file. `assets/uiautomator2_example.py` is the shape to copy, top to bottom:

| Part | What goes there |
| --- | --- |
| Header comment | Unchanged |
| Imports | Unchanged |
| `SERIAL`, `PACKAGE`, `ACTIVITY` | From `config.yaml`: `deviceName`, `appPackage`, `appActivity`, as string literals, or `os.environ['NAME']` for an `ENV:NAME` value |
| `VARS`, `SOFT`, `OUT` | Unchanged |
| Helpers `_selector` … `_write_pagesource` | Unchanged - the runtime |
| `ELEMENTS` | Every usable element - including value-only ones a run-time expression reads, such as `Evaluate`'s operands: `'name': ['locator', 'fallback', ...]` in suite order, with refused locators left out |
| `# Modules` | One `def <name>(d):` per module, its docstring the original name, one line per step |
| `# Test cases` | One `def test_<name>(d):` per test case, calling its modules in order |
| `main()` and the `__main__` guard | Unchanged |

## Names

- A function name is the block name lowercased, with every run of other characters
  replaced by `_` (`Sign In` → `sign_in`, test cases get `test_`). A name starting with a
  digit gets `m_` in front.
- Two blocks that land on the same name, or a name the script already uses (`main`, `sys`,
  `time`, `u2`, `d`, a Python keyword), get `_2`, `_3` … in suite order. Calls use the
  assigned name.

## Values

- A literal param is a Python string: `'demo_user'`.
- A locator param holding an element is `ELEMENTS['name']`.
- A value param holding an element is that element's first value, inlined as a literal.
- A run-time variable is `_var('name')` (from `references/code-patterns.md`) - `VARS` holds
  lists, so never pass `VARS['name']` itself.

## Running it

`pip install uiautomator2`, a device with `python -m uiautomator2 init` done, then
`python <file>`. It prints `PASS`/`FAIL` per test case, and exits non-zero if any failed.
