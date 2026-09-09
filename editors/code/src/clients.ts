// Agents that keep their own MCP config, and how to add an entry to each.
//
// Copilot is deliberately absent: it reads VS Code's own MCP registry, which `mcp.ts` already
// feeds, so it needs nothing written to disk. Claude Code wraps its CLI and takes servers from
// its own config instead, which is why it needs this.

import { execFile } from 'child_process';
import { homedir } from 'os';
import { promisify } from 'util';
import * as vscode from 'vscode';

const execFileAsync = promisify(execFile);

// Where each agent reads Agent Skills from. Installed only where the parent already exists: that
// is the evidence the tool is present, since the `skills` directory itself is often absent until
// something writes one.
const SKILL_HOMES: Array<{ label: string; parent: string }> = [
  { label: 'Claude Code', parent: '.claude' },
  { label: 'Cursor', parent: '.cursor' },
  { label: 'Gemini CLI', parent: '.config/gemini-cli' },
];

/** How the CLI names the two scopes. `local` is deliberately not offered: it is neither. */
type Scope = 'user' | 'project';

interface Launch {
  binary: string;
  spec: string;
  env: Record<string, string>;
}

/** Whether the CLI is on PATH, which is the only way this can work. */
export async function claudeCodeAvailable(): Promise<boolean> {
  try {
    await execFileAsync('claude', ['--version']);
    return true;
  } catch {
    return false;
  }
}

/**
 * Registers with Claude Code through its own CLI. It owns its schema, and `claude mcp add` is a
 * supported interface where hand-editing `~/.claude.json` is not.
 */
export async function registerWithClaudeCode(
  name: string,
  launch: Launch,
  scope: Scope,
  cwd: string
): Promise<void> {
  // `add` refuses when the name is taken and has no --force, so re-running the command would fail
  // where VS Code's own registry simply overwrites. Scoped, so registering for one scope never
  // drops the entry in the other. A missing entry exits non-zero; ignored.
  await execFileAsync('claude', ['mcp', 'remove', name, '--scope', scope], { cwd }).catch(
    () => undefined
  );

  const env = Object.entries(launch.env).flatMap(([key, value]) => ['-e', `${key}=${value}`]);
  await execFileAsync(
    'claude',
    ['mcp', 'add', name, '--scope', scope, ...env, '--', launch.binary, launch.spec],
    { cwd }
  );
}

export async function pickScope(): Promise<Scope | undefined> {
  const choice = await vscode.window.showQuickPick(
    [
      {
        label: 'Every project on this machine',
        detail: 'Written to your Claude Code user config',
        scope: 'user' as Scope,
      },
      {
        label: 'This project only',
        // Worth saying up front: Claude will not use it until it is approved.
        detail: 'Written to .mcp.json, which Claude lists as pending until you approve it',
        scope: 'project' as Scope,
      },
    ],
    { title: 'Add the Optics LSP MCP server to Claude Code', ignoreFocusOut: true }
  );
  return choice?.scope;
}

/**
 * Installs the optics skill, which tells an agent the framework post-dates its training data and
 * where the documentation is. Separate from the MCP registration because it is a different
 * mechanism: the bridge owns the MCP `instructions` field, so this is the only way to say it.
 *
 * Only our own directory is written. The `CLAUDE.md` skills table that some installers maintain is
 * the user's file and is left alone.
 */
export async function installSkill(source: vscode.Uri): Promise<string[]> {
  const installed: string[] = [];
  for (const { label, parent } of SKILL_HOMES) {
    const home = vscode.Uri.file(`${homedir()}/${parent}`);
    try {
      await vscode.workspace.fs.stat(home);
    } catch {
      continue;
    }
    const target = vscode.Uri.joinPath(home, 'skills', 'optics-framework', 'SKILL.md');
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(target, '..'));
    await vscode.workspace.fs.copy(source, target, { overwrite: true });
    installed.push(label);
  }
  return installed;
}
