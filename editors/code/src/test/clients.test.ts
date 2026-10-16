import * as assert from 'assert';
import { mkdtempSync, mkdirSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join, resolve } from 'path';
import * as vscode from 'vscode';

import { installSkill } from '../clients';

suite('installSkill', () => {
  test('every skill folder is copied whole to an agent that is installed', async () => {
    const home = mkdtempSync(join(tmpdir(), 'optics-home-'));
    mkdirSync(join(home, '.claude'));
    const saved = process.env.HOME;
    process.env.HOME = home;
    try {
      const source = vscode.Uri.file(resolve(__dirname, '../../../../src/optics_framework_lsp/skills'));
      assert.deepStrictEqual(await installSkill(source), ['Claude Code']);
    } finally {
      process.env.HOME = saved;
    }
    for (const file of ['optics-framework/SKILL.md', 'optics-to-native/SKILL.md', 'optics-to-native/references/ios.md']) {
      assert.ok(existsSync(join(home, '.claude', 'skills', file)), file);
    }
  });
});
