# Diagnostics for optics-framework workspaces. One workspace folder = one project.

from __future__ import annotations

from collections import defaultdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import yaml
from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import completion
from .parser.ast import AST
from .keyword_catalog import CATALOG
from .parser.csv_parser import parse_csv_sources
from . import rename as renaming
from .symbols import symbols
from .tokens import LEGEND, MODIFIERS, tokens
from .validation import Finding, SOURCE, validate


# What `_load_file_data` can parse.
_DATA = {".csv", ".json"}
_YAML = {".yaml", ".yml"}


def images(files: list[Path]) -> list[str]:
    """Templates are matched by bare filename, wherever they sit in the project."""
    return sorted({p.name for p in files if p.suffix.lower() in completion.IMAGE_SUFFIXES})


def apis(files: list[Path]) -> list[str]:
    """`collection.api` identifiers, as `invoke_api` splits them."""
    found = []
    for path in files:
        if path.suffix.lower() not in _YAML:
            continue

        try:
            data = yaml.safe_load(path.read_text(errors="replace"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue

        # The reader unwraps a top-level `api` key, or takes the whole document.
        api = data.get("api", data)
        collections = api.get("collections") if isinstance(api, dict) else None

        for name, collection in (collections or {}).items():
            defined = collection.get("apis") if isinstance(collection, dict) else None
            found.extend(f"{name}.{api_name}" for api_name in defined or {})
    return sorted(found)


def data_files(root: str | None, files: list[Path], ast: AST) -> list[str]:
    """What `Read Data` can read: a project-relative csv or json that is not ours."""
    ours = {b.uri for b in [*ast.test_cases, *ast.modules]} | {
        e.uri for e in [*ast.elements, *ast.error_definitions]
    }
    return sorted(
        str(path.relative_to(root))
        for path in files
        if root and path.suffix.lower() in _DATA and path.as_uri() not in ours
    )


def _range(finding: Finding, lines: list[str]) -> types.Range:
    """The finding's whole row. Ending at the next line's start is past EOF on the last row,
    and IntelliJ refuses to annotate a range outside the document."""
    line = min(finding.line, max(len(lines) - 1, 0))
    return types.Range(
        start=types.Position(line=line, character=0),
        end=types.Position(line=line, character=len(lines[line]) if lines else 0),
    )


def _diagnostic(finding: Finding, lines: list[str]) -> types.Diagnostic:
    """A `Finding` on the wire. The engine stays protocol-free; the range is built here."""
    return types.Diagnostic(
        range=_range(finding, lines),
        message=finding.message,
        severity=types.DiagnosticSeverity(finding.severity),
        code=finding.code,
        source=SOURCE,
    )


# Read from the package rather than keeping a fourth copy of the version.
try:
    _VERSION = version("optics-framework-lsp")
except PackageNotFoundError:  # pragma: no cover - only when run from a bare source tree
    _VERSION = "0+unknown"


class OpticsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("optics-lsp", _VERSION)
        # Files we last published to per folder, so fixed problems clear in the editor
        # without one folder wiping another's diagnostics.
        self._published: defaultdict[str, set[str]] = defaultdict(set)

    def folder_of(self, uri: str) -> str | None:
        return next((f for f in self.workspace.folders if uri.startswith(f)), None)

    def files(self, folder_uri: str) -> list[Path]:
        root = to_fs_path(folder_uri)
        if root is None:
            return []

        found = []
        for parent, folders, files in Path(root).walk():
            # Never descend into .venv or .git: optics-framework ships sample csvs and
            # images of its own, which would invent names the project does not have.
            folders[:] = sorted(f for f in folders if not f.startswith("."))
            found.extend(parent / name for name in sorted(files))
        return found

    def sources(self, files: list[Path]) -> list[tuple[str, str]]:
        """Every csv among `files`, with open buffers overriding what is on disk."""
        return [(uri, text) for uri, text, _ in self.snapshot(files)]

    def snapshot(self, files: list[Path]) -> list[tuple[str, str, int | None]]:
        """As `sources`, plus each text's document version — captured together, or a client
        cannot tell a stale publish from a fresh one."""
        snapshot = []
        for path in files:
            if path.suffix != ".csv":
                continue

            uri = path.as_uri()
            document = self.workspace.text_documents.get(uri)
            if document is None:
                snapshot.append((uri, path.read_text(errors="replace"), None))
            else:
                snapshot.append((uri, document.source, document.version))
        return snapshot

    def validate_folder(self, folder_uri: str) -> None:
        snapshot = {uri: (text, v) for uri, text, v in self.snapshot(self.files(folder_uri))}
        found = validate(
            parse_csv_sources([(uri, text) for uri, (text, _) in snapshot.items()]),
            CATALOG,
        )

        for uri in self._published[folder_uri] - found.keys():
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(
                    uri=uri, diagnostics=[], version=snapshot.get(uri, (None, None))[1]
                )
            )

        for uri, findings in found.items():
            text, version = snapshot.get(uri, ("", None))
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(
                    uri=uri,
                    diagnostics=[_diagnostic(f, text.splitlines()) for f in findings],
                    version=version,
                )
            )

        self._published[folder_uri] = set(found)


server = OpticsLanguageServer()


@server.feature(types.INITIALIZED)
async def initialized(ls: OpticsLanguageServer, params: types.InitializedParams) -> None:
    # Ask the client to watch for edits made outside the editor, such as a git checkout.
    # File watching has no static capability, so it can only be requested here, and only
    # from clients that offered to do it.
    watching = getattr(ls.client_capabilities.workspace, "did_change_watched_files", None)
    if watching and watching.dynamic_registration:
        ls.client_register_capability(
            types.RegistrationParams(
                registrations=[
                    types.Registration(
                        id="optics-csv-watcher",
                        method=types.WORKSPACE_DID_CHANGE_WATCHED_FILES,
                        register_options=types.DidChangeWatchedFilesRegistrationOptions(
                            watchers=[types.FileSystemWatcher(glob_pattern="**/*.csv")]
                        ),
                    )
                ]
            )
        )

    for folder in ls.workspace.folders:
        ls.validate_folder(folder)


def _revalidate(ls: OpticsLanguageServer, uri: str) -> None:
    # Cross-file rules mean one edit can change diagnostics anywhere in the project.
    if folder := ls.folder_of(uri):
        ls.validate_folder(folder)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: OpticsLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    _revalidate(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: OpticsLanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    _revalidate(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: OpticsLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    _revalidate(ls, params.text_document.uri)


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(
    ls: OpticsLanguageServer, params: types.DidChangeWatchedFilesParams
) -> None:
    for folder in {f for c in params.changes if (f := ls.folder_of(c.uri))}:
        ls.validate_folder(folder)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: OpticsLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    # The buffer is gone, so fall back to what is on disk.
    _revalidate(ls, params.text_document.uri)


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=[",", "{"]),
)
def completions(
    ls: OpticsLanguageServer, params: types.CompletionParams
) -> list[types.CompletionItem]:
    uri = params.text_document.uri
    folder = ls.folder_of(uri)
    if folder is None:
        return []

    files = ls.files(folder)
    ast = parse_csv_sources(ls.sources(files))
    return completion.complete(
        ls.workspace.get_text_document(uri).source,
        params.position,
        ast,
        CATALOG,
        images=images(files),
        data_files=data_files(to_fs_path(folder), files, ast),
        apis=apis(files),
    )


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    types.SemanticTokensLegend(token_types=LEGEND, token_modifiers=MODIFIERS),
)
def semantic_tokens(
    ls: OpticsLanguageServer, params: types.SemanticTokensParams
) -> types.SemanticTokens:
    uri = params.text_document.uri
    folder = ls.folder_of(uri)
    if folder is None:
        return types.SemanticTokens(data=[])

    # Which names are modules is a whole-project question, as it is for references.
    source = ls.workspace.get_text_document(uri).source
    ast = parse_csv_sources(ls.sources(ls.files(folder)))
    return types.SemanticTokens(data=tokens(source, ast, CATALOG))


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbols(
    ls: OpticsLanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol]:
    # One file's outline, so the rest of the workspace is not parsed.
    uri = params.text_document.uri
    return symbols(parse_csv_sources([(uri, ls.workspace.get_text_document(uri).source)]))


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: OpticsLanguageServer, params: types.HoverParams) -> types.Hover | None:
    folder = ls.folder_of(params.text_document.uri)
    if folder is None:
        return None

    # Only the catalog is needed here, so the workspace is not re-parsed.
    return completion.hover(
        ls.workspace.get_text_document(params.text_document.uri).source,
        params.position,
        CATALOG,
    )


@server.feature(types.TEXT_DOCUMENT_RENAME, types.RenameOptions(prepare_provider=True))
def rename(ls: OpticsLanguageServer, params: types.RenameParams) -> types.WorkspaceEdit | None:
    uri = params.text_document.uri
    folder = ls.folder_of(uri)
    if folder is None:
        return None

    # Every file, because the runner keys by name and a missed cell changes what runs.
    edits = renaming.rename(
        ls.sources(ls.files(folder)),
        CATALOG,
        ls.workspace.get_text_document(uri).source,
        params.position,
        params.new_name,
    )
    return types.WorkspaceEdit(changes=edits) if edits else None


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(
    ls: OpticsLanguageServer, params: types.PrepareRenameParams
) -> types.Range | None:
    folder = ls.folder_of(params.text_document.uri)
    return renaming.prepare(
        ls.workspace.get_text_document(params.text_document.uri).source,
        params.position,
        CATALOG,
    )


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references(
    ls: OpticsLanguageServer, params: types.ReferenceParams
) -> list[types.Location]:
    uri = params.text_document.uri
    folder = ls.folder_of(uri)
    if folder is None:
        return []

    ast = parse_csv_sources(ls.sources(ls.files(folder)))
    return completion.references(
        ls.workspace.get_text_document(uri).source,
        params.position,
        ast,
        CATALOG,
        include_declaration=params.context.include_declaration,
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(
    ls: OpticsLanguageServer, params: types.DefinitionParams
) -> list[types.Location]:
    uri = params.text_document.uri
    folder = ls.folder_of(uri)
    if folder is None:
        return []

    ast = parse_csv_sources(ls.sources(ls.files(folder)))
    return completion.definition(
        ls.workspace.get_text_document(uri).source,
        params.position,
        ast,
        CATALOG,
    )


@server.feature(
    types.TEXT_DOCUMENT_SIGNATURE_HELP,
    types.SignatureHelpOptions(trigger_characters=[","], retrigger_characters=[","]),
)
def signature_help(
    ls: OpticsLanguageServer, params: types.SignatureHelpParams
) -> types.SignatureHelp | None:
    folder = ls.folder_of(params.text_document.uri)
    if folder is None:
        return None

    # Only the catalog is needed here, so the workspace is not re-parsed.
    return completion.signature(
        ls.workspace.get_text_document(params.text_document.uri).source,
        params.position,
        CATALOG,
    )
