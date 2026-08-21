# Diagnostics for optics-framework workspaces. One workspace folder = one project.

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from sys import addaudithook

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import completion, keyword_catalog
from .parser.csv_parser import parse_csv_sources
from .validation import validate


class OpticsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("optics-lsp", "0.1.0")
        # Files we last published to per folder, so fixed problems clear in the editor
        # without one folder wiping another's diagnostics.
        self._published: defaultdict[str, set[str]] = defaultdict(set)
        self._catalogs: dict[str, keyword_catalog.Catalog | None] = {}

    def folder_of(self, uri: str) -> str | None:
        return next((f for f in self.workspace.folders if uri.startswith(f)), None)

    def sources(self, folder_uri: str) -> list[tuple[str, str]]:
        """Every csv in the folder, with open buffers overriding what is on disk."""
        root = to_fs_path(folder_uri)
        if root is None:
            return []

        sources = []
        for parent, folders, files in Path(root).walk():
            # Never descend into .venv or .git: optics-framework ships sample csvs of its
            # own, and parsing those would invent modules and elements the project lacks.
            folders[:] = sorted(f for f in folders if not f.startswith("."))

            for name in sorted(f for f in files if f.endswith(".csv")):
                uri = (parent / name).as_uri()
                document = self.workspace.text_documents.get(uri)
                sources.append(
                    (
                        uri,
                        document.source
                        if document
                        else (parent / name).read_text(errors="replace"),
                    )
                )
        return sources

    def validate_folder(self, folder_uri: str) -> None:
        found = validate(
            parse_csv_sources(self.sources(folder_uri)),
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

        root = to_fs_path(folder)
        if root is not None:
            ls._catalogs[folder] = await keyword_catalog.load(Path(root))
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

    return completion.complete(
        ls.workspace.get_text_document(uri).source,
        params.position,
        parse_csv_sources(ls.sources(folder)),
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
