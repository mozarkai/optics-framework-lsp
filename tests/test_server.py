import asyncio
import sys

import pytest
import pytest_lsp
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

WORKSPACE = {
    "tests/test_cases.csv": "test_case,test_step\nTC,Login\nTC,Gone\n",
    "modules/modules.csv": "module_name,module_step,param_1\nLogin,Press Element,${btn}\n",
    "data/elements.csv": "element_name,element_id\nbtn,//a\n",
}


async def codes_for(client, uri, expected, timeout=5):
    """Poll until the published codes match; diagnostics can arrive before we look."""
    async with asyncio.timeout(timeout):
        while True:
            diagnostics = client.diagnostics.get(uri) or []
            if [d.code for d in diagnostics] == expected:
                return diagnostics
            await asyncio.sleep(0.05)


def edit(client, uri, version, text):
    client.text_document_did_change(
        types.DidChangeTextDocumentParams(
            text_document=types.VersionedTextDocumentIdentifier(uri=uri, version=version),
            content_changes=[types.TextDocumentContentChangeWholeDocument(text=text)],
        )
    )


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("project")
    for name, content in WORKSPACE.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "optics_framework_lsp.cli"]
    ),
)
async def client(lsp_client: LanguageClient, workspace):
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            workspace_folders=[
                types.WorkspaceFolder(uri=workspace.as_uri(), name="project")
            ],
        )
    )
    yield
    await lsp_client.shutdown_session()


async def test_diagnostics_on_startup(client: LanguageClient, workspace):
    uri = (workspace / "tests/test_cases.csv").as_uri()
    (diagnostic,) = await codes_for(client, uri, ["module-not-found"])

    assert diagnostic.range.start.line == 2
    assert "Gone" in diagnostic.message
    assert diagnostic.source == "optics"


async def test_semantic_tokens_over_lsp(client: LanguageClient, workspace):
    """The legend is advertised and the encoding survives the trip."""
    found = await client.text_document_semantic_tokens_full_async(
        types.SemanticTokensParams(
            text_document=types.TextDocumentIdentifier(
                uri=(workspace / "modules/modules.csv").as_uri()
            )
        )
    )
    # Five ints per token, and the first is the header cell at line 0, character 0.
    assert len(found.data) % 5 == 0
    assert list(found.data[:3]) == [0, 0, len("module_name")]


async def test_references_over_lsp(client: LanguageClient, workspace):
    """A module's callers, found in a file the client never opened."""
    found = await client.text_document_references_async(
        types.ReferenceParams(
            text_document=types.TextDocumentIdentifier(
                uri=(workspace / "modules/modules.csv").as_uri()
            ),
            position=types.Position(line=1, character=3),
            context=types.ReferenceContext(include_declaration=False),
        )
    )
    (use,) = found
    assert use.uri == (workspace / "tests/test_cases.csv").as_uri()
    assert use.range.start.line == 1


async def test_document_symbols_over_lsp(client: LanguageClient, workspace):
    """An outline of a file the client never opened, so it comes off disk."""
    found = await client.text_document_document_symbol_async(
        types.DocumentSymbolParams(
            text_document=types.TextDocumentIdentifier(
                uri=(workspace / "modules/modules.csv").as_uri()
            )
        )
    )
    (symbol,) = found
    assert (symbol.name, symbol.kind) == ("Login", types.SymbolKind.Function)
    # Children survive the trip: a client renders them as a tree.
    assert [c.name for c in symbol.children] == ["Press Element"]
    # Children survive the trip: a client renders them as a tree.
    assert [c.name for c in symbol.children] == ["Press Element"]


async def test_goto_definition_over_lsp(client: LanguageClient, workspace):
    """A test step jumps to the module, in another file, without the buffer being open."""
    found = await client.text_document_definition_async(
        types.DefinitionParams(
            text_document=types.TextDocumentIdentifier(
                uri=(workspace / "tests/test_cases.csv").as_uri()
            ),
            position=types.Position(line=1, character=5),
        )
    )
    (location,) = found
    assert location.uri == (workspace / "modules/modules.csv").as_uri()
    assert location.range.start.line == 1


async def test_unsaved_edits_are_validated_and_cleared(client: LanguageClient, workspace):
    path = workspace / "modules/modules.csv"
    uri = path.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            types.TextDocumentItem(
                uri=uri, language_id="csv", version=1, text=path.read_text()
            )
        )
    )
    await codes_for(client, uri, [])

    edit(client, uri, 2, "module_name,module_step,param_1\nLogin,Press Element,${nope}\n")
    await codes_for(client, uri, ["element-not-found"])

    edit(client, uri, 3, "module_name,module_step,param_1\nLogin,Press Element,${btn}\n")
    await codes_for(client, uri, [])


@pytest.fixture
def two_projects(tmp_path):
    for name in ("alpha", "beta"):
        path = tmp_path / name / "tests"
        path.mkdir(parents=True)
        (path / "test_cases.csv").write_text("test_case,test_step\nTC,Missing\n")
    return tmp_path / "alpha", tmp_path / "beta"


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "optics_framework_lsp.cli"]
    ),
)
async def multi_client(lsp_client: LanguageClient, two_projects):
    alpha, beta = two_projects
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            workspace_folders=[
                types.WorkspaceFolder(uri=alpha.as_uri(), name="alpha"),
                types.WorkspaceFolder(uri=beta.as_uri(), name="beta"),
            ],
        )
    )
    yield
    await lsp_client.shutdown_session()


async def test_folders_keep_their_own_diagnostics(multi_client, two_projects):
    alpha, beta = two_projects

    # Waiting on the folder validated last means the first one has settled.
    await codes_for(multi_client, (beta / "tests/test_cases.csv").as_uri(), ["module-not-found"])
    await asyncio.sleep(0.2)

    alpha_uri = (alpha / "tests/test_cases.csv").as_uri()
    assert [d.code for d in multi_client.diagnostics.get(alpha_uri) or []] == [
        "module-not-found"
    ]


async def test_disk_change_refreshes_diagnostics(client: LanguageClient, workspace):
    """A watched-file notification stands in for a git checkout or external edit."""
    uri = (workspace / "tests/test_cases.csv").as_uri()
    await codes_for(client, uri, ["module-not-found"])

    (workspace / "modules/modules.csv").write_text(
        "module_name,module_step,param_1\n"
        "Login,Press Element,${btn}\n"
        "Gone,Press Element,${btn}\n"
    )
    client.workspace_did_change_watched_files(
        types.DidChangeWatchedFilesParams(
            changes=[
                types.FileEvent(
                    uri=(workspace / "modules/modules.csv").as_uri(),
                    type=types.FileChangeType.Changed,
                )
            ]
        )
    )
    await codes_for(client, uri, [])

