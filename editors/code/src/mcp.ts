// The same answers the editor gets, offered to an AI agent.
//
// `mcpls` is a generic LSP-to-MCP bridge: it spawns a language server and re-exposes its
// requests as MCP tools, so an agent can ask for diagnostics, hover, references, rename and
// workspace symbols across a whole project. Registering it here means installing this
// extension is the whole setup — no separate install, no config file to hand-edit.
//
// The binary is fetched on first use rather than shipped, which keeps one `.vsix` instead of
// six platform-specific ones. `optics.mcp.binaryPath` skips the fetch entirely, for a network
// that cannot reach GitHub.

import { execFile } from 'child_process';
import { createHash } from 'crypto';
import { chmod } from 'fs/promises';
import { promisify } from 'util';
import * as vscode from 'vscode';
import { Executable } from 'vscode-languageclient/node';

const execFileAsync = promisify(execFile);

// Pinned, not floated: mcpls is young enough that a bump is a real change. The checksums are
// the ones published alongside the release, recorded here so a swapped download is caught.
const VERSION = '0.3.9';
const RELEASE = `https://github.com/bug-ops/mcpls/releases/download/v${VERSION}`;

const ASSETS: Record<string, { archive: string; sha256: string }> = {
  'darwin-arm64': {
    archive: 'mcpls-aarch64-apple-darwin.tar.gz',
    sha256: '5ea14d8c3ebcec10e5204479699f513ac1dae327dd9dc2147884903818d34de2',
  },
  'darwin-x64': {
    archive: 'mcpls-x86_64-apple-darwin.tar.gz',
    sha256: '12b535d19c84eb884979bc5daf8be65f57ca72446bb991ee5eb13ca6948b929e',
  },
  'linux-arm64': {
    archive: 'mcpls-aarch64-unknown-linux-gnu.tar.gz',
    sha256: '88348c9912febfb8ced73cfc19f530fa08f688a7bcdf88f15cc7ea1cc19a09f3',
  },
  'linux-x64': {
    archive: 'mcpls-x86_64-unknown-linux-gnu.tar.gz',
    sha256: 'fb77498f38d26b209310efe682fa576490d4d337dc4831dfe754a860e6db6fcd',
  },
  'win32-arm64': {
    archive: 'mcpls-aarch64-pc-windows-msvc.zip',
    sha256: '0eac4ec45ee1ea1ef242f4f3606a067f2d731c62c189dd7814de234f5646f152',
  },
  'win32-x64': {
    archive: 'mcpls-x86_64-pc-windows-msvc.zip',
    sha256: '330479b829b75b6a4bae18611e746564ea94419bd9ac94c05bf992680051058e',
  },
};

// How the language server is launched, as the extension already resolved it for its own
// client. Kept rather than re-resolved: resolving reports its own failures to the user, and
// doing it twice would report them twice.
let launch: Executable | undefined;

const changed = new vscode.EventEmitter<void>();

/** Called whenever the interpreter changes, which is whenever the client is (re)started. */
export function relaunch(executable: Executable | undefined): void {
  launch = executable;
  changed.fire();
}

/** The config names the workspace roots, so it is stale after a folder is added or removed. */
export function refresh(): void {
  changed.fire();
}

export function register(context: vscode.ExtensionContext): vscode.Disposable {
  return vscode.lm.registerMcpServerDefinitionProvider('optics.mcpls', {
    onDidChangeMcpServerDefinitions: changed.event,

    provideMcpServerDefinitions: () => {
      // Nothing to serve when switched off, or without a project to scope to and a server
      // to bridge.
      const on = vscode.workspace.getConfiguration('optics').get<boolean>('mcp.enabled');
      if (on === false || !launch || !vscode.workspace.workspaceFolders?.length) {
        return [];
      }
      return [
        new vscode.McpStdioServerDefinition(
          'Optics Framework',
          // A placeholder: the real command needs the binary, which resolve fetches. VS Code
          // calls this eagerly and forbids user interaction here, so the download waits.
          'mcpls',
          [],
          {},
          VERSION
        ),
      ];
    },

    // Called only when a server is actually starting, which is where the docs put work that
    // may block or prompt — so the fetch happens on first agent use, not on every startup.
    resolveMcpServerDefinition: async (server) => {
      if (!(server instanceof vscode.McpStdioServerDefinition) || !launch) {
        return undefined;
      }
      const binary = await resolveBinary(context);
      if (!binary) {
        return undefined;
      }
      server.command = binary;
      server.env = { MCPLS_CONFIG: await writeConfig(context, launch) };
      return server;
    },
  });
}

/** The configured binary if there is one, else the cached download, else fetch it. */
async function resolveBinary(context: vscode.ExtensionContext): Promise<string | undefined> {
  const configured = vscode.workspace
    .getConfiguration('optics')
    .get<string>('mcp.binaryPath');
  if (configured) {
    return configured;
  }

  const asset = ASSETS[`${process.platform}-${process.arch}`];
  if (!asset) {
    void vscode.window.showErrorMessage(
      `Optics: mcpls publishes no build for ${process.platform}-${process.arch}. ` +
        'Set optics.mcp.binaryPath to a binary you built yourself.'
    );
    return undefined;
  }

  // Version in the directory name, so a bump is a fresh download rather than a stale hit.
  const home = vscode.Uri.joinPath(context.globalStorageUri, `mcpls-${VERSION}`);
  const binary = vscode.Uri.joinPath(home, process.platform === 'win32' ? 'mcpls.exe' : 'mcpls');
  try {
    await vscode.workspace.fs.stat(binary);
    return binary.fsPath;
  } catch {
    // Not downloaded yet.
  }

  try {
    return await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Optics: downloading mcpls ${VERSION}` },
      async () => {
        const response = await fetch(`${RELEASE}/${asset.archive}`);
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`);
        }
        const body = new Uint8Array(await response.arrayBuffer());

        const digest = createHash('sha256').update(body).digest('hex');
        if (digest !== asset.sha256) {
          throw new Error(`checksum mismatch: expected ${asset.sha256}, got ${digest}`);
        }

        await vscode.workspace.fs.createDirectory(home);
        const archive = vscode.Uri.joinPath(home, asset.archive);
        await vscode.workspace.fs.writeFile(archive, body);
        // `tar` reads both .tar.gz and .zip, and ships on macOS, Linux and Windows 10+
        // (bsdtar) — so no extraction dependency.
        await execFileAsync('tar', ['-xf', archive.fsPath, '-C', home.fsPath]);
        await vscode.workspace.fs.delete(archive);
        // On Windows this only touches the read-only flag, which is harmless.
        await chmod(binary.fsPath, 0o755);
        return binary.fsPath;
      }
    );
  } catch (error) {
    const choice = await vscode.window.showErrorMessage(
      `Optics: could not install mcpls ${VERSION}: ${error}`,
      'Open Settings'
    );
    if (choice === 'Open Settings') {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'optics.mcp');
    }
    return undefined;
  }
}

/**
 * mcpls is configured by a file, not by flags. Pure so a test can assert the shape without
 * a workspace: the config is the part most likely to break on an mcpls upgrade.
 */
export function renderConfig(roots: string[], executable: Executable): string {
  // TOML basic strings escape as JSON strings do, which matters for Windows paths.
  const quote = (value: string) => JSON.stringify(value);
  const pythonPath = executable.options?.env?.PYTHONPATH ?? '';

  return [
    '# Generated by the Optics VS Code extension. Edits are overwritten.',
    '[workspace]',
    `roots = [${roots.map(quote).join(', ')}]`,
    '',
    // Without this a .csv is whatever mcpls guesses, and the languageId it opens files with
    // is wrong. Nested under [workspace]: at the top level it is not a recognised key.
    '[[workspace.language_extensions]]',
    'extensions = ["csv"]',
    'language_id = "optics"',
    '',
    '[[lsp_servers]]',
    'language_id = "optics"',
    `command = ${quote(executable.command)}`,
    `args = [${(executable.args ?? []).map(quote).join(', ')}]`,
    'file_patterns = ["**/*.csv"]',
    `env = { PYTHONPATH = ${quote(pythonPath)} }`,
    '',
  ].join('\n');
}

/** Rewritten on every resolve, since the roots and the interpreter both move. */
async function writeConfig(
  context: vscode.ExtensionContext,
  executable: Executable
): Promise<string> {
  const roots = (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
  await vscode.workspace.fs.createDirectory(context.globalStorageUri);
  const path = vscode.Uri.joinPath(context.globalStorageUri, 'mcpls.toml');
  await vscode.workspace.fs.writeFile(
    path,
    Buffer.from(renderConfig(roots, executable), 'utf8')
  );
  return path.fsPath;
}
