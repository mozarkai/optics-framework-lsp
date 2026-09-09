import { join } from 'path';
import * as vscode from 'vscode';
import { PythonExtension } from '@vscode/python-extension';
import {
  Executable,
  LanguageClient,
  LanguageClientOptions,
  TextDocumentFilter,
} from 'vscode-languageclient/node';
import * as clients from './clients';
import * as mcp from './mcp';

const MIN_PYTHON: [number, number] = [3, 12];
// Every csv and yaml, because the server classifies by what is inside a file rather than by
// its name. A yaml that is not a suite gets nothing back rather than being claimed.
const SELECTOR: TextDocumentFilter[] = [
  { scheme: 'file', pattern: '**/*.{csv,yaml,yml}' },
];
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
    mcp.register(context, () => resolveServerOptions(context)),
    vscode.commands.registerCommand('optics.server.restart', () => restart(context)),
    vscode.commands.registerCommand('optics.mcp.configure', () => configureMcp(context)),
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
  void offerAgentSetup(context);
}

/**
 * Copilot needs nothing, but Claude Code and the skill both do, and neither is discoverable from
 * the command palette by someone who does not know the extension bridges to an agent at all.
 * Shown once per install: a prompt on every start would be nagging, not information.
 */
async function offerAgentSetup(context: vscode.ExtensionContext): Promise<void> {
  const KEY = 'optics.mcp.offered';
  if (context.globalState.get<boolean>(KEY)) {
    return;
  }

  const configure = 'Set up now';
  const choice = await vscode.window.showInformationMessage(
    'Optics: your AI agent can query this project through the Optics LSP MCP server. ' +
      'Copilot finds it automatically; Claude Code needs one command, which also installs a ' +
      'skill telling the agent where the optics documentation is.',
    configure,
    'Not now'
  );

  // Marked only once it has been shown and answered, so a window that closes first retries next
  // time rather than silently consuming the single offer.
  await context.globalState.update(KEY, true);

  if (choice === configure) {
    await configureMcp(context);
  }
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}

/**
 * Copilot finds the server through VS Code's MCP registry with nothing written, so this covers the
 * agent that does not: Claude Code wraps its own CLI and reads its own config.
 */
async function configureMcp(context: vscode.ExtensionContext): Promise<void> {
  // Resolved on demand rather than taken from the running client: a new project has no CSVs to
  // open, and writing its first suite with an agent is exactly when this is wanted.
  const launch = await mcp.ensureLaunch();
  if (!launch) {
    // resolveServerOptions has already said which of the two things is wrong, and what to do.
    return;
  }

  // The skill is worth installing regardless: Cursor and Gemini CLI read the same directory, and
  // it is what tells an agent the framework post-dates its training data.
  const skilled = await clients.installSkill(
    vscode.Uri.joinPath(context.extensionUri, 'skills', 'optics-framework', 'SKILL.md')
  );

  if (!(await clients.claudeCodeAvailable())) {
    void vscode.window.showInformationMessage(
      skilled.length > 0
        ? `Optics: installed the optics skill for ${skilled.join(', ')}. Copilot finds the ` +
            'Optics LSP MCP server under MCP Servers already, and needs no setup.'
        : 'Optics: nothing to configure. Copilot finds the Optics LSP MCP server under MCP Servers already.'
    );
    return;
  }

  const scope = await clients.pickScope();
  if (!scope) {
    return;
  }

  const binary = await mcp.resolveBinary(context);
  if (!binary) {
    return;
  }

  const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!cwd) {
    void vscode.window.showErrorMessage('Optics: open a project first.');
    return;
  }

  try {
    await clients.registerWithClaudeCode(
      mcp.NAME,
      { binary, spec: mcp.serverSpec(launch), env: mcp.serverEnv(launch) },
      scope,
      cwd
    );
  } catch (error) {
    void vscode.window.showErrorMessage(`Optics: claude mcp add failed: ${error}`);
    return;
  }

  const skill = skilled.length > 0 ? ` Installed the optics skill for ${skilled.join(', ')}.` : '';
  void vscode.window.showInformationMessage(
    (scope === 'project'
      ? 'Optics: added to .mcp.json. Run `claude` and approve it before it is used.'
      : 'Optics: added to Claude Code. Restart it to pick the server up.') + skill
  );
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
