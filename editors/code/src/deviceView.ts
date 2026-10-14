import { randomBytes } from 'crypto';
import * as vscode from 'vscode';
import * as device from './device';
import * as mcp from './mcp';
import { Poller } from './poller';

export const VIEW_ID = 'optics.deviceView';
const LAST_DEVICE = 'optics.deviceView.last';

export class DeviceView implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | undefined;
  private listing: device.Listing = { devices: [], notes: [] };
  private selected: string | undefined;
  private paused = false;
  private readonly poller = new Poller(
    () => this.frame(),
    () => Math.max(250, this.setting<number>('refreshMs', 1000))
  );

  constructor(private readonly context: vscode.ExtensionContext) {
    this.selected = context.workspaceState.get<string>(LAST_DEVICE);
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = html(view.webview.cspSource);
    view.webview.onDidReceiveMessage((message) => this.onMessage(message));
    view.onDidChangeVisibility(() => (view.visible ? this.resume() : this.poller.stop()));
    view.onDidDispose(() => {
      this.poller.stop();
      this.view = undefined;
    });
  }

  private setting<T>(key: string, fallback: T): T {
    return vscode.workspace.getConfiguration('optics.deviceView').get<T>(key) ?? fallback;
  }

  private adb(): string | undefined {
    return this.setting<string | null>('adbPath', null) ?? undefined;
  }

  private post(message: object): void {
    void this.view?.webview.postMessage(message);
  }

  private onMessage(message: { type: string; id?: string }): void {
    switch (message.type) {
      case 'ready':
        void this.resume();
        break;
      case 'refresh':
        void this.relist();
        break;
      case 'select':
        this.selected = message.id;
        void this.context.workspaceState.update(LAST_DEVICE, message.id);
        this.poller.stop();
        this.poller.start();
        break;
      case 'pause':
        this.paused = !this.paused;
        this.post({ type: 'paused', paused: this.paused });
        this.paused ? this.poller.stop() : this.poller.start();
        break;
    }
  }

  private async resume(): Promise<void> {
    await this.relist();
    if (!this.paused) {
      this.poller.start();
    }
  }

  private async relist(): Promise<void> {
    const launch = await mcp.ensureLaunch();
    if (!launch) {
      this.post({ type: 'error', message: 'No Python interpreter for the Optics server. See the Optics notification.' });
      return;
    }
    try {
      this.listing = await device.listDevices(launch, this.adb());
    } catch (error) {
      this.post({ type: 'error', message: String(error instanceof Error ? error.message : error) });
      return;
    }
    if (!this.listing.devices.some((d) => d.id === this.selected)) {
      this.selected = this.listing.devices[0]?.id;
    }
    this.post({ type: 'devices', ...this.listing, selected: this.selected });
  }

  private async frame(): Promise<void> {
    const launch = await mcp.ensureLaunch();
    if (!launch || !this.selected) {
      return;
    }
    try {
      const png = await device.capture(launch, this.selected, this.adb());
      this.post({ type: 'frame', png: png.toString('base64') });
    } catch (error) {
      this.post({ type: 'error', message: String(error instanceof Error ? error.message : error) });
      await this.relist();
    }
  }
}

function html(csp: string): string {
  const nonce = randomBytes(16).toString('hex');
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body { padding: 8px; display: flex; flex-direction: column; gap: 8px; height: 100vh; box-sizing: border-box; }
  .bar { display: flex; gap: 6px; flex-wrap: wrap; }
  select { flex: 1; min-width: 120px; padding: 3px 4px; color: var(--vscode-dropdown-foreground); background: var(--vscode-dropdown-background); border: 1px solid var(--vscode-dropdown-border); font: inherit; }
  button { padding: 4px 10px; color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); border: 1px solid var(--vscode-button-border, transparent); border-radius: 2px; font: inherit; cursor: pointer; }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
  button:focus-visible, select:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
  #screen { flex: 1; overflow: auto; text-align: center; }
  #screen img { max-width: 100%; max-height: 100%; }
  #screen.actual img { max-width: none; max-height: none; }
  #note { color: var(--vscode-descriptionForeground); font-size: 12px; white-space: pre-wrap; }
</style></head>
<body>
  <div class="bar">
    <select id="device" aria-label="Device"></select>
    <button id="refresh" title="Look for devices again">Refresh</button>
    <button id="pause">Pause</button>
    <button id="zoom" title="Fit the panel or show actual size">Actual size</button>
  </div>
  <div id="note">Looking for devices…</div>
  <div id="screen"><img id="img" alt="Device screen" hidden></div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);
  $('refresh').onclick = () => vscode.postMessage({ type: 'refresh' });
  $('pause').onclick = () => vscode.postMessage({ type: 'pause' });
  $('device').onchange = (e) => vscode.postMessage({ type: 'select', id: e.target.value });
  $('zoom').onclick = () => {
    const actual = $('screen').classList.toggle('actual');
    $('zoom').textContent = actual ? 'Fit' : 'Actual size';
  };
  window.addEventListener('message', ({ data }) => {
    if (data.type === 'devices') {
      $('device').innerHTML = '';
      for (const d of data.devices) {
        const option = new Option(d.name + ' (' + d.platform + ')', d.id, false, d.id === data.selected);
        $('device').add(option);
      }
      $('note').textContent = data.devices.length
        ? data.notes.join('\\n')
        : ['No device found. Start an emulator or a simulator.', ...data.notes].join('\\n');
      $('img').hidden = !data.devices.length;
    } else if (data.type === 'frame') {
      $('img').src = 'data:image/png;base64,' + data.png;
      $('img').hidden = false;
      $('note').textContent = '';
    } else if (data.type === 'error') {
      $('note').textContent = data.message;
    } else if (data.type === 'paused') {
      $('pause').textContent = data.paused ? 'Resume' : 'Pause';
    }
  });
  vscode.postMessage({ type: 'ready' });
</script></body></html>`;
}
