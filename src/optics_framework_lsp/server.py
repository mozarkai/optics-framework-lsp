# Diagnostics for optics-framework workspaces. One workspace folder = one project.

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml
from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import completion, keyword_catalog
from .parser.ast import AST
from .parser.csv_parser import parse_csv_sources
from .symbols import symbols
from .tokens import LEGEND, MODIFIERS, tokens
from .validation import validate


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


class OpticsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("optics-lsp", "0.1.0")
        # Files we last published to per folder, so fixed problems clear in the editor
        # without one folder wiping another's diagnostics.
        self._published: defaultdict[str, set[str]] = defaultdict(set)
        self._catalogs: dict[str, keyword_catalog.Catalog | None] = {}
        # The install each catalog was read from, so `pip install` is picked up.
        self._probed: dict[str, tuple[str, float] | None] = {}

    def refreshes_tokens(self) -> bool:
        """Whether the client asked to be told when tokens go stale. `getattr` because
        there are no capabilities before initialize, which is how a test drives us."""
        capabilities = getattr(self, "client_capabilities", None)
        workspace = getattr(capabilities, "workspace", None)
        return bool(getattr(workspace, "semantic_tokens", None))

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
        sources = []
        for path in files:
            if path.suffix != ".csv":
                continue

            uri = path.as_uri()
            document = self.workspace.text_documents.get(uri)
            sources.append(
                (uri, document.source if document else path.read_text(errors="replace"))
            )
        return sources

    async def sync_catalog(self, folder_uri: str) -> None:
        """Read the keyword catalog if the project's optics install has changed."""
        root = to_fs_path(folder_uri)
        if root is None:
            return

        marker = keyword_catalog.installed_at(Path(root))
        if folder_uri in self._catalogs and marker == self._probed.get(folder_uri):
            return

        # Recorded before the await, so keystrokes during a probe do not stack.
        self._probed[folder_uri] = marker
        self._catalogs[folder_uri] = await keyword_catalog.load(Path(root))

        # Semantic tokens are pulled once and cached until the buffer changes, so a
        # catalog arriving after the first pull needs a nudge, or every keyword stays
        # coloured as a module.
        if self._catalogs[folder_uri] and self.refreshes_tokens():
            self.workspace_semantic_tokens_refresh(None)

    def validate_folder(self, folder_uri: str) -> None:
        found = validate(
            parse_csv_sources(self.sources(self.files(folder_uri))),
            self._catalogs.get(folder_uri),
        )

        for uri in self._published[folder_uri] - found.keys():
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )

        for uri, diagnostics in found.items():
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
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
        # Structural problems first; keyword ones follow once the catalog is read.
        ls.validate_folder(folder)
        await ls.sync_catalog(folder)
        ls.validate_folder(folder)


async def _revalidate(ls: OpticsLanguageServer, uri: str) -> None:
    # Cross-file rules mean one edit can change diagnostics anywhere in the project.
    if folder := ls.folder_of(uri):
        await ls.sync_catalog(folder)
        ls.validate_folder(folder)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def did_open(ls: OpticsLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    await _revalidate(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: OpticsLanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    await _revalidate(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def did_save(ls: OpticsLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    await _revalidate(ls, params.text_document.uri)


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
async def did_change_watched_files(
    ls: OpticsLanguageServer, params: types.DidChangeWatchedFilesParams
) -> None:
    for folder in {f for c in params.changes if (f := ls.folder_of(c.uri))}:
        await ls.sync_catalog(folder)
        ls.validate_folder(folder)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
async def did_close(ls: OpticsLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    # The buffer is gone, so fall back to what is on disk.
    await _revalidate(ls, params.text_document.uri)


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
        ls._catalogs.get(folder),
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
    return types.SemanticTokens(data=tokens(source, ast, ls._catalogs.get(folder)))


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
        ls._catalogs.get(folder),
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
        ls._catalogs.get(folder),
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
        ls._catalogs.get(folder),
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
        ls._catalogs.get(folder),
    )
