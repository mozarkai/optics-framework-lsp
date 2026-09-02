# Optics Framework

Diagnostics, completion, hover, goto-definition, references, rename, workspace symbol search
and semantic highlighting for
[optics-framework](https://github.com/mozarkai/optics-framework) CSV test suites, powered
by [`optics-framework-lsp`](https://github.com/mozarkai/optics-framework-lsp).

Everything is project-wide: a name defined in one CSV resolves references in every other file
in the workspace, so completion, goto-definition and rename all work across files, not just
within one.

## Requirements

- The [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python),
  with an interpreter selected (Python 3.12+).

No other install step: the language server's own pure-Python dependencies ship inside this
extension.

The server attaches to every `*.csv` file in the workspace. Files that are not optics suites
produce no diagnostics, because the parser classifies each file by its header row.

## Settings

| setting | default | |
|---|---|---|
| `optics.server.pythonCommand` | unset | override the interpreter the Python extension selects |
| `optics.trace.server` | `"off"` | log LSP traffic to the "Optics" output channel |

## Commands

- **Optics: Restart Language Server**

## License

Apache-2.0
