# Optics Framework — JetBrains plugin

Wraps [`optics-framework-lsp`](../../README.md) as a plugin for IntelliJ-based IDEs, using the
platform's own LSP client.

## Requirements

Python 3.12 or newer, either on `PATH` or set under **Settings | Tools | Optics Framework**. The
server's dependencies ship inside the plugin, so there is nothing to `pip install`.

An IDE from **2026.1.4** onward. The plugin declares an optional dependency on
`com.intellij.modules.lsp`, which every unified JetBrains IDE has, free tier included. On an IDE
without it (Android Studio) the plugin installs and contributes nothing rather than failing to load.

## Why the floor is 2026.1.4

The server speaks sixteen standard LSP methods, but the platform's LSP client grew into them over
several releases. Anything below the floor does not degrade visibly — the feature is simply never
requested, and the server sits there answering nobody. From
[the SDK docs](https://plugins.jetbrains.com/docs/intellij/language-server-protocol.html):

| feature | LSP method | client asks for it since |
|---|---|---|
| Diagnostics, completion, goto-declaration | `publishDiagnostics`, `completion`, `definition` | 2023.2 |
| Quick documentation | `hover` | 2023.3.2 |
| Find usages | `references` | 2024.2 |
| Semantic highlighting | `semanticTokens/full` | 2024.2.2 |
| Structure, breadcrumbs, go-to-symbol | `documentSymbol` | 2025.3 |
| Go to symbol across the project | `workspace/symbol` | 2025.3 |
| Parameter info | `signatureHelp` | 2025.3 |
| Rename refactoring | `rename`, `prepareRename` | **2026.1.1** (261.23567.138) |

Rename is the last one to arrive, so 2026.1.1 is the first build where every method this server
implements is actually used. The floor is one step higher still, at **2026.1.4** (261.26222.65),
because that is where the un-deprecated client API landed — `LspIntegrationProvider`,
`ProjectWideLspClientDescriptor`, `LspClientManager`. Supporting anything older would mean writing
against the deprecated `Lsp*Server*` names for no feature gain.

Note the build numbers rather than a bare `261`: 2026.1 itself is 261.22158.277 and has neither.

## Building

`bundled/libs` is produced once for every editor client and is not checked in:

```
make -C .. bundled/libs/.installed
./gradlew buildPlugin        # -> build/distributions/optics-framework-lsp-1.0.0.zip
./gradlew check              # the smoke test: spawns the real server over stdio
./gradlew verifyPlugin       # checks the plugin loads across IDEs, including LSP-less ones
./gradlew runIde             # a sandbox IDE with the plugin installed
```

## How it attaches to files

`isSupportedFile` matches every `*.csv`. No `FileType` or `Language` is declared, so the CSV editor
you already use is untouched. Files that are not optics suites produce nothing, because the server
classifies each one by its header row.
