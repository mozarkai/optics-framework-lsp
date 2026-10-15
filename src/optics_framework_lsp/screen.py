from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from .device import DeviceError, Missing, _adb, _android, _ios, _run, selected

# Longer text is a paragraph, which nobody locates an element by.
MAX_TEXT = 60


@dataclass(frozen=True)
class OnScreen:
    locator: str
    detail: str


def _quoted(value: str) -> str | None:
    """XPath has no escape for a quote, so a value holding both cannot be written."""
    if '"' not in value:
        return f'"{value}"'
    return f"'{value}'" if "'" not in value else None


def parse(xml: str) -> list[OnScreen]:
    nodes = []
    for node in ET.fromstring(xml).iter("node"):
        for attr in ("resource-id", "content-desc", "text"):
            value = node.get(attr, "").strip()
            if value and len(value) <= MAX_TEXT and _quoted(value):
                nodes.append((node.get("class", "android.view.View"), attr, value))
                break

    totals = Counter(nodes)
    seen: Counter = Counter()
    found: dict[str, OnScreen] = {}
    for key in nodes:
        node_class, attr, value = key
        seen[key] += 1
        path = f"//{node_class}[@{attr}={_quoted(value)}]"
        locator = path if totals[key] == 1 else f"({path})[{seen[key]}]"
        short = node_class.rsplit(".", 1)[-1]
        found.setdefault(locator, OnScreen(locator, f"on screen: {short}, {attr} {value}"))
    return list(found.values())


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
        raise Missing("adb not found. Set OPTICS_ADB, or the adb path in the editor's settings.")
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


def _appium_source(url: str, block: dict, udid: str) -> str:
    """WebDriverAgent stays up after the session closes, so the next read skips this."""
    try:
        session = _http("POST", f"{url}/session", {"capabilities": {"alwaysMatch": _caps(block, udid)}}, timeout=180)
    except urllib.error.HTTPError as error:
        raise DeviceError(f"Appium refused a session: {error.read().decode(errors='replace')[:200]}") from None
    except OSError:
        raise Missing(f"Appium is not running at {url}. Start it, or set the url in config.yaml.") from None
    sid = session["value"]["sessionId"]
    try:
        return _http("GET", f"{url}/session/{sid}/source")["value"]
    finally:
        try:
            _http("DELETE", f"{url}/session/{sid}")
        except OSError:
            pass


def _ios_source(udid: str, block: dict | None) -> str:
    block = block or {}
    url = str(block.get("url") or DEFAULT_APPIUM).rstrip("/")
    if urllib.parse.urlparse(url).hostname not in LOCAL:
        raise Missing("Element suggestions read a local Appium only. This suite's Appium is remote.")
    port = int((block.get("capabilities") or {}).get("wdaLocalPort") or 8100)
    return _wda_source(port) or _appium_source(url, block, udid)


def _steps(app: ET.Element) -> list[tuple[ET.Element, list[str]]]:
    found: list[tuple[ET.Element, list[str]]] = []

    def walk(parent: ET.Element, steps: list[str]) -> None:
        for child in parent:
            twins = [c for c in parent if c.tag == child.tag]
            here = steps + [child.tag + (f"[{twins.index(child) + 1}]" if len(twins) > 1 else "")]
            found.append((child, here))
            walk(child, here)

    walk(app, [])
    return found


def parse_ios_source(xml: str) -> list[OnScreen]:
    """The name as suites write it, and the path from the application as Appium Inspector writes it."""
    app = next(ET.fromstring(xml).iter("XCUIElementTypeApplication"), None)
    if app is None:
        return []
    name = _quoted(app.get("name") or "")
    root = f"//XCUIElementTypeApplication[@name={name}]" if name else "//XCUIElementTypeApplication"
    found: dict[str, OnScreen] = {}
    for node, steps in _steps(app):
        label = node.get("name") or node.get("label") or ""
        if node.tag == "XCUIElementTypeWindow" or node.get("visible") == "false" or not label.strip() or len(label) > MAX_TEXT:
            continue
        kind = node.tag.removeprefix("XCUIElementType")
        found.setdefault(label, OnScreen(label, f"on screen: {kind}, name {label}"))
        path = f"{root}/{'/'.join(steps)}"
        found.setdefault(path, OnScreen(path, f"on screen: {kind}, path to {label}"))
    return list(found.values())


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
    if platform == "ios":
        return parse_ios_source(_ios_source(device, _appium.get(f"ios:{device}")))
    if _busy(device):
        raise Busy(f"{device} is in use by a test")
    return parse(dump(device))


class Cache:
    """Completion must not wait ~3s for a dump, so it reads the last one and a stale cache
    refreshes in the background. Off unless asked: it touches the user's device."""

    def __init__(self, fetch=snapshot, ttl: float = 10.0, backoff: float = 60.0, enabled: bool = False) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._backoff = backoff
        self._enabled = enabled
        self._for: str | None = None
        self._found: list[OnScreen] = []
        self._next = float("-inf")
        self._busy = threading.Lock()
        self.problem: str | None = None

    def get(self, preferred: str | None = None) -> list[OnScreen]:
        if preferred != self._for:
            self._for, self._found, self._next = preferred, [], float("-inf")
        if self._enabled and time.monotonic() >= self._next and self._busy.acquire(blocking=False):
            threading.Thread(target=self._refresh, args=(preferred,), daemon=True).start()
        return self._found

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
