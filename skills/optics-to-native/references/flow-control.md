# Control flow and variables

`Condition`, `Run Loop`, `Evaluate`, `Date Evaluate`, and the variable store they share. The
keyword tables mark these refused - translate them with this file instead, writing the code from
`references/code-patterns.md`. Behaviour is
optics-framework 1.10.4's.

## The variable store

optics keeps one store for the whole run: a name maps to a **list of strings**. Give the
script the same:

- Android: `VARS = {}` (already in the runtime) holding `{name: [str, ...]}`.
- iOS: `vars: [String: String]` holds the first value only - widen to `[String: [String]]`
  only if a keyword below needs the list.

Rules every keyword below follows:

- **Reading `${name}`** - only a whole cell is resolved, and it gives the **first** value as a
  string. Embedded `${x}` is left as text, except inside `Evaluate`, `Condition` and the
  `Read Data` query, which substitute it themselves (each differently, see below).
- **Element or variable** - optics keeps both in one map, and a write replaces a same-named
  element; so `${name}` reads the store first, then the elements. A name in neither fails the
  step: `E0201 Element not found`.
- **Setting** - `Evaluate`, `Run Loop`, `Read Data` and `Invoke API` *replace* the value.
  `Date Evaluate` *appends*, so a second `Date Evaluate` into the same name leaves the first
  value readable - reproduce that.
- **The name a keyword writes to** is written bare (`total`); strip `${}` if present.
- **Nothing else writes the store.** `Get Text` returns the text and stores nothing; keep it
  that way (Android's `VARS["last_text"]` is the runtime's own scratch, not a suite name).

## Condition

`Condition, cond1, target1, cond2, target2, …, [else_target]` - an odd count means the last
param is the else target. Pairs are tried in order; the first that runs its target ends it.

A **module condition** is a condition naming a module (after removing a leading `!`):

- Run the condition module for real - its steps act on the device.
- It is **true when it completes without an exception**; its results do not matter.
- `!Module` inverts: true when the module fails.
- True → run the target and stop. A target that raises in the non-inverted form is
  swallowed and evaluation moves to the next pair (optics quirk - reproduce it); with `!`
  a raising target fails the step.

An **expression condition** is anything else:

- Each `${x}` becomes `"<first value>"` - **in double quotes, so always a string**.
- Then a restricted Python expression (same grammar as `Evaluate`) decides truthiness.
- So `${n} > 5` compares a string with a number and fails the step; `${a} == "yes"` works.
- `!expr` inverts, and an inverted expression that **errors counts as true**.

Nothing matched → run the else target if there is one, else do nothing.

Android shape:

```python
def _module_ok(fn):
    try:
        fn(d)
        return True
    except Exception:
        return False

if _module_ok(validate_module):          # Condition, Validate Module, Process Flow, Fallback
    process_flow(d)
else:
    fallback(d)
```

iOS has no exceptions from `XCTAssert`; make the condition module return `Bool` (each
step's check `&&`-ed) or run it under `XCTContext.runActivity` and check
`testRun?.failureCount` before and after.

## Run Loop

- **Count form** - `Run Loop, Module, 3`: run the module that many times. Not an integer,
  or below 1 → fail the step. A failure inside the module stops the loop.
- **Variable form** - `Run Loop, Module, ${user}, a|b|c, ${pin}, 1|2|3`: pairs of name and
  values. A value list is `|`-separated (each piece stripped) or a JSON list. Iterations =
  the shortest list. Each iteration replaces each variable with its one value, then runs the
  module. Afterwards the variables keep their last value.
- An empty list, an odd pair count, or a value list that is neither → fail the step.
- A `${list}` as the values gives only its first value, which then has to be `|` or JSON
  itself - a `Read Data` result (`a,b,c`) is not.

## Evaluate

`Evaluate, total, ${a} + ${b} * 2`

- Each `${x}` is replaced by its first value **as raw text** (unquoted): `"3" + "4"` becomes
  `3 + 4` = `7`. A non-numeric value becomes a bare name and fails unless a stored name.
- Allowed: numbers, strings, `+ - * / % **`, comparisons `< > == != <= >=`, `and or not`,
  `a if c else b`, lists and tuples, bare names (= first value of that stored name, as text).
- **Not allowed** (fail the step): unary minus (`-5`, `x * -1`), `//`, `in`, `is`, calls,
  attributes, indexing.
- Store `str(result)`, replacing: `10/4` → `"2.5"`, `4/2` → `"2.0"`, booleans → `"True"`.

Android: run the same check as optics - `ast.parse(expr, mode="eval")`, reject any node
outside the list above, then `eval` with no builtins. iOS: `NSExpression(format:)` covers
the arithmetic; reject anything else.

## Date Evaluate

`Date Evaluate, out, <date>, <expr>, [<format>]`

- `<date>` is read with the first of `%m/%d/%Y`, `%d/%m/%Y`, `%Y-%m-%d`, `%d-%m-%Y`,
  `%Y/%m/%d` that parses (so `04/05/2025` is April 5). Nothing else - no `today`, no time.
- `<expr>` (lowercased): `+N day(s)` / `-N day(s)` - days only - or `today` / `now` (no
  change). Anything else fails.
- No clock, no timezone: purely from `<date>`.
- Output `strftime(<format>)`, default `%d %B` (`26 April`). **Appended** to `out`.
