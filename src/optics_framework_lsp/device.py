"""The hidden `optics-lsp _device` command, so every editor's device view shares one adb and simctl."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 15


class DeviceError(Exception):
    pass


def _adb() -> str | None:
    """An IDE started from the Dock rarely has the SDK on its PATH."""

    if os.environ.get("OPTICS_ADB"):
        return os.environ["OPTICS_ADB"]
    for sdk in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), "~/Library/Android/sdk", "~/Android/Sdk"):
        candidate = Path(sdk).expanduser() / "platform-tools" / "adb" if sdk else None
        if candidate and candidate.is_file():
            return str(candidate)
    return shutil.which("adb")


def _run(command: list[str]) -> bytes:
    try:
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DeviceError(f"{Path(command[0]).name} did not answer within {TIMEOUT}s") from None
    if done.returncode:
        raise DeviceError(done.stderr.decode(errors="replace").strip() or f"{Path(command[0]).name} failed")
    return done.stdout


def _android(adb: str) -> list[dict]:
    devices = []
    for line in _run([adb, "devices", "-l"]).decode().splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2 or fields[1] != "device":
            continue
        model = next((f[6:] for f in fields[2:] if f.startswith("model:")), fields[0])
        devices.append({"id": f"android:{fields[0]}", "name": model.replace("_", " "), "platform": "android"})
    return devices


def _ios() -> list[dict]:
    booted = json.loads(_run(["xcrun", "simctl", "list", "devices", "booted", "--json"]))["devices"]
    return [
        {"id": f"ios:{sim['udid']}", "name": sim["name"], "platform": "ios"}
        for sims in booted.values()
        for sim in sims
        if sim.get("state") == "Booted"
    ]


def list_devices() -> dict:
    devices, notes = [], []
    adb = _adb()
    if adb:
        try:
            devices += _android(adb)
        except (DeviceError, OSError) as error:
            notes.append(f"Android: {error}")
    else:
        notes.append("Android: adb not found. Set optics.deviceView.adbPath or install the platform tools.")
    if sys.platform == "darwin" and shutil.which("xcrun"):
        try:
            devices += _ios()
        except (DeviceError, OSError, KeyError, ValueError) as error:
            notes.append(f"iOS: {error}")
    return {"devices": devices, "notes": notes}


def capture(device_id: str) -> bytes:
    platform, _, serial = device_id.partition(":")
    if platform == "android":
        adb = _adb()
        if not adb:
            raise DeviceError("adb not found")
        return _run([adb, "-s", serial, "exec-out", "screencap", "-p"])
    if platform == "ios":
        # simctl treats `-` as a file name rather than stdout, so go through a file.
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / "screen.png"
            _run(["xcrun", "simctl", "io", serial, "screenshot", "--type=png", str(shot)])
            return shot.read_bytes()
    raise DeviceError(f"unknown device: {device_id}")


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["list"]:
            print(json.dumps(list_devices()))
            return 0
        if len(argv) == 2 and argv[0] == "capture":
            sys.stdout.buffer.write(capture(argv[1]))
            return 0
    except (DeviceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print("usage: optics-lsp _device list | capture ID", file=sys.stderr)
    return 2
