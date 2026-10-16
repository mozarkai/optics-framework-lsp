import asyncio
import time
import urllib.error

import pytest

from optics_framework_lsp import remote, screen
from optics_framework_lsp.remote import Remote, Taken

BLOCK = {"url": "https://hub.example.com/wd/hub", "capabilities": {"platformName": "Android", "deviceName": "A04", "udid": "R5"}}


class Hub:
    """A hub that answers for the sessions it has opened, and refuses a read on one it has dropped."""

    def __init__(self):
        self.calls, self.dropped, self.opened = [], set(), 0

    def open(self, url, block, udid):
        self.opened += 1
        return f"S{self.opened}"

    def http(self, method, url, body=None, timeout=15):
        self.calls.append((method, url.split("/wd/hub")[-1], body))
        sid = url.split("/session/")[-1].split("/")[0] if "/session/" in url else ""
        if sid in self.dropped:
            raise urllib.error.HTTPError(url, 404, "invalid session id", {}, None)
        return {"value": "<hierarchy/>" if url.endswith("/source") else "PNG" if url.endswith("/screenshot") else None}


@pytest.fixture
def hub(monkeypatch):
    hub = Hub()
    monkeypatch.setattr(screen, "open_session", hub.open)
    monkeypatch.setattr(screen, "_http", hub.http)
    return hub


def test_a_session_is_opened_once_and_reused_for_every_read(hub):
    held = Remote()

    assert held.source("android:R5", BLOCK, "R5") == "<hierarchy/>"
    assert held.screenshot("android:R5", BLOCK, "R5") == "PNG"
    held.source("android:R5", BLOCK, "R5")

    assert hub.opened == 1


def test_an_iphone_is_asked_for_smaller_screenshots_once(hub):
    ios = {"url": BLOCK["url"], "capabilities": {"platformName": "iOS", "udid": "U"}}
    held = Remote()
    held.screenshot("ios:U", ios, "U")
    held.screenshot("ios:U", ios, "U")

    posts = [c for c in hub.calls if c[0] == "POST"]
    assert [p[2] for p in posts] == [{"settings": {"screenshotQuality": 2}}]


def test_a_session_the_hub_dropped_means_another_session_took_the_device_and_it_is_left_alone(hub):
    held = Remote(cooldown=60)
    held.source("android:R5", BLOCK, "R5")
    hub.dropped.add("S1")

    with pytest.raises(Taken, match="in use by another session"):
        held.source("android:R5", BLOCK, "R5")
    before = len(hub.calls)
    with pytest.raises(Taken):
        held.source("android:R5", BLOCK, "R5")

    assert len(hub.calls) == before and hub.opened == 1


def test_after_the_cooldown_a_new_session_may_be_opened(hub):
    held = Remote(cooldown=0.05)
    held.source("android:R5", BLOCK, "R5")
    hub.dropped.add("S1")
    with pytest.raises(Taken):
        held.source("android:R5", BLOCK, "R5")
    time.sleep(0.1)

    assert held.source("android:R5", BLOCK, "R5") == "<hierarchy/>"
    assert hub.opened == 2


def test_a_refused_read_on_a_session_the_hub_still_knows_is_only_a_hiccup(hub, monkeypatch):
    held = Remote()
    held.source("android:R5", BLOCK, "R5")
    real = hub.http

    def flaky(method, url, body=None, timeout=15):
        if url.endswith("/source"):
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)
        return real(method, url, body, timeout)

    monkeypatch.setattr(screen, "_http", flaky)

    with pytest.raises(remote.DeviceError, match="refused the read"):
        held.source("android:R5", BLOCK, "R5")
    monkeypatch.setattr(screen, "_http", real)
    held.source("android:R5", BLOCK, "R5")
    assert hub.opened == 1


def test_an_idle_session_is_closed_so_the_device_is_not_held_for_ever(hub, monkeypatch):
    monkeypatch.setitem(screen._appium, "android:R5", BLOCK)
    held = Remote(idle=0.2)
    held.source("android:R5", BLOCK, "R5")
    for _ in range(50):
        if any(c[0] == "DELETE" for c in hub.calls):
            break
        time.sleep(0.1)

    assert ("DELETE", "/session/S1", None) in hub.calls


def test_an_expired_token_stops_it_before_a_session_is_opened(hub):
    import base64
    import json

    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    expired = {"url": BLOCK["url"], "capabilities": {"mozark:options": {"secret": f"{part({})}.{part({'exp': 1})}.sig"}}}

    with pytest.raises(screen.Missing, match="expired"):
        Remote().source("android:R5", expired, "R5")
    assert hub.opened == 0


def test_the_device_view_is_offered_the_suites_hub_device(monkeypatch):
    from optics_framework_lsp import server

    monkeypatch.setitem(screen._appium, "android:R5", {**BLOCK, "url": "https://hub.example.com/wd/hub"})
    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: "android:R5")

    class Client:
        def folder_of(self, uri):
            return "file:///w"

    assert server.remote_device(Client(), "file:///w/e.csv") == {"id": "remote:android:R5", "name": "A04 (hub)", "platform": "android"}
    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: "android:LOCAL")
    assert server.remote_device(Client(), "file:///w/e.csv") is None


def test_the_device_views_read_returns_the_picture_or_why_not(monkeypatch):
    from optics_framework_lsp import server

    monkeypatch.setitem(screen._appium, "android:R5", BLOCK)
    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: "android:R5")
    monkeypatch.setattr(screen, "is_remote", lambda device: True)
    monkeypatch.setattr(remote.HELD, "screenshot", lambda key, block, udid: "PNGDATA")

    class Client:
        def folder_of(self, uri):
            return "file:///w"

    run = lambda: asyncio.run(server.remote_screen(Client(), "file:///w/e.csv"))  # noqa: E731

    assert run() == {"png": "PNGDATA"}

    def taken(*args):
        raise Taken("in use")

    monkeypatch.setattr(remote.HELD, "screenshot", taken)
    assert run() == {"error": "in use"}


def test_the_device_view_starts_on_the_device_the_suite_names(monkeypatch):
    from optics_framework_lsp import server

    monkeypatch.setitem(screen._appium, "android:R5", {**BLOCK, "url": "https://hub.example.com/wd/hub"})

    class Client:
        def folder_of(self, uri):
            return "file:///w"

    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: "android:R5")
    assert server.suite_device(Client(), "file:///w/e.csv") == "remote:android:R5"
    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: "android:LOCAL")
    assert server.suite_device(Client(), "file:///w/e.csv") == "android:LOCAL"
    monkeypatch.setattr(server, "_device_hint", lambda uri, folder: None)
    assert server.suite_device(Client(), "file:///w/e.csv") is None
