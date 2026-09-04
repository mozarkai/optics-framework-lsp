import { join } from 'path';
import * as vscode from 'vscode';
import { PythonExtension } from '@vscode/python-extension';
import {
  Executable,
  LanguageClient,
  LanguageClientOptions,
  TextDocumentFilter,
} from 'vscode-languageclient/node';
import * as mcp from './mcp';

const MIN_PYTHON: [number, number] = [3, 12];
const SELECTOR: TextDocumentFilter[] = [{ scheme: 'file', pattern: '**/*.csv' }];
// `-S` keeps site-packages out, so the bundled libs on PYTHONPATH are the only ones importable.
const LAUNCH_ARGS = ['-S', '-m', 'optics_framework_lsp'];

let client: LanguageClient | undefined;
let python: PythonExtension | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  try {
    python = await PythonExtension.api();
  } catch {
    python = undefined;
  }

  context.subscriptions.push(
    mcp.register(context),
    vscode.commands.registerCommand('optics.server.restart', () => restart(context)),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('optics.server')) {
        restart(context);
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => mcp.refresh())
  );

  if (python) {
    context.subscriptions.push(
      python.environments.onDidChangeActiveEnvironmentPath(() => restart(context))
    );
  }

  await start(context);
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}

async function restart(context: vscode.ExtensionContext): Promise<void> {
  await client?.stop();
  client = undefined;
  await start(context);
}

async function start(context: vscode.ExtensionContext): Promise<void> {
  const serverOptions = await resolveServerOptions(context);
  // Both clients launch the server the same way, so the MCP bridge reuses what was resolved
  // here instead of resolving it again and reporting the same failure twice.
  mcp.relaunch(serverOptions);
  if (!serverOptions) {
    return;
  }

  const clientOptions: LanguageClientOptions = {
    documentSelector: SELECTOR,
    // A crash-looping server should say so once, not thrash.
    connectionOptions: { maxRestartCount: 0 },
  };

  client = new LanguageClient('optics', 'Optics Language Server', serverOptions, clientOptions);
  try {
    await client.start();
  } catch (err) {
    void vscode.window.showErrorMessage(`Optics: the language server failed to start: ${err}`);
  }
}

/** `optics.server.pythonCommand` if set, else the Python extension's active interpreter. */
async function resolveServerOptions(
  context: vscode.ExtensionContext
): Promise<Executable | undefined> {
  const options = { env: bundledEnv(context) };

  const userPython = vscode.workspace.getConfiguration('optics').get<string>('server.pythonCommand');
  if (userPython) {
    return { command: userPython, args: LAUNCH_ARGS, options };
  }

  if (!python) {
    void vscode.window.showErrorMessage(
      'Optics: the Python extension (ms-python.python) is required to locate an interpreter, or set optics.server.pythonCommand.'
    );
    return undefined;
  }

  const activeEnv = await python.environments.resolveEnvironment(
    python.environments.getActiveEnvironmentPath()
  );
  if (!activeEnv?.executable.uri) {
    void vscode.window.showErrorMessage(
      'Optics: no Python interpreter is selected. Use "Python: Select Interpreter" and try again.'
    );
    return undefined;
  }

  const [major, minor] = MIN_PYTHON;
  const version = activeEnv.version;
  if (version && (version.major < major || (version.major === major && version.minor < minor))) {
    // Better than letting them hit a Path.walk AttributeError in a log they will never open.
    const choice = await vscode.window.showErrorMessage(
      `Optics needs Python ${major}.${minor}+, but the selected interpreter is ${version.major}.${version.minor}.`,
      'Select Interpreter'
    );
    if (choice === 'Select Interpreter') {
      await vscode.commands.executeCommand('python.setInterpreter');
    }
    return undefined;
  }

  return { command: activeEnv.executable.uri.fsPath, args: LAUNCH_ARGS, options };
}

/** Bundled libs go first on PYTHONPATH so they beat anything installed. */
function bundledEnv(context: vscode.ExtensionContext): NodeJS.ProcessEnv {
  const sep = process.platform === 'win32' ? ';' : ':';
  const libs = join(context.extensionPath, 'bundled', 'libs');
  const existing = process.env.PYTHONPATH;
  return { ...process.env, PYTHONPATH: existing ? `${libs}${sep}${existing}` : libs };
}
