# Diagnostics for optics-framework workspaces. One workspace folder = one project.

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from sys import addaudithook

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from . import completion, keyword_catalog
from .parser.ast import AST
from .parser.csv_parser import parse_csv_sources
from .validation import validate


# Only these classify as Image in `determine_element_type` (.tiff discovers but never matches).
_IMAGES = {".png", ".jpg", ".jpeg", ".bmp"}
# What `_load_file_data` can parse.
_DATA = {".csv", ".json"}


def images(files: list[Path]) -> list[str]:
    """Templates are matched by bare filename, wherever they sit in the project."""
    return sorted({p.name for p in files if p.suffix.lower() in _IMAGES})


def data_files(root: str | None, files: list[Path], ast: AST) -> list[str]:
    """What `Read Data` can read: a project-relative csv or json that is not ours."""
    ours = {b.uri for b in [*ast.test_cases, *ast.modules]} | {e.uri for e in ast.elements}
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

    files = ls.files(folder)
    ast = parse_csv_sources(ls.sources(files))
    return completion.complete(
        ls.workspace.get_text_document(uri).source,
        params.position,
        ast,
        ls._catalogs.get(folder),
        images(files),
        data_files(to_fs_path(folder), files, ast),
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
