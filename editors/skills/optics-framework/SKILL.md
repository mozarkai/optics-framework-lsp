---
name: optics-framework
description: Read the optics-framework documentation before answering about its keywords, and use the optics MCP tools for the test suites in this project. Use when working with optics-framework CSV or YAML test suites (test_cases, modules, elements, error_definitions) or when a keyword name, parameter or default is uncertain.
license: Apache-2.0
---

# optics-framework

optics-framework is newer than your training data. Do not guess at keyword names, parameters or
defaults — look them up.

## Documentation

- Keyword reference: https://mozarkai.github.io/optics-framework/api_reference/action_keywords/
- Full documentation: https://mozarkai.github.io/optics-framework/

## What a suite is

A suite is CSV or YAML files, classified by their **contents** rather than their filename. A
project may mix both, and names resolve across them.

A CSV is classified by its header row:

| header | what the file holds |
| --- | --- |
| `test_case,test_step` | test cases, each a list of modules to run |
| `module_name,module_step` | modules, each a list of keywords or other modules |
| `element_name,element_id` | elements, each one or more locators tried in order |
| `error_code,match_string` | error definitions |

A YAML is classified by its top-level keys, and one file may hold all three:

```yaml
Test Cases:                 # a list of single-key mappings
  - Add Contact:
      - Launch Contact App  # module names, never keywords
Modules:                    # a list of single-key mappings
  - Launch Contact App:
      - Launch App          # one string: the keyword, then its params
      - Enter Text ${field} John
Elements:                   # a plain mapping, not a list
  field: '//input[@id="name"]'
  save_button:              # a list is the fallback chain, tried in order
    - '//button[@id="save"]'
    - Save
```

A file matching none of those is ignored by the framework, so it is not a clean file — it is an
unread one.

Every name resolves project-wide: a module defined in one file is callable from any other,
whatever format either is in, and a rename that misses one cell changes what runs instead of
failing loudly.

## Writing YAML, and its three traps

YAML is a real peer of CSV at run time, but it is undocumented, no sample ships in one, and
`optics init` never writes one. Prefer CSV unless the project is already YAML. If you do write
YAML, these three all fail *silently* — the reader logs and carries on with an empty section, so
the run fails somewhere that says nothing about the cause:

1. **A param holding a space has to be quoted.** The params are whitespace-split after YAML
   quoting is gone, so `Enter Text ${f} hello world` passes three params, not two. Write
   `text="hello world"`, which the reader unwraps back to one. The quotes inside a locator
   (`//button[@id="save"]`) are not around the whole value, so they stay.
2. **Section keys are read with the case intact** — exactly `Test Cases`, `Modules`, `Elements`.
   Writing `test_cases:` still gets the file classified as test cases, and then read as empty.
3. **`Test Cases` and `Modules` must be lists of single-key mappings.** Written as a plain
   mapping, the load dies with `AttributeError: 'str' object has no attribute 'items'`.

One further limit: **error definitions have no YAML form at all** — they must be a CSV.

A step's keyword name ends where the keyword catalogue says it does, so a literal first param
needs no `${...}` to be seen as a param: `Sleep 5` is the keyword `Sleep`. A module whose name
starts with a keyword's, like `Sleep Well`, is still read as the module.

## Answering questions about a suite

The `optics` MCP server exposes this project's language server, which knows every module, element,
error code and keyword signature in the project, in both formats. It reports each of the traps
above. Prefer it over reading the files by hand, and prefer it over recalling the framework from
memory.
