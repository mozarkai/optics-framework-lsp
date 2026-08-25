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


@pytest.fixture
def catalog_project(tmp_path):
    """No venv: the catalog is shipped, so keywords are known everywhere."""
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules/modules.csv").write_text(
        "module_name,module_step,param_1\nLogin,Sleep,2\n"
    )
    return tmp_path


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "optics_framework_lsp.cli"]
    ),
)
async def catalog_client(lsp_client: LanguageClient, catalog_project):
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            workspace_folders=[
                types.WorkspaceFolder(uri=catalog_project.as_uri(), name="p")
            ],
        )
    )
    yield
    await lsp_client.shutdown_session()


async def test_completion_signature_and_hover_over_lsp(catalog_client, catalog_project):
    path = catalog_project / "modules/modules.csv"
    uri = path.as_uri()
    text = path.read_text() + "New,"

    catalog_client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            types.TextDocumentItem(uri=uri, language_id="csv", version=1, text=text)
        )
    )

    where = types.Position(line=text.count("\n"), character=len("New,"))
    result = await catalog_client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=uri), position=where
        )
    )
    labels = [i.label for i in result]
    # Both, on the first request: no probe to wait for.
    assert "Login" in labels and "Press Element" in labels

    text += "Press Element,"
    edit(catalog_client, uri, 2, text)
    help_ = await catalog_client.text_document_signature_help_async(
        types.SignatureHelpParams(
            text_document=types.TextDocumentIdentifier(uri=uri),
            position=types.Position(line=text.count("\n"), character=len(text.splitlines()[-1])),
        )
    )
    assert help_.signatures[0].label.startswith("Press Element(element,")
    assert help_.active_parameter == 0

    hover = await catalog_client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=uri),
            position=types.Position(line=text.count("\n"), character=len("New,P")),
        )
    )
    # The docstring is generated into `keywords.py` from the framework's own source.
    assert ":param element:" in hover.contents.value


async def test_dot_folders_are_not_scanned(catalog_client, catalog_project):
    """optics-framework ships sample csvs of its own; they must stay invisible.

    Planted rather than relied upon: an editable install keeps the package outside
    the venv, so the real samples are not always under a dot folder.
    """
    planted = catalog_project / ".cache/samples/modules"
    planted.mkdir(parents=True, exist_ok=True)
    (planted / "modules.csv").write_text(
        "module_name,module_step,param_1\nSample Module,Press Element,${x}\n"
    )

    uri = (catalog_project / "modules/modules.csv").as_uri()
    result = await catalog_client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=uri),
            position=types.Position(line=1, character=len("Login,")),
        )
    )
    modules = [i.label for i in result if i.detail == "module"]
    assert modules == ["Login"]


def test_images_are_found_anywhere_but_dot_folders(tmp_path):
    from optics_framework_lsp.server import OpticsLanguageServer, images

    (tmp_path / "a.png").touch()
    (tmp_path / "input_templates").mkdir()
    (tmp_path / "input_templates" / "B.JPG").touch()
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "sample.png").touch()
    (tmp_path / "notes.txt").touch()

    assert images(OpticsLanguageServer().files(tmp_path.as_uri())) == ["B.JPG", "a.png"]


def test_data_files_exclude_the_projects_own_csvs(tmp_path):
    from optics_framework_lsp.parser.csv_parser import parse_csv_sources
    from optics_framework_lsp.server import data_files

    for name, content in WORKSPACE.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    # WORKSPACE already puts its elements csv here, which must not be offered as data.
    # Nor is an error-definitions csv data: it is one of our four kinds.
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "error_definitions.csv").write_text(
        "error_code,match_string\nE001,Crashed\n"
    )
    (tmp_path / "data" / "users.csv").write_text("id,name\n1,a\n")
    (tmp_path / "data" / "api.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("")

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    ast = parse_csv_sources(
        [(p.as_uri(), p.read_text()) for p in files if p.suffix == ".csv"]
    )

    assert data_files(str(tmp_path), files, ast) == ["data/api.json", "data/users.csv"]


API_YAML = """
api:
  collections:
    users:
      name: Users
      base_url: https://example.test
      apis:
        get_user:
          name: get_user
          endpoint: /users/1
        create_user:
          name: create_user
          endpoint: /users
"""


def test_apis_are_read_from_project_yaml(tmp_path):
    from optics_framework_lsp.server import apis

    (tmp_path / "api.yaml").write_text(API_YAML)
    # A config yaml has no collections, and a broken one must not raise.
    (tmp_path / "config.yaml").write_text("driver_sources:\n  - appium\n")
    (tmp_path / "broken.yml").write_text("api: [unclosed\n")

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert apis(files) == ["users.create_user", "users.get_user"]

