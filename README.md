<h1 align="center">optics-framework-lsp</h1>

<p align="center">
  A language server and linter for
  <a href="https://mozarkai.github.io/optics-framework/">optics-framework</a> test suites.
</p>

<p align="center">
  <a href="https://github.com/mozarkai/optics-framework-lsp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.14%2B-blue" alt="Python 3.14+">
</p>

---

An optics suite is CSV files referring to each other by name, and nothing checks that those
names line up. This does, across the whole project, over LSP while you type or as one command.
Its rules come from optics-framework's own readers, so it agrees with the runtime.

## Install

```sh
uv tool install optics-framework-lsp
```

Or from a checkout, for development:

```sh
uv sync
```

### In an editor

Two packaged clients bundle the server's dependencies, so neither needs the steps above:

- **VS Code** — [`editors/code`](editors/code/README.md)
- **IntelliJ, PyCharm and other JetBrains IDEs** — [`editors/intellij`](editors/intellij/README.md)

Both need a Python 3.12+ interpreter and attach to every `*.csv` in the project without claiming
the `.csv` extension, so whatever CSV editor you already use is untouched.

---

# The linter

`optics-lsp lint` reports every problem in a suite in one shot. Point it at a project:

```console
$ optics-lsp lint ~/projects/my_project
```

Line numbers are 1-based, matching your editor's status bar. A whole project takes about
60 ms including process start, because nothing on this path imports any LSP machinery.

**The exit code is 0 whenever validation ran**, findings or not. Non-zero means the input could
not be read at all. Which severities should block a pipeline is your policy, so read `status`
if you want that decision made for you.

<details>
<summary><b>JSON, for another program</b></summary>

Add `--json` for the machine-readable form. A caller holding uploaded files in memory, with
nothing on disk, can pipe them in instead and skip the filesystem entirely:

```console
$ echo '{"files": [{"name": "modules.csv", "content": "module_name,module_step\nM,Sleep\n"}]}' \
    | optics-lsp lint
```

Reading on stdin always answers JSON:

```json
{
  "status": "FAIL",
  "analyzed": { "modules.csv": "modules" },
  "skipped": [],
  "diagnostics": [
    {
      "uri": "modules.csv",
      "severity": "error",
      "code": "keyword-arity",
      "message": "'Sleep' takes 1-1 params, got 0",
      "row": 2,
      "range": { "startLine": 1, "startColumn": 0, "endLine": 2, "endColumn": 0 },
      "source": "optics"
    }
  ]
}
```

`row` is 1-based for a person, `range` is 0-based for an editor. Diagnostics arrive sorted by
file then row, so a caller need not re-sort.

Shelling out from Node: pass the arguments as an array with the payload on stdin rather than
interpolating either into a shell string, and raise `maxBuffer` past its 1 MB default. 

</details>

<details>
<summary><b><code>analyzed</code> and <code>skipped</code>: which files were even looked at</b></summary>

File kind comes from the header row, not the filename. `analyzed` says what each file became
(`test_cases`, `modules`, `elements`, `error_definitions`); `skipped` lists the CSVs whose
header matched none of those.

optics ignores those files too, so a skipped file is usually a dataset and fine. But a
`test_cases` file with a typo in its header lands there as well, and would otherwise be
indistinguishable from a clean one.

</details>

## What it reports

Two severities, and the line between them is one question: **does optics fail, or does it run
and do something you probably didn't mean?**

Errors are a name that resolves to nothing, or a call the keyword rejects:

| code | meaning |
| --- | --- |
| `module-not-found` | a test step names a module no file defines |
| `keyword-not-found` | a module step is neither a keyword nor another module |
| `keyword-arity` | a keyword got too few or too many params |
| `element-not-found` | a `${ref}` has no element and nothing binds it |

Warnings mean it loads, but a row you wrote isn't doing what it looks like:

| code | meaning |
| --- | --- |
| `duplicate-module`, `duplicate-test-case` | the later definition wins, wherever the files sit |
| `duplicate-element` | a file repeats an entire element row |
| `duplicate-error-code`, `duplicate-match-string` | error definitions merge across files, so these clash |
| `error-definition-incomplete` | a row missing a column, so it never matches |
| `csv-too-few-columns` | the reader skips the row |
| `csv-too-many-columns` | the extra cells are dropped |
| `csv-whitespace-line` | a row of nothing but separators |

---

# The language server

Run with no arguments and it speaks LSP over stdio. Unknown flags are ignored rather than
rejected, so a client that insists on passing `--stdio` needs no special handling.

One workspace folder is one project. Cross-file rules mean a single edit can change
diagnostics anywhere in the suite, so the whole folder is revalidated on every change, and the
server asks the client to watch `**/*.csv` so a git checkout is picked up too. Open buffers
override what is on disk. Dot folders are never descended into, because a project's `.venv` holds
optics-framework's own sample CSVs and images, which would invent element and module names the
project does not have.

## Features

<details open>
<summary><b>Diagnostics</b></summary>

Everything from the linter section above, live, across the whole project. Because resolution
is a project-wide question, defining an element in one file clears the `element-not-found` in
another without touching it.

</details>

<details>
<summary><b>Completion</b></summary>

Aware of which column you are in, because in a CSV the column *is* the context.

| where the cursor is | what is offered |
| --- | --- |
| an empty file | the four header rows, since the header decides the file's kind |
| `module_step` | every keyword **and** every module in the project, since a step can be either |
| a param cell | what that particular keyword accepts at that position |
| `test_step`, `module_name` | modules that already exist, since both columns continue a block |
| `element_name` | names used somewhere but never defined |
| any `element_id*` | template image filenames found anywhere in the project |
| `test_case` | existing test cases, plus the lifecycle names (`Suite Setup`, …) not yet used |

Param completion is specific rather than generic. `Read Data`'s second param offers the
project's data files; `Invoke API`'s first offers `collection.api` identifiers parsed out of
the project's YAML; `Run Loop` and `Execute Module` offer modules, written bare. Params with a
documented set of values offer exactly those. `direction` gives `up`, `down`, `left`, `right`;
`rule` gives `any`, `all`; `element_state` gives `visible`, `invisible`, `enabled`, `disabled`.
`Condition` alternates condition and target, so it offers modules in the target slots and
modules-or-variables in the others, with `!` inversion preserved.

Accepting a param the header does not yet cover **widens the header in the same edit**, because
`csv.DictReader` drops cells the header does not name and the param would otherwise silently
vanish.

</details>

<details>
<summary><b>Hover</b></summary>

A keyword's real signature and the framework's own docstring, which is where the accepted
values are actually written:

```
Press Element(element, repeat='1', offset_x='0', offset_y='0', index='0',
              aoi_x='0', aoi_y='0', aoi_width='100', aoi_height='100', event_name=None)

Press a specified element.

:param element: The element to be pressed (text, xpath or image).
:param repeat: Number of times to repeat the press.
:param index: Index of the element if multiple matches are found.
:param aoi_width: Width percentage of Area of Interest (0-100). Default: 100.
```

Defaults are rendered as `name='value'`, so what an omitted cell falls back to is visible
without reading the source.

</details>

<details>
<summary><b>Signature help</b></summary>

The keyword's params with the column you are in marked active, retriggering on every comma,
which is how you tell param 4 from param 5 in a row of commas.

</details>

<details>
<summary><b>Goto definition</b></summary>

From a step to the module it runs, or from a `${ref}` to the elements it reads. Every `${name}`
in the cell is offered, not just one: a fallback element is several rows, and so is
`${a} == ${b}`.

Two details it gets right. A `module_step` naming something that is *also* a keyword resolves
to the keyword, so a same-named module is not offered, mirroring what the runner does. And
`Condition`'s `!Name` inversion is stripped the same way the runner strips it.

</details>

<details>
<summary><b>Find references</b></summary>

Every place a name is used across the project, optionally including where it is bound. Works
on test cases, modules, elements and error codes, the things the project owns. A keyword
belongs to the framework, and an image, data file or API identifier names something outside
the CSVs, so neither comes back from here.

</details>

<details>
<summary><b>Rename</b></summary>

Renames across every file that writes the name, with prepare-rename so the client can reject
an invalid position before you start typing. This is the feature that most needs to be
project-wide: the runner keys everything by name, so a rename that misses one cell quietly
changes what runs instead of failing loudly.

</details>

<details>
<summary><b>Document symbols</b></summary>

One file's outline: what it defines, and the rows making each one up:

```
Open App          [Function]  2 steps
    Launch App    [Method]
    Sleep         [Method]    2
Login             [Function]  1 step
    Press Element [Method]    ${btn}
```

</details>

<details>
<summary><b>Semantic tokens</b></summary>

Highlighting a CSV grammar cannot express, because the meaning of a cell depends on the column
above it and on the rest of the project:

| token | what it marks |
| --- | --- |
| `keyword` | the header row, the names that decide what the file is |
| `class` | a test case |
| `function` | a module, wherever it is named |
| `method` | a step that resolves to a framework keyword |
| `variable` | `${name}`, and an `element_name` that defines one |
| `string` | a locator, a data file, an API identifier |
| `enumMember` | an error code, and a param with a documented set of values |
| `operator` | the `!` that inverts a `Condition` |

A framework keyword also carries the `defaultLibrary` modifier, so themes colour it apart from
a module of the same shape, which they would otherwise draw identically.

</details>

---

## The keyword catalog

`src/optics_framework_lsp/keywords.py` is generated and holds **49 keywords from
optics-framework 1.9.3**: each one's params, which are required, the defaults, and the
framework's own docstring, which is where hover text and the param values come from.

It is compiled in rather than read from your environment. Importing `optics_framework.api.*`
pulls numpy, cv2, pandas and skimage through `common.optics_builder`, needing a 342 MB install
and failing outright if any one of those is broken, leaving a project with no keyword
diagnostics at all and no explanation why.

To refresh it for a new optics release:

```sh
python scripts/update_catalog.py ~/src/optics-framework
python scripts/update_catalog.py --check    # exits 1 if the committed table is stale
```

Signatures are read with `ast`, never imported, which is what lets the script run against a
bare checkout or a `--no-deps` install and makes it usable for diffing two releases. It refuses
to run if one of the four API classes gains a base class, since that would mean keywords it
cannot see. A test runs `--check`, so a stale table fails the suite.

## Development

```sh
uv run pytest tests/ -q
```

One test needs optics-framework itself and skips without it; point `OPTICS_PROBE_VENV` at a
virtualenv that has it to run that one.

The engine is deliberately protocol-free. `validate()` returns plain `Finding` objects and each
transport converts at its own boundary: `server.py` to `lsprotocol` diagnostics, `lint.py` to
JSON. `import lsprotocol.types` alone costs ~290 ms, which a long-lived server pays once and a
per-call command would pay every time. `tests/test_lint.py` asserts the lint path imports
neither pygls nor lsprotocol, so it stays that way.

## License

Apache 2.0.
