import { execFile } from 'child_process';
import { Executable } from 'vscode-languageclient/node';

export interface Device {
  id: string;
  name: string;
  platform: 'android' | 'ios';
}

export interface Listing {
  devices: Device[];
  notes: string[];
}

// A screenshot is a few MB of PNG, hence the large buffer.
function run(launch: Executable, args: string[], adbPath: string | undefined): Promise<Buffer> {
  const env = { ...process.env, ...launch.options?.env, ...(adbPath ? { OPTICS_ADB: adbPath } : {}) };
  return new Promise((resolve, reject) => {
    execFile(
      launch.command,
      [...(launch.args ?? []), '_device', ...args],
      { env, encoding: 'buffer', maxBuffer: 64 * 1024 * 1024, timeout: 120_000 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr.toString().trim() || error.message));
        } else {
          resolve(stdout);
        }
      }
    );
  });
}

export async function listDevices(launch: Executable, adbPath?: string): Promise<Listing> {
  return JSON.parse((await run(launch, ['list'], adbPath)).toString()) as Listing;
}

export async function select(launch: Executable, id: string): Promise<void> {
  await run(launch, ['select', id], undefined);
}

export function capture(launch: Executable, id: string, adbPath?: string): Promise<Buffer> {
  return run(launch, ['capture', id], adbPath);
}
