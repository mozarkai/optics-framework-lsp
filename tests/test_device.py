import subprocess
import sys

import pytest

from optics_framework_lsp import device

PNG = b"\x89PNG\r\n\x1a\nfake"

ADB = """#!/bin/sh
case "$*" in
  "devices -l") printf 'List of devices attached\\nemulator-5554 device product:x model:Pixel_8 device:y\\nR58 offline\\n\\n' ;;
  "-s emulator-5554 exec-out screencap -p") printf '\\211PNG\\r\\n\\032\\nfake' ;;
  *) echo "error: device '$2' not found" >&2; exit 1 ;;
esac
"""

XCRUN = """#!/bin/sh
case "$*" in
  "simctl list devices booted --json") echo '{"devices": {"iOS-26": [{"udid": "U1", "name": "iPhone 17", "state": "Booted"}]}}' ;;
  "simctl io U1 screenshot --type=png "*) printf '\\211PNG\\r\\n\\032\\nfake' > "$6" ;;
  *) echo "Invalid device: $3" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def tools(tmp_path, monkeypatch):
    for name, body in (("adb", ADB), ("xcrun", XCRUN)):
        (tmp_path / name).write_text(body)
        (tmp_path / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("OPTICS_ADB", str(tmp_path / "adb"))
    monkeypatch.setattr(device.sys, "platform", "darwin")


def test_lists_booted_simulators_and_online_android_devices_only(tools):
    found = device.list_devices()
    assert found["devices"] == [
        {"id": "android:emulator-5554", "name": "Pixel 8", "platform": "android"},
        {"id": "ios:U1", "name": "iPhone 17", "platform": "ios"},
    ]
    assert found["notes"] == []


def test_a_missing_adb_is_explained_rather_than_hidden(tools, monkeypatch):
    monkeypatch.delenv("OPTICS_ADB")
    monkeypatch.setenv("ANDROID_HOME", "/nonexistent")
    monkeypatch.setattr(device, "_adb", lambda: None)
    found = device.list_devices()
    assert [d["platform"] for d in found["devices"]] == ["ios"]
    assert "adb not found" in found["notes"][0]


@pytest.mark.parametrize("device_id", ["android:emulator-5554", "ios:U1"])
def test_capture_returns_the_png(tools, device_id):
    assert device.capture(device_id) == PNG


def test_capture_of_a_missing_device_says_so(tools):
    with pytest.raises(device.DeviceError, match="not found"):
        device.capture("android:gone")


def test_the_hidden_command_is_not_advertised():
    help_text = subprocess.run(
        [sys.executable, "-m", "optics_framework_lsp", "--help"], capture_output=True, text=True
    ).stdout
    assert "_device" not in help_text
