// The same answers the editor gets, offered to an AI agent.
//
// `agent-lsp` is a generic LSP-to-MCP bridge: it spawns a language server and re-exposes its
// requests as MCP tools, so an agent can ask for diagnostics, hover, references, rename and
// workspace symbols across a whole project. Registering it here means installing this extension
// is the whole setup — no separate install, and no config file to generate either: the server is
// one command-line argument and the workspace is the working directory.
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

// Pinned, not floated: the checksums are the ones published with this release, and `agent-lsp
// update` must never be called — the binary that runs is the binary we verified.
const VERSION = '0.19.2';
const RELEASE = `https://github.com/blackwell-systems/agent-lsp/releases/download/v${VERSION}`;

// The name every client knows the server by, and the language id agent-lsp routes under. Kept
// distinct: the two appear side by side in a client's server list, and the same word twice reads
// as two servers.
export const NAME = 'optics';
const LANGUAGE = 'optics-csv';

const ASSETS: Record<string, { archive: string; sha256: string }> = {
  'darwin-arm64': {
    archive: 'agent-lsp_darwin_arm64.tar.gz',
    sha256: 'b5ae67f20e7aedc511bedee875f0a25066c0ab493d765fed53b4cc8c8d425e2e',
  },
  'darwin-x64': {
    archive: 'agent-lsp_darwin_amd64.tar.gz',
    sha256: '44943ad9065c22f90376de8a1242787a3a3d0ee5c6df779bfa22b59fbeac8d6e',
  },
  'linux-arm64': {
    archive: 'agent-lsp_linux_arm64.tar.gz',
    sha256: '325ad82236e976d4b0741167fcdbaa9125c9f4852e63fab553692a7495dc5153',
  },
  'linux-x64': {
    archive: 'agent-lsp_linux_amd64.tar.gz',
    sha256: '03a8cdc9a190a096d1e865154daf37d2d15fbdbc1ea0655b46ffe483e8ffeca9',
  },
  'win32-arm64': {
    archive: 'agent-lsp_windows_arm64.zip',
    sha256: '65fe0ef6f70828f7739a4941f43bf8e73a9173ad110ec63e6337a3010b355d47',
  },
  'win32-x64': {
    archive: 'agent-lsp_windows_amd64.zip',
    sha256: '938eccf79cc957090b20aadce71ff46cdf14931e925d4436908cd598e0b5a92b',
  },
};

// How the language server is launched, as the extension resolved it for its own client. Cached
// rather than re-resolved on every call, but not depended on: a fresh project has no CSVs and may
// have no interpreter selected yet, and the whole point of the bridge there is to help write the
// first suite. So when the cache is empty the resolver runs on demand.
let launch: Executable | undefined;
let resolver: (() => Promise<Executable | undefined>) | undefined;

const changed = new vscode.EventEmitter<void>();

/** Called whenever the interpreter changes, which is whenever the client is (re)started. */
export function relaunch(executable: Executable | undefined): void {
  launch = executable;
  changed.fire();
}

/** The bridge takes its workspace from the folder it is spawned in, so a change makes it stale. */
export function refresh(): void {
  changed.fire();
}


/**
 * Resolves the launch, from cache or by asking. Whatever the resolver reports on failure is the
 * actionable message — "no interpreter selected" is a thing a user can fix, "not running" is not.
 */
export async function ensureLaunch(): Promise<Executable | undefined> {
  launch ??= await resolver?.();
  return launch;
}

/**
 * The id `package.json` contributes under. VS Code matches the two by string and silently
 * contributes nothing when they differ, so the tests assert they are equal.
 */
export const PROVIDER_ID = 'optics.agentLsp';

export function register(
  context: vscode.ExtensionContext,
  resolveLaunch: () => Promise<Executable | undefined>
): vscode.Disposable {
  resolver = resolveLaunch;
  return vscode.lm.registerMcpServerDefinitionProvider(PROVIDER_ID, provider(context));
}

/** Split out from `register` so the tests can drive it without a live MCP client. */
export function provider(context: vscode.ExtensionContext): vscode.McpServerDefinitionProvider {
  return {
    onDidChangeMcpServerDefinitions: changed.event,

    provideMcpServerDefinitions: () => {
      // Offered whenever there is a project. The interpreter is resolved in `resolve`, which is
      // allowed to prompt — here we must not, and an unresolved one is no reason to hide the
      // server from a project that has yet to grow its first CSV.
      const on = vscode.workspace.getConfiguration('optics').get<boolean>('mcp.enabled');
      if (on === false || !vscode.workspace.workspaceFolders?.length) {
        return [];
      }
      return [
        new vscode.McpStdioServerDefinition(
          'Optics Framework',
          // A placeholder: the real command needs the binary, which resolve fetches. VS Code
          // calls this eagerly and forbids user interaction here, so the download waits.
          'agent-lsp',
          [],
          {},
          VERSION
        ),
      ];
    },

    // Called only when a server is actually starting, which is where the docs put work that
    // may block or prompt — so the fetch happens on first agent use, not on every startup.
    resolveMcpServerDefinition: async (server) => {
      if (!(server instanceof vscode.McpStdioServerDefinition)) {
        return undefined;
      }
      const resolved = await ensureLaunch();
      if (!resolved) {
        return undefined;
      }
      const binary = await resolveBinary(context);
      if (!binary) {
        return undefined;
      }
      server.command = binary;
      server.args = [serverSpec(resolved)];
      server.env = serverEnv(resolved);
      // agent-lsp takes its workspace from the directory it is spawned in.
      server.cwd = vscode.workspace.workspaceFolders?.[0]?.uri;
      return server;
    },
  };
}

/**
 * The single argument that tells agent-lsp what to run, `id:command,arg,arg`. Comma-separated,
 * which is why nothing in it may contain a comma — an interpreter path never does.
 */
export function serverSpec(executable: Executable): string {
  return `${LANGUAGE}:${[executable.command, ...(executable.args ?? [])].join(',')}`;
}

/**
 * What the server needs in its environment. agent-lsp passes its own environment to the server
 * it spawns, which is how the bundled payload reaches an interpreter started with `-S`.
 */
export function serverEnv(executable: Executable): Record<string, string> {
  return {
    PYTHONPATH: executable.options?.env?.PYTHONPATH ?? '',
    // Otherwise the server writes __pycache__ into the payload we packaged.
    PYTHONDONTWRITEBYTECODE: '1',
  };
}

/** The configured binary if there is one, else the cached download, else fetch it. */
export async function resolveBinary(
  context: vscode.ExtensionContext
): Promise<string | undefined> {
  const configured = vscode.workspace
    .getConfiguration('optics')
    .get<string>('mcp.binaryPath');
  if (configured) {
    return configured;
  }

  const asset = ASSETS[`${process.platform}-${process.arch}`];
  if (!asset) {
    void vscode.window.showErrorMessage(
      `Optics: agent-lsp publishes no build for ${process.platform}-${process.arch}. ` +
        'Set optics.mcp.binaryPath to a binary you built yourself.'
    );
    return undefined;
  }

  // Version in the directory name, so a bump is a fresh download rather than a stale hit.
  const home = vscode.Uri.joinPath(context.globalStorageUri, `agent-lsp-${VERSION}`);
  const binary = vscode.Uri.joinPath(
    home,
    process.platform === 'win32' ? 'agent-lsp.exe' : 'agent-lsp'
  );
  try {
    await vscode.workspace.fs.stat(binary);
    return binary.fsPath;
  } catch {
    // Not downloaded yet.
  }

  try {
    return await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Optics: downloading agent-lsp ${VERSION}`,
      },
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
      `Optics: could not install agent-lsp ${VERSION}: ${error}`,
      'Open Settings'
    );
    if (choice === 'Open Settings') {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'optics.mcp');
    }
    return undefined;
  }
}
