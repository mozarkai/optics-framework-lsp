from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from .device import DeviceError, _adb, _android, _run, selected

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
    raw = _run([_adb() or "adb", "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"]).decode(errors="replace")
    end = raw.find("</hierarchy>")
    if end < 0:
        raise DeviceError(raw.strip() or "uiautomator returned no hierarchy")
    return raw[: end + len("</hierarchy>")]


def _connected() -> list[str]:
    adb = _adb()
    return [d["id"].split(":", 1)[1] for d in _android(adb)] if adb else []


def _udid(config: object) -> str | None:
    for source in (config.get("driver_sources") if isinstance(config, dict) else None) or []:
        caps = ((source or {}).get("appium") or {}).get("capabilities") or {}
        if str(caps.get("platformName", "")).lower() == "android":
            return str(caps.get("appium:udid") or caps.get("udid") or "") or None
    return None


def config_serial(start: Path, stop: Path) -> str | None:
    for folder in (start, *start.parents):
        if (file := folder / "config.yaml").is_file():
            try:
                return _udid(yaml.safe_load(file.read_text()))
            except (OSError, yaml.YAMLError):
                return None
        if folder == stop:
            break
    return None


def _chosen() -> str | None:
    connected = _connected()
    kind, _, serial = (selected() or "").partition(":")
    if kind == "android" and serial in connected:
        return serial
    return connected[0] if len(connected) == 1 else None


class Busy(DeviceError):
    pass


def _busy(serial: str) -> bool:
    """Appium and Espresso run as an instrumentation, uiautomator2 3 as its own process. Not
    `io.appium.settings`, which outlives the session."""
    check = "dumpsys activity | grep -c ActiveInstrumentation; ps -A -o ARGS | grep -c '[c]om.wetest.uia2.Main'; true"
    counts = _run([_adb() or "adb", "-s", serial, "shell", check]).decode().split()
    return any(count != "0" for count in counts)


def snapshot(preferred: str | None = None) -> list[OnScreen]:
    serial = preferred or _chosen()
    if not serial:
        return []
    if _busy(serial):
        raise Busy(f"{serial} is in use by a test")
    return parse(dump(serial))


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
        except Busy:
            found = self._found
        except Exception:
            found = []
            wait = self._backoff
        finally:
            if preferred == self._for:
                self._found = found
            self._next = time.monotonic() + wait
            self._busy.release()
