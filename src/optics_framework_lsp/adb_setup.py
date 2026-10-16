"""Fetches Google's Android platform-tools on first use, unless the user brings their own adb."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "37.0.1"
BASE = "https://dl.google.com/android/repository"
ASSETS = {
    "linux": ("linux", "d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1"),
    "darwin": ("darwin", "ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d"),
    "win32": ("win", "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99"),
}
# After a failed download, the next attempt waits: each Device view refresh would otherwise retry it.
RETRY_AFTER = 600.0

problem: str | None = None


def _cache() -> Path:
    return Path.home() / ".cache" / "optics-lsp"


def installed() -> str | None:
    adb = _cache() / f"platform-tools-{VERSION}" / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")
    return str(adb) if adb.is_file() else None


def ensure() -> str | None:
    """None says why in `problem`."""
    global problem
    if found := installed():
        return found
    asset = ASSETS.get(sys.platform)
    marker = _cache() / "platform-tools-failed"
    if os.environ.get("OPTICS_AUTO_INSTALL", "1").lower() in ("0", "false", "no") or not asset:
        return None
    if marker.exists() and time.time() - marker.stat().st_mtime < RETRY_AFTER:
        problem = marker.read_text()
        return None
    name, sha256 = asset
    try:
        with urllib.request.urlopen(f"{BASE}/platform-tools_r{VERSION}-{name}.zip", timeout=120) as response:
            body = response.read()
        if hashlib.sha256(body).hexdigest() != sha256:
            raise ValueError("the download does not match its checksum")
        _cache().mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="platform-tools-", dir=_cache()))
        try:
            zipfile.ZipFile(io.BytesIO(body)).extractall(staging)
            if sys.platform != "win32":
                for tool in (staging / "platform-tools").iterdir():
                    tool.chmod(0o755)
            os.replace(staging, _cache() / f"platform-tools-{VERSION}")
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            if not installed():
                raise
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        problem = f"adb could not be downloaded ({error})"
        _cache().mkdir(parents=True, exist_ok=True)
        marker.write_text(problem)
        return None
    return installed()
