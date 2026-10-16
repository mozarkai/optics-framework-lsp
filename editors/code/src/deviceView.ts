import { randomBytes } from 'crypto';
import * as vscode from 'vscode';
import * as device from './device';
import * as mcp from './mcp';
import { Poller } from './poller';

export const VIEW_ID = 'optics.deviceView';
const LAST_DEVICE = 'optics.deviceView.last';

/** The language server's answer for a device on a hub: only it can hold a session there. */
export type Shot = { error?: string; png?: string };

export class DeviceView implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | undefined;
  private listing: device.Listing = { devices: [], notes: [] };
  private selected: string | undefined;
  // Applied once per value, so picking another device by hand sticks until the suite names a different one.
  private applied: string | undefined;
  private paused = false;
  // A hub screenshot takes seconds to ten, so it waits twice as long as it last took.
  private slowest = 0;
  private readonly poller = new Poller(() => this.frame(), () => Math.max(250, this.setting<number>('refreshMs', 1000)));
  private readonly pictures = new Poller(() => this.picture(), () => Math.max(10000, this.slowest * 2));

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly hubDevice: (uri: string) => Promise<device.Device | null>,
    private readonly suiteDevice: (uri: string) => Promise<string | null>,
    private readonly hubShot: (uri: string) => Promise<Shot>,
    private readonly suite: () => string | undefined
  ) {
    this.selected = context.workspaceState.get<string>(LAST_DEVICE);
  }

  /** The list has to be asked again: a hub device belongs to the suite that is open. */
  suiteChanged(): void {
    if (this.view?.visible) {
      void this.relist();
    }
  }

  private remote(): boolean {
    return !!this.selected?.startsWith('remote:');
  }

  private start(): void {
    (this.remote() ? this.pictures : this.poller).start();
  }

  private stop(): void {
    this.poller.stop();
    this.pictures.stop();
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = html(view.webview.cspSource);
    view.webview.onDidReceiveMessage((message) => this.onMessage(message));
    view.onDidChangeVisibility(() => (view.visible ? this.resume() : this.stop()));
    view.onDidDispose(() => {
      this.stop();
      this.view = undefined;
    });
  }

  private setting<T>(key: string, fallback: T): T {
    return vscode.workspace.getConfiguration('optics.deviceView').get<T>(key) ?? fallback;
  }

  // The language server is another process, and picks its device from this when nothing else does.
  private async tell(): Promise<void> {
    const launch = await mcp.ensureLaunch();
    if (launch && this.selected && !this.remote()) {
      await device.select(launch, this.selected).catch(() => undefined);
    }
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
        void this.tell();
        this.stop();
        this.post({ type: 'cleared' });
        this.start();
        break;
      case 'pause':
        this.paused = !this.paused;
        this.post({ type: 'paused', paused: this.paused });
        this.paused ? this.stop() : this.start();
        break;
    }
  }

  private async resume(): Promise<void> {
    await this.relist();
    if (!this.paused) {
      this.start();
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
      // A hub device needs none of the local tools, so it is still offered.
      this.listing = { devices: [], notes: [String(error instanceof Error ? error.message : error)] };
    }
    const suite = this.suite();
    const hub = suite ? await this.hubDevice(suite).catch(() => null) : null;
    if (hub) {
      this.listing.devices.push(hub);
    }
    const named = suite ? await this.suiteDevice(suite).catch(() => null) : null;
    const before = this.selected;
    if (named && named !== this.applied && this.listing.devices.some((d) => d.id === named)) {
      this.selected = this.applied = named;
    }
    if (!this.listing.devices.some((d) => d.id === this.selected)) {
      this.selected = this.listing.devices[0]?.id;
    }
    if (this.selected !== before && !this.paused && this.view?.visible) {
      this.stop();
      this.post({ type: 'cleared' });
      this.start();
    }
    this.post({ type: 'devices', ...this.listing, selected: this.selected });
    void this.tell();
  }

  private async picture(): Promise<void> {
    const suite = this.suite();
    if (!this.remote() || !suite) {
      return;
    }
    const asked = this.selected;
    const began = Date.now();
    const shot: Shot = await this.hubShot(suite).catch((error) => ({ error: String(error) }));
    this.slowest = Date.now() - began;
    if (this.selected !== asked) {
      return;
    }
    this.post(shot.error ? { type: 'error', message: shot.error } : { type: 'frame', png: shot.png });
  }

  private async frame(): Promise<void> {
    const launch = await mcp.ensureLaunch();
    if (!launch || !this.selected) {
      return;
    }
    const asked = this.selected;
    try {
      const png = await device.capture(launch, asked, this.adb());
      if (this.selected === asked) {
        this.post({ type: 'frame', png: png.toString('base64') });
      }
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
    } else if (data.type === 'cleared') {
      $('img').hidden = true;
    } else if (data.type === 'error') {
      $('note').textContent = data.message;
    } else if (data.type === 'paused') {
      $('pause').textContent = data.paused ? 'Resume' : 'Pause';
    }
  });
  vscode.postMessage({ type: 'ready' });
</script></body></html>`;
}
