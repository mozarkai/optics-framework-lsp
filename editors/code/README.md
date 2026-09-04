# Optics Framework

Diagnostics, completion, hover, goto-definition, references, rename, workspace symbol search
and semantic highlighting for
[optics-framework](https://github.com/mozarkai/optics-framework) CSV test suites, powered
by [`optics-framework-lsp`](https://github.com/mozarkai/optics-framework-lsp).

Everything is project-wide: a name defined in one CSV resolves references in every other file
in the workspace, so completion, goto-definition and rename all work across files, not just
within one.

## Requirements

- VS Code 1.101 or newer, for the MCP API below.
- The [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python),
  with an interpreter selected (Python 3.12+).

No other install step: the language server's own pure-Python dependencies ship inside this
extension.

The server attaches to every `*.csv` file in the workspace. Files that are not optics suites
produce no diagnostics, because the parser classifies each file by its header row.

## AI agents

The extension registers the server as an MCP server too, so an AI agent can ask it the same
questions the editor does, across the whole project rather than only the open files. It appears
under **MCP Servers** with nothing to configure.

The bridge is [`mcpls`](https://github.com/bug-ops/mcpls), downloaded the first time an agent
starts the server. Set `optics.mcp.binaryPath` to use your own copy and nothing is fetched.

Copilot reads this automatically. Claude Code and Cursor keep their own MCP config, so those
need the binary registered with them directly.

## Settings

| setting | default | |
|---|---|---|
| `optics.server.pythonCommand` | unset | override the interpreter the Python extension selects |
| `optics.trace.server` | `"off"` | log LSP traffic to the "Optics" output channel |
| `optics.mcp.enabled` | `true` | offer the server to AI agents over MCP |
| `optics.mcp.binaryPath` | unset | use this `mcpls` binary rather than downloading one |

## Commands

- **Optics: Restart Language Server**

## License

Apache-2.0
