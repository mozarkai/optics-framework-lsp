# Read Data and Invoke API

Both write the variable store from `references/flow-control.md`. The keyword tables mark
them refused - translate them with this file instead, writing the code from
`references/code-patterns.md`. Behaviour is optics-framework 1.10.4's.

## Read Data

`Read Data, out, <source>, [<query>]`

**Source**

- A `.csv` or `.json` path, relative to the project folder (the suite's root). Ship the file
  with the script and resolve it from there. Missing file or other extension → fail.
- `ENV:NAME` - read from the environment (missing → fail). A value starting with `{`, `[`
  or `"` is JSON; otherwise it is tried as CSV; if neither gives a table, the raw string is
  the result and the query is ignored.
- JSON: a dict uses its first list-valued entry, else becomes one row; nested keys flatten to
  `a.b` column names.

**Every cell becomes a string** after pandas reads it - so `007` reads as `7` and an integer
in a float column as `1.0`. Android: use `pandas.read_csv(...).astype(str)` to match.

**Query** - split on `;`, strip, drop empty parts:

- `select=col1,col2` picks columns (the last `select=` wins).
- Every other part is a filter; filters are joined with ` and ` and run as
  **`pandas.DataFrame.query`** (so `==`, `!=`, `<`, `in [...]`, `and`/`or`, parentheses,
  backticks for odd column names).
- Each `${x}` in a part becomes its first value **in single quotes** (`'R58M'`), unless it is
  already inside single quotes. Columns are strings, so compare against quoted values.
- Filter error or unknown column → fail. Query given and no row matches → fail. Selected
  column missing → fail.

**Result**

- **One row:** store `','.join(row)` as the single value - with one selected column that is
  just the cell (`alice@upi`).
- **Zero or several rows:** optics crashes (`TypeError` joining lists). Fail the step with
  `Read Data matched N rows` rather than invent a shape.

Android: `pandas` exactly as above. iOS: parse the CSV yourself (cells as strings), and
evaluate the filters with `NSPredicate(format:)` over `[String: String]` rows - it reads
`col == 'v'`, `!=`, `AND`/`OR` and parentheses; refuse a query using anything else.

## Invoke API

`Invoke API, collection.api` - the definition lives in the suite's API YAML (top-level
`api:` or `apis:`; several files merge):

```yaml
api:
  collections:
    bank:                          # the key is what the step names, not `name`
      name: bank
      base_url: https://api.example.com
      global_headers: {Content-Type: application/json}
      apis:
        login:
          name: login
          endpoint: /v1/login      # a full http(s) URL here ignores base_url
          request:
            method: POST
            headers: {X-Device: "${serial_id}"}
            body: {user: "${user}", pin: "${pin}"}
          expected_result:
            extract: {token: data.token}               # store under `token`
            jsonpath_assertions:
              - {path: "$.status", condition: "$ == 'ok'"}
```

- URL = `base_url + endpoint` (no slash fixing). `${x}` is resolved in the endpoint,
  header values and body strings (recursively) - not in `base_url`, not in keys.
- Headers = `global_headers` then the API's own on top.
- Send `method` with the body **as JSON** and a 30 s timeout. No retries. A 4xx/5xx
  response **passes** - there is no status check (`expected_status` and `timeout` in the YAML
  are ignored).
- Only when `expected_result` exists: the body must be JSON (else fail).
  - `extract` - each path (`$.` added if missing; plain dot keys, `[n]`, `[*]`; no filters)
    → store the first match, replacing. No match: leave the variable unset, don't fail.
  - `jsonpath_assertions` - first match `m`, then the condition with `$` replaced by `m`
    must be true; no match or false → fail.

Android: `requests.request(method, url, headers=..., json=body, timeout=30)` and
`jsonpath_ng.parse`. iOS: `URLSession` waited on with a semaphore, `JSONSerialization` for
the body, a small dot/`[n]` path walker, and conditions limited to `== != < > <= >=` -
refuse others. The request leaves from the device, so the device needs the network the API
is on.
