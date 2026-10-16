from __future__ import annotations

import base64
import dataclasses
import datetime
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

from .xpaths import Xpaths
from . import adb_setup
from .device import DeviceError, Missing, _adb, _android, _ios, _run, selected

# Longer text is a paragraph, which nobody locates an element by.
MAX_TEXT = 60


@dataclass(frozen=True)
class OnScreen:
    locator: str
    detail: str


ACTIONABLE = (
    "Button", "Switch", "CheckBox", "RadioButton", "ToggleButton", "SeekBar", "Slider",
    "EditText", "TextField", "SecureTextField", "SearchField", "XCUIElementTypeCell", "XCUIElementTypeLink", "XCUIElementTypeTab",
)


def _label(node: ET.Element) -> tuple[str, str]:
    for key in ("text", "content-desc", "name", "label", "value", "resource-id"):
        value = (node.get(key) or "").strip()
        if value:
            return key, value.rsplit("/", 1)[-1] if key == "resource-id" else value
    return "", ""


def _android_tree(xml: str) -> ET.Element:
    """`uiautomator dump` names every element `node`, where Appium names it by class, and optics's xpaths are Appium's."""
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        node.tag = node.get("class") or "android.view.View"
    return root


def _shown(node: ET.Element) -> tuple[str, str] | None:
    if node.tag in ("XCUIElementTypeApplication", "XCUIElementTypeWindow", "AppiumAUT", "hierarchy"):
        return None
    if node.get("visible") == "false" or node.get("displayed") == "false":
        return None
    key, label = _label(node)
    if len(label) > MAX_TEXT or not (label or any(f in node.tag for f in ACTIONABLE) or node.get("clickable") == "true"):
        return None
    return key, label


def _suggestions(root: ET.Element, ios: bool) -> list[OnScreen]:
    paths = Xpaths(root)
    found: dict[str, OnScreen] = {}
    for node in root.iter():
        shown = _shown(node)
        if node is root or shown is None:
            continue
        key, label = shown
        kind = node.tag.rsplit(".", 1)[-1].removeprefix("XCUIElementType")
        what = f"{key} {label}" if label else "no name"
        if ios and node.get("name") and len(node.get("name")) <= MAX_TEXT:
            found.setdefault(node.get("name"), OnScreen(node.get("name"), f"on screen: {kind}, name {node.get('name')}"))
        locator = paths.of(node)
        found.setdefault(locator, OnScreen(locator, f"on screen: {kind}, {what}"))
    return list(found.values())


def parse(xml: str) -> list[OnScreen]:
    return _suggestions(_android_tree(xml), ios=False)


def dump(serial: str) -> str:
    raw = _run([_need_adb(), "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"]).decode(errors="replace")
    end = raw.find("</hierarchy>")
    if end < 0:
        raise DeviceError(raw.strip() or "uiautomator returned no hierarchy")
    return raw[: end + len("</hierarchy>")]


def _connected() -> list[str]:
    adb = _adb()
    return [d["id"].split(":", 1)[1] for d in _android(adb)] if adb else []


def _booted() -> list[str]:
    return [d["id"].split(":", 1)[1] for d in _ios()] if sys.platform == "darwin" and shutil.which("xcrun") else []


_appium: dict[str, dict] = {}


def _device(config: object) -> tuple[str, dict] | None:
    for source in (config.get("driver_sources") if isinstance(config, dict) else None) or []:
        block = (source or {}).get("appium") or {}
        caps = block.get("capabilities") or {}
        platform = str(caps.get("platformName", "")).lower()
        if platform in ("android", "ios"):
            udid = str(caps.get("appium:udid") or caps.get("udid") or "")
            return (f"{platform}:{udid}", block) if udid else None
    return None


def config_device(start: Path, stop: Path) -> str | None:
    """Also keeps the suite's Appium settings, which an iOS read needs and the device id cannot carry."""
    for folder in (start, *start.parents):
        if (file := folder / "config.yaml").is_file():
            try:
                found = _device(yaml.safe_load(file.read_text()))
            except (OSError, yaml.YAMLError):
                return None
            if found:
                _appium[found[0]] = found[1]
            return found[0] if found else None
        if folder == stop:
            break
    return None


def _chosen() -> str | None:
    devices = [f"android:{serial}" for serial in _connected()] + [f"ios:{udid}" for udid in _booted()]
    picked = selected()
    if picked in devices:
        return picked
    return devices[0] if len(devices) == 1 else None


class Busy(DeviceError):
    pass


def _need_adb() -> str:
    adb = _adb()
    if not adb:
        raise Missing(f"{adb_setup.problem or 'adb not found'}. Set the adb path in the editor's settings, or OPTICS_ADB.")
    return adb


def _busy(serial: str) -> bool:
    """Appium and Espresso run as an instrumentation, uiautomator2 3 as its own process. Not
    `io.appium.settings`, which outlives the session."""
    check = "dumpsys activity | grep -c ActiveInstrumentation; ps -A -o ARGS | grep -c '[c]om.wetest.uia2.Main'; true"
    counts = _run([_need_adb(), "-s", serial, "shell", check]).decode().split()
    return any(count != "0" for count in counts)


LOCAL = ("127.0.0.1", "localhost", "::1")
DEFAULT_APPIUM = "http://127.0.0.1:4723/wd/hub"


def _http(method: str, url: str, body: dict | None = None, timeout: float = 15) -> dict:
    request = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _wda_source(port: int) -> str | None:
    """WebDriverAgent answers on its own, with no session, for as long as an Appium session keeps it up."""
    try:
        return _http("GET", f"http://127.0.0.1:{port}/source")["value"]
    except OSError:
        return None


def _caps(block: dict, udid: str) -> dict:
    caps = block.get("capabilities") or {"platformName": "iOS", "automationName": "XCUITest", "udid": udid}
    return {key if key == "platformName" or ":" in key else f"appium:{key}": value for key, value in caps.items()}


def open_session(url: str, block: dict, udid: str) -> str:
    try:
        session = _http("POST", f"{url}/session", {"capabilities": {"alwaysMatch": _caps(block, udid)}}, timeout=180)
    except urllib.error.HTTPError as error:
        raise DeviceError(f"Appium refused a session: {error.read().decode(errors='replace')[:200]}") from None
    except OSError:
        raise Missing(f"Appium is not running at {url}. Start it, or set the url in config.yaml.") from None
    return session["value"]["sessionId"]


def _appium_source(url: str, block: dict, udid: str) -> str:
    """WebDriverAgent stays up after the session closes, so the next read skips this."""
    sid = open_session(url, block, udid)

    def close() -> None:
        try:
            _http("DELETE", f"{url}/session/{sid}", timeout=60)
        except OSError:
            pass

    try:
        return _http("GET", f"{url}/session/{sid}/source", timeout=120)["value"]
    finally:
        threading.Thread(target=close, daemon=True).start()


def _ios_source(udid: str, block: dict | None) -> str:
    block = block or {}
    url = str(block.get("url") or DEFAULT_APPIUM).rstrip("/")
    port = int((block.get("capabilities") or {}).get("wdaLocalPort") or 8100)
    return _wda_source(port) or _appium_source(url, block, udid)


def is_remote(preferred: str | None) -> bool:
    url = str((_appium.get(preferred or "") or {}).get("url") or DEFAULT_APPIUM)
    return urllib.parse.urlparse(url).hostname not in LOCAL


def _check_token(block: dict) -> None:
    """The hub's token is a day-long JWT, and a refused session says nothing about why."""
    secret = ((block.get("capabilities") or {}).get("mozark:options") or {}).get("secret") or ""
    try:
        payload = secret.split(".")[1]
        expiry = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
    except (IndexError, ValueError, KeyError, TypeError):
        return
    if expiry < time.time():
        when = datetime.datetime.fromtimestamp(expiry).strftime("%d %b %H:%M")
        raise Missing(f"The hub token in config.yaml expired on {when}. Paste a fresh one.")


def parse_ios_source(xml: str) -> list[OnScreen]:
    return _suggestions(ET.fromstring(xml), ios=True)


def _resolve(preferred: str | None) -> tuple[str, str] | None:
    chosen = preferred or _chosen()
    if not chosen:
        return None
    for platform in ("android", "ios"):
        if chosen.startswith(f"{platform}:"):
            return platform, chosen.removeprefix(f"{platform}:")
    if chosen in _connected():
        return "android", chosen
    if chosen in _booted():
        return "ios", chosen
    raise DeviceError(f"{chosen} is not a connected Android device or a booted simulator")


def snapshot(preferred: str | None = None) -> list[OnScreen]:
    target = _resolve(preferred)
    if not target:
        return []
    platform, device = target
    block = _appium.get(f"{platform}:{device}")
    if is_remote(f"{platform}:{device}"):
        from .remote import HELD

        xml = HELD.source(f"{platform}:{device}", block or {}, device)
        return parse_ios_source(xml) if platform == "ios" else parse(xml)
    if platform == "ios":
        return parse_ios_source(_ios_source(device, block))
    if _busy(device):
        raise Busy(f"{device} is in use by a test")
    return parse(dump(device))


class Cache:
    """Completion must not wait ~3s for a dump, so it reads the last one and a stale cache
    refreshes in the background. Off unless asked: it touches the user's device."""

    def __init__(
        self, fetch=snapshot, ttl: float = 10.0, backoff: float = 60.0, enabled: bool = False,
        remote=lambda preferred: False, remote_ttl: float = 120.0,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._backoff = backoff
        self._enabled = enabled
        self._remote = remote
        self._remote_ttl = remote_ttl
        self._for: str | None = None
        self._found: list[OnScreen] = []
        self._next = float("-inf")
        self._busy = threading.Lock()
        self._read: dict[str | None, tuple[list[OnScreen], float]] = {}
        self.problem: str | None = None

    def _age(self, preferred: str | None) -> float | None:
        read = self._read.get(preferred)
        return time.monotonic() - read[1] if read else None

    def _asked(self, preferred: str | None) -> list[OnScreen] | None:
        age = self._age(preferred)
        if age is None or age > self._remote_ttl:
            return None
        return [dataclasses.replace(s, detail=f"{s.detail}, read {_ago(age)}") for s in self._read[preferred][0]]

    def get(self, preferred: str | None = None) -> list[OnScreen]:
        asked = self._asked(preferred)
        if self._remote(preferred):
            return asked or []
        if asked is not None and not self._enabled:
            return asked
        if preferred != self._for:
            self._for, self._found, self._next = preferred, [], float("-inf")
        if self._enabled and time.monotonic() >= self._next and self._busy.acquire(blocking=False):
            threading.Thread(target=self._refresh, args=(preferred,), daemon=True).start()
        return self._found

    def hint(self, preferred: str | None) -> str | None:
        """Why a remote device offers nothing, since it is only ever read when asked."""
        if not self._remote(preferred):
            return None
        age = self._age(preferred)
        if age is None:
            return "Read this device's screen: Optics: Read Screen Elements"
        return f"Screen read {_ago(age)}. Read it again: Optics: Read Screen Elements" if age > self._remote_ttl else None

    def read_now(self, preferred: str | None) -> list[OnScreen]:
        """Blocks for as long as the device takes, so a caller keeps it off the thread that answers the editor."""
        found = self._fetch(preferred)
        self._read[preferred] = (found, time.monotonic())
        return found

    def _refresh(self, preferred: str | None) -> None:
        wait = self._ttl
        try:
            found = self._fetch(preferred)
            self.problem = None
        except Busy:
            found = self._found
        except Missing as error:
            found, wait, self.problem = [], self._backoff, str(error)
        except Exception:
            found, wait, self.problem = [], self._backoff, None
        finally:
            if preferred == self._for:
                self._found = found
            self._next = time.monotonic() + wait
            self._busy.release()


def _ago(seconds: float) -> str:
    return f"{int(seconds)} s ago" if seconds < 90 else f"{int(seconds // 60)} min ago"
