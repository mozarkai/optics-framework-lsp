# Code patterns

How the keywords in `references/flow-control.md` and `references/data-and-api.md` are
written in each language. The semantics are in those files; this is the code. Add these
helpers to the script once, next to the runtime, and only the ones the suite uses.

Python needs `requests` and `jsonpath_ng` only when the script uses `Invoke API`; say so in
the report. `Read Data` uses the standard library only. The Swift uses regex literals, so iOS 16 or later.

Data the suite ships - CSV/JSON files for `Read Data`, the API YAML for `Invoke API` - is
**embedded in the script as literals** when you write it, so the script needs no project
folder and no YAML library. `ENV:` values are still read at run time.

## Variable store

```python
# VARS is the runtime's: {name: [str, ...]}
def _var(name):
    values = VARS.get(name) or ELEMENTS.get(name)
    if not values:
        raise AssertionError("E0201 Element not found: %s" % name)
    return str(values[0])

def _set(name, value):            # Evaluate, Run Loop, Read Data, Invoke API
    VARS[name] = [str(value)]

def _append(name, value):         # Date Evaluate
    VARS.setdefault(name, []).append(str(value))
```

```swift
/// Static: XCTest makes a new instance for every test method, and the store lives for the
/// whole run. It replaces the example's `vars`.
static var store: [String: [String]] = [:]

func v(_ name: String) -> String {
    if let first = Self.store[name]?.first ?? ELEMENTS[name]?.first { return first }
    XCTFail("E0201 Element not found: \(name)"); return ""
}
func set(_ name: String, _ value: String) { Self.store[name] = [value] }
func append(_ name: String, _ value: String) { Self.store[name, default: []].append(value) }
```

A step param `${name}` that is not a locator becomes `_var("name")` / `v("name")`.

## Condition

A module condition is a plain `if` on whether the module ran without failing.

```python
def _ok(d, module):
    try:
        module(d)
        return True
    except Exception:
        return False

def _condition(d, pairs, otherwise=None):
    """pairs: (is_true, target, swallow). optics swallows a failing target, moving on to the
    next pair, only after a module condition without `!`."""
    for is_true, target, swallow in pairs:
        if not is_true():
            continue
        try:
            target(d)
            return
        except Exception:
            if not swallow:
                raise
    if otherwise:
        otherwise(d)

# Condition, Is Logged In, Go Home, !Has Banner, Close Banner, ${status} == "ok", Done, Log In
# (in a module: `_origin(...)` on the line before, the source comment on the first line below)
_condition(d, [  # modules.csv:12 Condition
    (lambda: _ok(d, is_logged_in), go_home, True),
    (lambda: not _ok(d, has_banner), close_banner, False),
    (lambda: _var("status") == "ok", done, False),
], otherwise=log_in)
```

```swift
/// A module "passes" when it records no failure. Needs `continueAfterFailure = true`
/// for the duration, so the module runs to its end.
func ok(_ module: () -> Void) -> Bool {
    var failed = false
    let options = XCTExpectedFailure.Options()
    options.isStrict = false
    options.issueMatcher = { _ in failed = true; return true }
    let keep = continueAfterFailure
    continueAfterFailure = true
    swallowing += 1  // `record(_:)` of the run-output asset must not report this failure
    XCTExpectFailure("condition", options: options) { module() }
    swallowing -= 1
    continueAfterFailure = keep
    return !failed
}

// Condition, Is Logged In, Go Home, !Has Banner, Close Banner, Log In
var done = false
if ok(isLoggedIn) { done = ok(goHome) }                       // a module condition swallows a failing target...
if !done && !ok(hasBanner) { closeBanner(); done = true }     // ...a `!` condition does not
if !done { logIn() }
```

`ok` catches failed **assertions** (`Assert …`, `Validate …`, `XCTAssert…`). A step that acts on
an element that is not there (`tap`, `typeText`, a swipe from it) raises a failure XCTest does
not let `ok` catch: it ends the whole test case, inside `ok` too. So a condition's module may
only be a check, or must test the element first with `matches(...)`; for any other module,
write the step into the report as one that cannot be swallowed.

An expression condition compares the quoted first values - write it directly:
`${status} == "ok"` → `if _var("status") == "ok":` / `if v("status") == "ok" {`. If the
expression orders a quoted value against a number (`<`, `>`, `<=`, `>=`), optics raises - emit
the failure, not the comparison. `==` and `!=` against a number do not raise: emit them as
written, `"2" == 2` being False.

## Run Loop

```python
# Run Loop, Add Item, 3
for _ in range(3):
    add_item(d)

# Run Loop, Login, ${user}, alice|bob, ${pin}, 1111|2222|3333
for user, pin in zip(["alice", "bob"], ["1111", "2222", "3333"]):
    _set("user", user)
    _set("pin", pin)
    login(d)

# Run Loop, Type One Name, loop_name, Optics|Mozark|Bitbar   (one variable)
for _value in ["Optics", "Mozark", "Bitbar"]:
    _set("loop_name", _value)
    type_one_name(d)
```

```swift
for _ in 0..<3 { addItem() }

for (user, pin) in zip(["alice", "bob"], ["1111", "2222", "3333"]) {
    set("user", user); set("pin", pin); login()
}
```

Literal lists are split when you write the script. A list held in a variable is split at run
time: `_var("names").split("|")` / `v("names").components(separatedBy: "|")` (or parsed as
JSON when it starts with `[`).

## Evaluate

```python
import ast

_OK = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
       ast.Constant, ast.Name, ast.Load, ast.List, ast.Tuple, ast.Add, ast.Sub, ast.Mult,
       ast.Div, ast.Mod, ast.Pow, ast.Lt, ast.Gt, ast.Eq, ast.NotEq, ast.LtE, ast.GtE,
       ast.And, ast.Or, ast.Not)

def _evaluate(name, expression):
    expr = re.sub(r"\$\{([^}]+)\}", lambda m: _var(m.group(1)), expression)
    tree = ast.parse(expr, mode="eval")
    if not all(isinstance(n, _OK) for n in ast.walk(tree)):
        raise AssertionError("E0403 Unsafe expression detected")
    names = {k: str(v[0]) for k, v in {**ELEMENTS, **VARS}.items() if v}
    _set(name, eval(compile(tree, "<evaluate>", "eval"), {"__builtins__": None}, names))
```

`ast.UnaryOp` is listed only for `not`; a `-` is a `USub` operator node, which is not in the
list, so `-5` is refused as optics refuses it.

```swift
/// Arithmetic only: numbers, + - * / % and parentheses. Unary minus is refused, as optics does.
func evaluate(_ name: String, _ expression: String) {
    var expr = expression
    for key in expression.matches(of: #/\$\{([^}]+)\}/#).map({ String($0.1) }) {
        expr = expr.replacingOccurrences(of: "${\(key)}", with: v(key))
    }
    guard expr.range(of: #"^[0-9.+\-*/%() ]+$"#, options: .regularExpression) != nil,
          expr.range(of: #"(^|[-+*/%(])\s*-"#, options: .regularExpression) == nil else {
        return XCTFail("E0403 Unsafe expression detected: \(expr)")
    }
    // Doubles throughout, so 7/2 is 3.5 as in Python; then print as Python would.
    let asDoubles = expr.replacingOccurrences(of: #"(?<![\d.])(\d+)(?![\d.])"#, with: "$1.0",
                                              options: .regularExpression)
    let value = (NSExpression(format: asDoubles).expressionValue(with: nil, context: nil) as? Double) ?? .nan
    let integral = !expr.contains("/") && !expr.contains(".") && value == value.rounded()
    set(name, integral ? String(Int(value)) : String(value))
}
```

A comparison or `if`-expression in `Evaluate` is rare; on iOS write it as Swift when the
operands are known numbers, and report the step otherwise.

## Date Evaluate

```python
from datetime import datetime, timedelta

def _date_evaluate(name, date, expression, fmt="%d %B"):
    for f in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            day = datetime.strptime(date.strip(), f); break
        except ValueError:
            pass
    else:
        raise AssertionError("E0403 Unrecognised date: %s" % date)
    expr = expression.strip().lower()
    if expr not in ("today", "now"):
        sign, (n, unit) = expr[0], expr[1:].split()
        if sign not in "+-" or not unit.startswith("day"):
            raise AssertionError("E0403 Unsupported date expression: %s" % expression)
        day += timedelta(days=int(n) if sign == "+" else -int(n))
    _append(name, day.strftime(fmt or "%d %B"))
```

```swift
func dateEvaluate(_ name: String, _ date: String, _ expression: String, _ format: String = "dd MMMM") {
    let parser = DateFormatter(); parser.locale = Locale(identifier: "en_US_POSIX")
    var day: Date?
    for f in ["MM/dd/yyyy", "dd/MM/yyyy", "yyyy-MM-dd", "dd-MM-yyyy", "yyyy/MM/dd"] where day == nil {
        parser.dateFormat = f; day = parser.date(from: date.trimmingCharacters(in: .whitespaces))
    }
    guard var d = day else { return XCTFail("E0403 Unrecognised date: \(date)") }
    let expr = expression.trimmingCharacters(in: .whitespaces).lowercased()
    if expr != "today" && expr != "now" {
        let parts = expr.dropFirst().split(separator: " ")
        guard let sign = expr.first, "+-".contains(sign), parts.count == 2,
              let n = Int(parts[0]), parts[1].hasPrefix("day") else {
            return XCTFail("E0403 Unsupported date expression: \(expression)")
        }
        d = Calendar(identifier: .gregorian).date(byAdding: .day, value: sign == "+" ? n : -n, to: d)!
    }
    let out = DateFormatter(); out.dateFormat = format
    append(name, out.string(from: d))
}
```

Translate the suite's strftime format to a `DateFormatter` pattern when you write the step
(`%d %B` → `dd MMMM`, `%Y-%m-%d` → `yyyy-MM-dd`).

## Read Data

```python
import ast
import csv
import io
import re

DATA = {"users.csv": """device_serial,user,valid_upi
R58M,alice,alice@upi
"""}

_QUERY_OK = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name, ast.Load, ast.Constant,
             ast.List, ast.Tuple, ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.Gt,
             ast.LtE, ast.GtE, ast.In, ast.NotIn)

def _strings(column):
    if column and all(re.fullmatch(r"[+-]?\d+", c) for c in column):
        return [str(int(c)) for c in column]
    try:
        return [str(float(c)) if c != "" else None for c in column]
    except ValueError:
        return [c if c != "" else None for c in column]

def _table(text):
    header, *body = csv.reader(io.StringIO(text))
    body = [r for r in body if r]
    columns = [_strings([r[i] if i < len(r) else "" for r in body]) for i in range(len(header))]
    return header, [dict(zip(header, r)) for r in zip(*columns)]

def _read_data(name, source, query=""):
    header, rows = _table(DATA[source])
    parts = [p.strip() for p in query.split(";") if p.strip()]
    quote = lambda m: "'%s'" % _var(m.group(1))
    filters = [re.sub(r"(?<!')\$\{([^}]+)\}(?!')", quote, p) for p in parts if not p.startswith("select=")]
    selects = [p[len("select="):] for p in parts if p.startswith("select=")]
    if filters:
        tree = ast.parse(" and ".join(filters), mode="eval")
        if not all(isinstance(n, _QUERY_OK) for n in ast.walk(tree)):
            raise AssertionError("E0403 Unsupported query: %r" % query)
        code = compile(tree, "<query>", "eval")
        rows = [r for r in rows if eval(code, {"__builtins__": None}, r)]
        if not rows:
            raise AssertionError("E0403 No data found matching the query/filter: %r" % query)
    columns = [c.strip() for c in selects[-1].split(",")] if selects else header
    if len(rows) != 1:
        raise AssertionError("Read Data matched %d rows" % len(rows))
    _set(name, ",".join(rows[0][c] for c in columns))
```

No `pandas`: the CSV is read with `csv`, each column is turned into the text pandas would
give (`_strings`), and the filter is a Python expression over the row, which is what
`DataFrame.query` does for these operators. This was checked against `pandas` on 20 CSV and
query combinations with no differences. An empty selected cell fails the step - the join
raises `TypeError` - as it does in optics with pandas 3. A query with backticks or `.str` is
not a Python expression: refuse that step at write time.

`ENV:NAME` reads `os.environ["NAME"]` the same way (JSON or CSV), or stores the raw string.
A JSON file is a list of objects (a dict uses its first list-valued entry, else is one row);
flatten each object's nested keys to `a.b` with a small recursive function and turn every
value into text with `str`, then filter as above.

```swift
let DATA: [String: String] = ["users.csv": "device_serial,user,valid_upi\nR58M,alice,alice@upi\n"]

func header(_ csv: String) -> [String] {
    return cells(String(csv.split(whereSeparator: \.isNewline).first ?? ""))
}

func rows(_ csv: String) -> [[String: String]] {
    var lines = csv.split(whereSeparator: \.isNewline).map { cells(String($0)) }
    let header = lines.removeFirst()
    return lines.map { Dictionary(uniqueKeysWithValues: zip(header, $0)) }
}

/// One CSV line; quoted cells may hold commas and doubled quotes.
func cells(_ line: String) -> [String] {
    var out: [String] = [], cell = "", quoted = false, chars = Array(line), i = 0
    while i < chars.count {
        let c = chars[i]
        if quoted && c == "\"" && i + 1 < chars.count && chars[i + 1] == "\"" { cell.append("\""); i += 1 }
        else if c == "\"" { quoted.toggle() }
        else if c == "," && !quoted { out.append(cell); cell = "" }
        else { cell.append(c) }
        i += 1
    }
    return out + [cell]
}

func readData(_ name: String, _ source: String, _ query: String = "") {
    let parts = query.split(separator: ";").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    var table = rows(DATA[source] ?? "")
    let filters = parts.filter { !$0.hasPrefix("select=") }.map { part -> String in
        var p = part
        for key in part.matches(of: #/\$\{([^}]+)\}/#).map({ String($0.1) }) {
            p = p.replacingOccurrences(of: "${\(key)}", with: "'\(v(key))'")
        }
        return p
    }
    if !filters.isEmpty {
        let predicate = NSPredicate(format: filters.joined(separator: " AND "))
        table = table.filter { predicate.evaluate(with: $0) }
        if table.isEmpty { return XCTFail("E0403 No data found matching the query/filter: \(query)") }
    }
    let columns = parts.last(where: { $0.hasPrefix("select=") }).map {
        $0.dropFirst(7).split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
    }
    guard table.count == 1, let row = table.first else { return XCTFail("Read Data matched \(table.count) rows") }
    set(name, (columns ?? header(DATA[source] ?? "")).map { row[$0] ?? "" }.joined(separator: ","))
}
```

`NSPredicate` reads `col == 'v'`, `!=`, `<`, `>`, `AND`/`OR` (any case) and parentheses -
refuse a query using anything beyond those (`in`, `.str`, backticks).

## Invoke API

The API definition is embedded from the YAML when you write the script.

```python
import requests
from jsonpath_ng import parse as jsonpath

API = {"bank.login": {
    "url": "https://api.example.com/v1/login", "method": "POST",
    "headers": {"Content-Type": "application/json", "X-Device": "${serial_id}"},
    "body": {"user": "${user}", "pin": "${pin}"},
    "extract": {"token": "$.data.token"},
    "assertions": [("$.status", "$ == 'ok'")],
}}

def _fill(value):
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: _var(m.group(1)), value)
    if isinstance(value, dict):
        return {k: _fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v) for v in value]
    return value

def _invoke_api(identifier):
    api = API[identifier]
    response = requests.request(api["method"], _fill(api["url"]), headers=_fill(api["headers"]),
                                json=_fill(api.get("body")), timeout=30)
    if "extract" not in api and "assertions" not in api:
        return
    body = response.json()
    for name, path in api.get("extract", {}).items():
        found = jsonpath(path).find(body)
        if found:
            _set(name, found[0].value)
    for path, condition in api.get("assertions", []):
        found = jsonpath(path).find(body)
        assert found and eval(condition.replace("$", repr(found[0].value))), condition
```

```swift
struct Api { let url: String; let method: String; let headers: [String: String]; let body: Any?
             let extract: [String: String] }

let API: [String: Api] = ["bank.login": Api(
    url: "https://api.example.com/v1/login", method: "POST",
    headers: ["Content-Type": "application/json", "X-Device": "${serial_id}"],
    body: ["user": "${user}", "pin": "${pin}"], extract: ["token": "data.token"])]

func fill(_ value: Any?) -> Any? {
    if let s = value as? String {
        return s.matches(of: #/\$\{([^}]+)\}/#).reduce(s) { $0.replacingOccurrences(of: "${\($1.1)}", with: v(String($1.1))) }
    }
    if let d = value as? [String: Any] { return d.mapValues { fill($0) as Any } }
    if let a = value as? [Any] { return a.map { fill($0) as Any } }
    return value
}

/// `a.b[0].c` - dot keys and indexes, the subset suites use.
func walk(_ json: Any, _ path: String) -> Any? {
    var node: Any? = json
    for part in path.replacingOccurrences(of: "$.", with: "").split(separator: ".") {
        let name = part.split(separator: "[").first.map(String.init) ?? ""
        if !name.isEmpty { node = (node as? [String: Any])?[name] }
        for index in part.matches(of: #/\[(\d+)\]/#) { node = (node as? [Any])?[Int(index.1)!] }
    }
    return node
}

func invokeApi(_ identifier: String) {
    guard let api = API[identifier], let url = URL(string: fill(api.url) as! String) else {
        return XCTFail("E0601 Unknown API \(identifier)")
    }
    var request = URLRequest(url: url, timeoutInterval: 30)
    request.httpMethod = api.method
    (fill(api.headers) as? [String: String])?.forEach { request.setValue($1, forHTTPHeaderField: $0) }
    if let body = fill(api.body) { request.httpBody = try? JSONSerialization.data(withJSONObject: body) }
    let done = DispatchSemaphore(value: 0)
    var data: Data?
    URLSession.shared.dataTask(with: request) { d, _, _ in data = d; done.signal() }.resume()
    done.wait()
    guard !api.extract.isEmpty else { return }
    guard let raw = data, let json = try? JSONSerialization.jsonObject(with: raw) else {
        return XCTFail("E0403 The response is not JSON")
    }
    for (name, path) in api.extract { if let value = walk(json, path) { set(name, "\(value)") } }
}
```

On iOS write each `jsonpath_assertions` entry as a Swift comparison on `walk(json, path)`
(`== != < > <= >=`); report one using anything else.
