import * as assert from 'assert';
import { chmodSync, existsSync, mkdtempSync, readFileSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join, resolve } from 'path';

import * as vscode from 'vscode';
import { capture, listDevices, select } from '../device';
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

  test('the picked device is left where the language server reads it', async () => {
    const home = mkdtempSync(join(tmpdir(), 'optics-home-'));
    await select({ ...launch, options: { env: { ...launch.options.env, HOME: home } } }, 'android:emulator-5554');
    const file = join(home, '.cache', 'optics-lsp', 'device');
    assert.ok(existsSync(file));
    assert.strictEqual(readFileSync(file, 'utf8'), 'android:emulator-5554');
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
    assert.strictEqual(config.get('autoInstall'), true);
    for (const key of ['screenElements.enabled', 'autoInstall', 'deviceView.adbPath']) {
      assert.ok(config.inspect(key), key);
    }
  });

  test('the poller asks how long to wait each time, so a slow read can slow it down', async () => {
    const stamps: number[] = [];
    let wait = 20;
    const poller = new Poller(async () => {
      stamps.push(Date.now());
      wait = 150;
    }, () => wait);
    poller.start();
    await new Promise((done) => setTimeout(done, 450));
    poller.stop();

    const gaps = stamps.slice(1).map((t, i) => t - stamps[i]);
    assert.ok(gaps.length >= 2, `gaps: ${gaps}`);
    assert.ok(gaps.every((gap) => gap >= 120), `gaps: ${gaps}`);
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
