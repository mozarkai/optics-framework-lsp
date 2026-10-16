"""A hub session held open for a while, so the Device view's refresh costs a read and not the 7 to 12 s
a session takes to open. Optics opening its own session on the device ends ours, and ours then stays shut."""

from __future__ import annotations

import atexit
import threading
import time
import urllib.error

from . import screen
from .device import DeviceError


class Taken(DeviceError):
    pass


TAKEN = "The device is now in use by another session, so Optics stopped reading it. Try again in a couple of minutes."


class Remote:
    def __init__(self, idle: float = 120.0, cooldown: float = 120.0) -> None:
        self._idle, self._cooldown = idle, cooldown
        self._held: dict[str, list] = {}
        self._taken: dict[str, float] = {}
        self._lock = threading.Lock()
        self._reaper: threading.Thread | None = None

    def _url(self, block: dict) -> str:
        return str(block.get("url")).rstrip("/")

    def _session(self, key: str, block: dict, udid: str) -> str:
        with self._lock:
            if time.monotonic() < self._taken.get(key, 0):
                raise Taken(TAKEN)
            if key not in self._held:
                screen._check_token(block)
                sid = screen.open_session(self._url(block), block, udid)
                self._held[key] = [sid, time.monotonic()]
                self._start_reaper()
                if str((block.get("capabilities") or {}).get("platformName", "")).lower() == "ios":
                    # The picture is most of the time a screenshot takes, and this is the one setting that shrinks it.
                    self._try(lambda: screen._http("POST", f"{self._url(block)}/session/{sid}/appium/settings", {"settings": {"screenshotQuality": 2}}, timeout=60))
            return self._held[key][0]

    @staticmethod
    def _try(action) -> bool:
        try:
            action()
            return True
        except (OSError, ValueError):
            return False

    def _get(self, key: str, block: dict, udid: str, path: str):
        sid = self._session(key, block, udid)
        url = self._url(block)
        try:
            value = screen._http("GET", f"{url}/session/{sid}{path}", timeout=120)["value"]
        except urllib.error.HTTPError:
            self._lost(key, url, sid)
        except OSError as error:
            raise DeviceError(f"The hub did not answer: {error}") from None
        self._held[key][1] = time.monotonic()
        return value

    def _lost(self, key: str, url: str, sid: str):
        """A refused read on a session the hub still knows is a hiccup. One it has dropped means another session took the device."""
        if self._try(lambda: screen._http("GET", f"{url}/session/{sid}", timeout=30)):
            raise DeviceError("The hub refused the read. Try again.")
        with self._lock:
            self._held.pop(key, None)
            self._taken[key] = time.monotonic() + self._cooldown
        raise Taken(TAKEN)

    def source(self, key: str, block: dict, udid: str) -> str:
        return self._get(key, block, udid, "/source")

    def screenshot(self, key: str, block: dict, udid: str) -> str:
        return self._get(key, block, udid, "/screenshot")

    def close(self, key: str, block: dict) -> None:
        with self._lock:
            held = self._held.pop(key, None)
        if held:
            self._try(lambda: screen._http("DELETE", f"{self._url(block)}/session/{held[0]}", timeout=60))

    def close_all(self) -> None:
        for key in list(self._held):
            if block := screen._appium.get(key):
                self.close(key, block)

    def _start_reaper(self) -> None:
        if not self._reaper:
            self._reaper = threading.Thread(target=self._reap, daemon=True)
            self._reaper.start()

    def _reap(self) -> None:
        while True:
            time.sleep(max(1.0, self._idle / 4))
            for key, (sid, used) in list(self._held.items()):
                if time.monotonic() - used > self._idle and (block := screen._appium.get(key)):
                    self.close(key, block)


HELD = Remote()
atexit.register(HELD.close_all)
