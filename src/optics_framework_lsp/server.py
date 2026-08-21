# Diagnostics for optics-framework workspaces. One workspace folder = one project.

from __future__ import annotations

from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import keyword_catalog
from .parser.csv_parser import parse_csv_sources
from .validation import validate


class OpticsLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("optics-lsp", "0.1.0")
        # Files we last published to, so cleared problems can be cleared in the editor.
        self._published: set[str] = set()
        self._catalogs: dict[str, keyword_catalog.Catalog | None] = {}

    def folder_of(self, uri: str) -> str | None:
        return next((f for f in self.workspace.folders if uri.startswith(f)), None)

    def sources(self, folder_uri: str) -> list[tuple[str, str]]:
        """Every csv in the folder, with open buffers overriding what is on disk."""
        root = to_fs_path(folder_uri)
        if root is None:
            return []

        sources = []
        for path in sorted(Path(root).rglob("*.csv")):
            uri = path.as_uri()
            document = self.workspace.text_documents.get(uri)
            sources.append(
                (uri, document.source if document else path.read_text(errors="replace"))
            )
        return sources

    def validate_folder(self, folder_uri: str) -> None:
        found = validate(
            parse_csv_sources(self.sources(folder_uri)),
            self._catalogs.get(folder_uri),
        )

        for uri in self._published - found.keys():
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )

        for uri, diagnostics in found.items():
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
            )

        self._published = set(found)


server = OpticsLanguageServer()


@server.feature(types.INITIALIZED)
async def initialized(ls: OpticsLanguageServer, params: types.InitializedParams) -> None:
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


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: OpticsLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    # The buffer is gone, so fall back to what is on disk.
    _revalidate(ls, params.text_document.uri)
