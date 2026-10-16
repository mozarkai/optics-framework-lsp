import hashlib
import io
import os
import zipfile

import pytest

from optics_framework_lsp import adb_setup, device


def _zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("platform-tools/adb", "#!/bin/sh\n")
        archive.writestr("platform-tools/fastboot", "")
    return buffer.getvalue()


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    body = _zip()
    calls = []
    monkeypatch.setattr(adb_setup.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("OPTICS_AUTO_INSTALL", "1")
    monkeypatch.setattr(adb_setup, "problem", None)
    monkeypatch.setitem(adb_setup.ASSETS, adb_setup.sys.platform, ("test", hashlib.sha256(body).hexdigest()))

    def urlopen(url, timeout):
        calls.append(url)
        return io.BytesIO(body)

    monkeypatch.setattr(adb_setup.urllib.request, "urlopen", urlopen)
    return calls


@pytest.mark.skipif(os.name == "nt", reason="the executable bit is a posix thing")
def test_adb_is_downloaded_once_checked_unpacked_and_made_executable(fetch):
    adb = adb_setup.ensure()

    assert adb and adb.endswith("platform-tools/adb") and os.access(adb, os.X_OK)
    assert fetch == ["https://dl.google.com/android/repository/platform-tools_r37.0.1-test.zip"]
    assert adb_setup.ensure() == adb
    assert len(fetch) == 1


def test_a_download_that_does_not_match_its_checksum_is_refused_and_not_retried_at_once(fetch, monkeypatch):
    monkeypatch.setitem(adb_setup.ASSETS, adb_setup.sys.platform, ("test", "0" * 64))

    assert adb_setup.ensure() is None
    assert "checksum" in adb_setup.problem
    assert adb_setup.installed() is None
    assert adb_setup.ensure() is None
    assert len(fetch) == 1


def test_a_failed_download_is_tried_again_after_the_wait(fetch, monkeypatch):
    monkeypatch.setitem(adb_setup.ASSETS, adb_setup.sys.platform, ("test", "0" * 64))
    adb_setup.ensure()
    monkeypatch.setattr(adb_setup, "RETRY_AFTER", 0)
    monkeypatch.setitem(adb_setup.ASSETS, adb_setup.sys.platform, ("test", hashlib.sha256(_zip()).hexdigest()))

    assert adb_setup.ensure() is not None
    assert len(fetch) == 2


@pytest.mark.parametrize("setting", ["0", "false", "no"])
def test_fetching_can_be_switched_off(fetch, monkeypatch, setting):
    monkeypatch.setenv("OPTICS_AUTO_INSTALL", setting)

    assert adb_setup.ensure() is None
    assert fetch == []


def test_a_machine_google_publishes_no_build_for_is_left_alone(fetch, monkeypatch):
    monkeypatch.setattr(adb_setup.sys, "platform", "freebsd")

    assert adb_setup.ensure() is None
    assert fetch == []


def test_the_users_own_adb_comes_before_a_download(fetch, monkeypatch):
    monkeypatch.setenv("OPTICS_ADB", "/mine/adb")
    assert device._adb() == "/mine/adb"

    monkeypatch.delenv("OPTICS_ADB")
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.setattr(device.shutil, "which", lambda name: "/usr/bin/adb")
    assert device._adb() == "/usr/bin/adb"
    assert fetch == []

    monkeypatch.setattr(device.shutil, "which", lambda name: None)
    assert device._adb() is not None
    assert len(fetch) == 1


def test_the_panel_says_why_adb_is_missing(monkeypatch):
    monkeypatch.setattr(device, "_adb", lambda: None)
    monkeypatch.setattr(adb_setup, "problem", "adb could not be downloaded (offline)")
    monkeypatch.setattr(device.sys, "platform", "linux")

    assert "could not be downloaded (offline)" in device.list_devices()["notes"][0]
