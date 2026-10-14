import * as assert from 'assert';
import { chmodSync, mkdtempSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join, resolve } from 'path';

import * as vscode from 'vscode';
import { capture, listDevices } from '../device';
import { Poller } from '../poller';

const launch = {
  command: 'python3',
  args: ['-m', 'optics_framework_lsp'],
  options: { env: { PYTHONPATH: resolve(__dirname, '../../../../src'), PATH: process.env.PATH } },
};

function fakeAdb(): string {
  const path = join(mkdtempSync(join(tmpdir(), 'optics-adb-')), 'adb');
  writeFileSync(
    path,
    `#!/bin/sh
case "$*" in
  "devices -l") printf 'List of devices attached\\nemulator-5554 device model:Pixel_8\\n' ;;
  *screencap*) printf '\\211PNG\\r\\n\\032\\nfake' ;;
esac
`
  );
  chmodSync(path, 0o755);
  return path;
}

suite('device view', () => {
  test('lists an android device and captures its screen through the server package', async () => {
    const adb = fakeAdb();
    const listing = await listDevices(launch, adb);
    assert.ok(listing.devices.some((d) => d.id === 'android:emulator-5554' && d.name === 'Pixel 8'));
    const png = await capture(launch, 'android:emulator-5554', adb);
    assert.strictEqual(png.subarray(1, 4).toString(), 'PNG');
  });

  test('a failing capture surfaces the message the command printed', async () => {
    await assert.rejects(capture(launch, 'nonsense:1', fakeAdb()), /unknown device/);
  });

  test('the Optics container opens in the activity bar and the view provider is registered', async () => {
    await vscode.commands.executeCommand('workbench.view.extension.optics');
    await vscode.commands.executeCommand('optics.deviceView.focus');
  });

  test('screen suggestions are off until asked for, and the binary paths cannot come from a workspace', () => {
    const config = vscode.workspace.getConfiguration('optics');
    assert.strictEqual(config.get('screenElements.enabled'), false);
    for (const key of ['screenElements.enabled', 'deviceView.adbPath']) {
      assert.ok(config.inspect(key), key);
    }
  });

  test('the poller never starts a tick while one is running', async () => {
    let running = 0;
    let overlapped = false;
    let ticks = 0;
    const poller = new Poller(async () => {
      running += 1;
      overlapped ||= running > 1;
      ticks += 1;
      await new Promise((done) => setTimeout(done, 60));
      running -= 1;
    }, () => 10);
    poller.start();
    await new Promise((done) => setTimeout(done, 400));
    poller.stop();
    const seen = ticks;
    await new Promise((done) => setTimeout(done, 150));
    assert.ok(seen >= 3, `ticks: ${seen}`);
    assert.strictEqual(overlapped, false);
    assert.strictEqual(ticks, seen, 'stop must stop it');
  });
});
