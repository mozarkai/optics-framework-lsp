---
name: optics-framework
description: Read the optics-framework documentation before answering about its keywords, and use the optics MCP tools for the CSV suites in this project. Use when working with optics-framework CSV test suites (test_cases, modules, elements, error_definitions) or when a keyword name, parameter or default is uncertain.
license: Apache-2.0
---

# optics-framework

optics-framework is newer than your training data. Do not guess at keyword names, parameters or
defaults — look them up.

## Documentation

- Keyword reference: https://mozarkai.github.io/optics-framework/api_reference/action_keywords/
- Full documentation: https://mozarkai.github.io/optics-framework/

## What a suite is

A suite is CSV files, classified by their **header row** rather than their filename:

| header | what the file holds |
| --- | --- |
| `test_case,test_step` | test cases, each a list of modules to run |
| `module_name,module_step` | modules, each a list of keywords or other modules |
| `element_name,element_id` | elements, each one or more locators tried in order |
| `error_code,match_string` | error definitions |

A CSV matching none of those is ignored by the framework, so it is not a clean file — it is an
unread one.

Every name resolves project-wide: a module defined in one file is callable from any other, and a
rename that misses one cell changes what runs instead of failing loudly.

## Answering questions about a suite

The `optics` MCP server exposes this project's language server, which knows every module, element,
error code and keyword signature in the project. Prefer it over reading the CSVs by hand, and
prefer it over recalling the framework from memory.
