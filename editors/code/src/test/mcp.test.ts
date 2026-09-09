import * as assert from 'assert';
import * as vscode from 'vscode';

import { NAME, PROVIDER_ID, provider, relaunch, serverEnv, serverSpec } from '../mcp';

// agent-lsp takes the language server as one comma-separated argument, so a wrong shape here is
// an MCP server that starts and then bridges nothing.
suite('agent-lsp launch', () => {
  const launch = {
    command: '/usr/bin/python3',
    args: ['-S', '-m', 'optics_framework_lsp'],
    options: { env: { PYTHONPATH: '/ext/bundled/libs' } },
  };

  test('the spec names the language id, distinct from the server name, then the command', () => {
    assert.strictEqual(
      serverSpec(launch),
      'optics-csv:/usr/bin/python3,-S,-m,optics_framework_lsp'
    );
  });

  test('a windows interpreter path survives the spec', () => {
    // Backslashes are not separators here, only commas are.
    assert.strictEqual(
      serverSpec({ ...launch, command: 'C:\\Python312\\python.exe' }),
      'optics-csv:C:\\Python312\\python.exe,-S,-m,optics_framework_lsp'
    );
  });

  test('the environment carries the bundled payload and suppresses bytecode', () => {
    assert.deepStrictEqual(serverEnv(launch), {
      PYTHONPATH: '/ext/bundled/libs',
      PYTHONDONTWRITEBYTECODE: '1',
    });
  });

  test('an interpreter with no arguments still produces a valid spec', () => {
    assert.strictEqual(
      serverSpec({ command: '/usr/local/bin/optics-lsp' }),
      'optics-csv:/usr/local/bin/optics-lsp'
    );
  });
});

// The provider itself. VS Code offers no way to read back its MCP registry, so these drive the
// provider directly: everything on our side of the boundary, up to the definition we hand over.
suite('agent-lsp provider', () => {
  const optics = () => vscode.workspace.getConfiguration('optics');

  // resolveBinary returns a configured path without touching the context, so a stub suffices and
  // no download happens during the tests.
  const context = { globalStorageUri: vscode.Uri.file('/unused') } as vscode.ExtensionContext;

  const launch = {
    command: '/usr/bin/python3',
    args: ['-S', '-m', 'optics_framework_lsp'],
    options: { env: { PYTHONPATH: '/ext/bundled/libs' } },
  };

  teardown(async () => {
    await optics().update('mcp.enabled', undefined, true);
    await optics().update('mcp.binaryPath', undefined, true);
  });

  test('the registered id is the one package.json contributes', () => {
    const contributed = vscode.extensions.getExtension('mozarkai.optics-framework-lsp')
      ?.packageJSON.contributes.mcpServerDefinitionProviders;
    assert.deepStrictEqual(
      contributed.map((p: { id: string }) => p.id),
      [PROVIDER_ID]
    );
  });

  test('an open project is offered one stdio server', () => {
    const offered = provider(context).provideMcpServerDefinitions?.(
      new vscode.CancellationTokenSource().token
    );
    const servers = offered as vscode.McpServerDefinition[];
    assert.strictEqual(servers.length, 1);
    assert.ok(servers[0] instanceof vscode.McpStdioServerDefinition);
  });

  test('turning the setting off withdraws the server', async () => {
    await optics().update('mcp.enabled', false, true);
    const offered = provider(context).provideMcpServerDefinitions?.(
      new vscode.CancellationTokenSource().token
    );
    assert.deepStrictEqual(offered, []);
  });

  // The definition handed to VS Code has to carry the binary, the one-argument spec, the payload
  // on PYTHONPATH and the workspace as cwd. Any one of them missing is a server that starts and
  // then answers nothing.
  test('resolving fills in the binary, the spec, the environment and the workspace', async () => {
    await optics().update('mcp.binaryPath', '/opt/agent-lsp', true);
    relaunch(launch);

    const resolved = (await provider(context).resolveMcpServerDefinition?.(
      new vscode.McpStdioServerDefinition(NAME, 'agent-lsp', [], {}),
      new vscode.CancellationTokenSource().token
    )) as vscode.McpStdioServerDefinition;

    assert.strictEqual(resolved.command, '/opt/agent-lsp');
    assert.deepStrictEqual(resolved.args, [serverSpec(launch)]);
    assert.strictEqual(resolved.env.PYTHONPATH, '/ext/bundled/libs');
    assert.strictEqual(
      resolved.cwd?.fsPath,
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    );
  });
});
