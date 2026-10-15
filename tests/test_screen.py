import threading
import time
from pathlib import Path

import pytest

from optics_framework_lsp import screen

LAUNCHER = (Path(__file__).parent / "fixtures" / "uiautomator_launcher.xml").read_text()

DUPES = """<hierarchy>
<node class="android.widget.TextView" text="Next" resource-id="" content-desc="" />
<node class="android.widget.TextView" text="Next" resource-id="" content-desc="" />
<node class="android.widget.Button" text="" resource-id="com.app:id/submit_btn" content-desc="" />
<node class="android.widget.EditText" text="It's &quot;x&quot;" resource-id="" content-desc="" />
<node class="android.widget.FrameLayout" text="" resource-id="" content-desc="" />
</hierarchy>"""


def test_a_real_screen_gives_locators_in_the_form_suites_already_write():
    found = screen.parse(LAUNCHER)
    locators = {s.locator for s in found}

    assert '//android.widget.TextView[@text="Optics Super App"]' in locators
    assert '//android.view.ViewGroup[@resource-id="home-card-9"]' in locators


def test_a_repeated_locator_is_numbered_so_each_matches_one_node():
    locators = [s.locator for s in screen.parse(DUPES)]

    assert '(//android.widget.TextView[@text="Next"])[1]' in locators
    assert '(//android.widget.TextView[@text="Next"])[2]' in locators


def test_resource_id_beats_text_and_a_bare_container_is_left_out():
    found = {s.locator: s for s in screen.parse(DUPES)}

    assert '//android.widget.Button[@resource-id="com.app:id/submit_btn"]' in found
    assert not any("FrameLayout" in locator for locator in found)


def test_a_value_holding_both_quotes_cannot_be_an_xpath_and_is_left_out():
    assert not any("EditText" in s.locator for s in screen.parse(DUPES))


def test_the_cache_answers_at_once_and_refreshes_behind_the_caller():
    gate = threading.Event()
    one = [screen.OnScreen("//a", "d")]

    def fetch(preferred):
        gate.wait(2)
        return one

    cache = screen.Cache(fetch=fetch, ttl=60, enabled=True)
    assert cache.get() == []
    gate.set()
    for _ in range(50):
        if cache.get():
            break
        time.sleep(0.02)
    assert cache.get() == one


def test_a_failing_device_leaves_nothing_rather_than_a_stale_screen():
    calls = iter([[screen.OnScreen("//a", "d")]])

    def fetch(preferred):
        try:
            return next(calls)
        except StopIteration:
            raise screen.DeviceError("gone") from None

    cache = screen.Cache(fetch=fetch, ttl=0, backoff=0, enabled=True)
    for _ in range(100):
        cache.get()
        time.sleep(0.01)
    assert cache.get() == []


def test_a_cache_is_off_unless_asked_for_and_never_runs_the_fetch():
    assert screen.Cache(fetch=lambda p: 1 / 0).get() == []
    assert screen.Cache(fetch=lambda p: 1 / 0, enabled=False).get() == []


def test_a_failed_dump_is_not_retried_until_the_backoff_has_passed():
    calls = []

    def fetch(preferred):
        calls.append(1)
        raise screen.DeviceError("Killed")

    cache = screen.Cache(fetch=fetch, ttl=0, backoff=60, enabled=True)
    for _ in range(20):
        cache.get()
        time.sleep(0.01)
    assert len(calls) == 1


def _config(folder, platform="Android", udid="emulator-5554"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.yaml").write_text(
        f"driver_sources:\n  - appium:\n      capabilities:\n        platformName: {platform}\n        udid: \"{udid}\"\n"
    )


def test_the_device_comes_from_the_nearest_config_up_to_the_project_root(tmp_path):
    _config(tmp_path, udid="emulator-5554")
    (tmp_path / "elements").mkdir()

    assert screen.config_device(tmp_path / "elements", tmp_path) == "android:emulator-5554"


def test_a_config_names_the_platform_and_one_without_a_device_does_not_climb_further(tmp_path):
    _config(tmp_path, udid="emulator-5554")
    _config(tmp_path / "ios", platform="iOS", udid="ABCD-1234")
    _config(tmp_path / "nodevice", udid="")

    assert screen.config_device(tmp_path / "ios", tmp_path) == "ios:ABCD-1234"
    assert screen.config_device(tmp_path / "nodevice", tmp_path) is None
    assert screen.config_device(tmp_path / "missing", tmp_path / "missing") is None


def test_a_broken_config_gives_none(tmp_path):
    (tmp_path / "config.yaml").write_text("driver_sources: [unclosed")
    assert screen.config_device(tmp_path, tmp_path) is None


def test_a_preferred_device_wins_then_the_device_views_pick_then_the_only_one(monkeypatch):
    dumped = []
    monkeypatch.setattr(screen, "dump", lambda serial: dumped.append(serial) or "<hierarchy/>")
    monkeypatch.setattr(screen, "_busy", lambda serial: False)
    monkeypatch.setattr(screen, "_connected", lambda: ["a", "b"])
    monkeypatch.setattr(screen, "_booted", lambda: [])

    monkeypatch.setattr(screen, "selected", lambda: "android:b")
    screen.snapshot("android:a")
    screen.snapshot()
    monkeypatch.setattr(screen, "selected", lambda: "android:gone")
    screen.snapshot()
    monkeypatch.setattr(screen, "_connected", lambda: ["only"])
    screen.snapshot()

    assert dumped == ["a", "b", "only"]


def test_a_new_preferred_device_drops_the_screen_of_the_old_one():
    def fetch(preferred):
        time.sleep(0.2 if preferred == "b" else 0)
        return [screen.OnScreen(f"//{preferred}", "d")]

    cache = screen.Cache(fetch=fetch, ttl=60, enabled=True)
    cache.get("a")
    for _ in range(50):
        if cache.get("a"):
            break
        time.sleep(0.02)
    assert [s.locator for s in cache.get("a")] == ["//a"]
    assert cache.get("b") == []


def test_the_environment_beats_the_config_and_neither_falls_through(tmp_path, monkeypatch):
    from optics_framework_lsp.server import _device_hint

    _config(tmp_path, udid="from-config")
    elements = tmp_path / "elements" / "elements.csv"
    elements.parent.mkdir()
    uri, folder = elements.as_uri(), tmp_path.as_uri()

    monkeypatch.delenv("OPTICS_DEVICE", raising=False)
    assert _device_hint(uri, folder) == "android:from-config"
    monkeypatch.setenv("OPTICS_DEVICE", "from-env")
    assert _device_hint(uri, folder) == "from-env"


@pytest.mark.parametrize(
    "counts, busy", [(b"0\n0\n", False), (b"1\n0\n", True), (b"0\n1\n", True), (b"", False)]
)
def test_the_device_is_busy_when_an_instrumentation_or_the_uiautomator2_server_runs(monkeypatch, counts, busy):
    monkeypatch.setattr(screen, "_run", lambda command: counts)
    assert screen._busy("emulator-5554") is busy


def test_a_busy_device_is_not_dumped_and_the_screen_already_known_is_kept(monkeypatch):
    dumped = []
    monkeypatch.setattr(screen, "_busy", lambda serial: bool(dumped))
    monkeypatch.setattr(screen, "dump", lambda serial: dumped.append(serial) or '<hierarchy><node class="a.B" text="Hi" /></hierarchy>')
    cache = screen.Cache(fetch=screen.snapshot, ttl=0, enabled=True)

    for _ in range(100):
        cache.get("android:emulator-5554")
        time.sleep(0.01)

    assert len(dumped) == 1
    assert [s.locator for s in cache.get("android:emulator-5554")] == ['//a.B[@text="Hi"]']


WDA = (Path(__file__).parent / "fixtures" / "wda_super_app.xml").read_text()






def test_a_bare_device_id_is_matched_to_the_platform_it_belongs_to(monkeypatch):
    monkeypatch.setattr(screen, "_connected", lambda: ["emulator-5554", "192.168.1.5:5555"])
    monkeypatch.setattr(screen, "_booted", lambda: ["SIM-UDID"])

    assert screen._resolve("emulator-5554") == ("android", "emulator-5554")
    assert screen._resolve("192.168.1.5:5555") == ("android", "192.168.1.5:5555")
    assert screen._resolve("SIM-UDID") == ("ios", "SIM-UDID")
    assert screen._resolve("ios:SIM-UDID") == ("ios", "SIM-UDID")
    with pytest.raises(screen.DeviceError, match="not a connected"):
        screen._resolve("gone")


def test_a_missing_tool_is_kept_as_the_problem_until_a_read_works():
    reads = iter([screen.Missing("Appium is not running"), []])

    def fetch(preferred):
        item = next(reads)
        if isinstance(item, Exception):
            raise item
        return item

    cache = screen.Cache(fetch=fetch, ttl=0, backoff=0, enabled=True)
    for _ in range(100):
        cache.get("ios:U")
        if cache.problem:
            break
        time.sleep(0.01)
    assert cache.problem == "Appium is not running"
    for _ in range(100):
        cache.get("ios:U")
        if not cache.problem:
            break
        time.sleep(0.01)
    assert cache.problem is None


def test_an_android_device_without_adb_says_so(monkeypatch):
    monkeypatch.setattr(screen, "_adb", lambda: None)

    with pytest.raises(screen.Missing, match="adb not found"):
        screen.snapshot("android:emulator-5554")



def test_a_problem_is_shown_once_however_often_completion_asks(monkeypatch):
    from optics_framework_lsp import server

    class Client:
        sent = []

        def window_show_message(self, params):
            self.sent.append(params.message)

    monkeypatch.setattr(server, "_reported", set())
    monkeypatch.setattr(server.SCREEN, "problem", "Appium is not running")
    client = Client()
    for _ in range(3):
        server._report_screen_problem(client)

    assert client.sent == ["Optics screen suggestions: Appium is not running"]




def test_an_ios_screen_offers_the_names_and_the_path_from_the_application_down():
    found = {s.locator: s for s in screen.parse_ios_source(WDA)}
    paths = [locator for locator in found if locator.startswith("//")]

    assert "home-card-1" in found
    assert found["home-card-1"].detail == "on screen: Other, name home-card-1"
    assert all(p.startswith('//XCUIElementTypeApplication[@name="QuickTest"]/XCUIElementTypeWindow/') for p in paths)
    assert max(p.count("/") for p in paths) > 15
    assert "QuickTest" not in found


def test_a_path_numbers_only_the_steps_that_share_a_type_with_a_sibling():
    xml = (
        '<AppiumAUT><XCUIElementTypeApplication name="App"><XCUIElementTypeWindow>'
        '<XCUIElementTypeOther name="a"/><XCUIElementTypeOther name="b"/><XCUIElementTypeButton name="c"/>'
        "</XCUIElementTypeWindow></XCUIElementTypeApplication></AppiumAUT>"
    )
    paths = {s.detail.rsplit(" ", 1)[-1]: s.locator for s in screen.parse_ios_source(xml) if s.locator.startswith("//")}

    assert paths["a"] == '//XCUIElementTypeApplication[@name="App"]/XCUIElementTypeWindow/XCUIElementTypeOther[1]'
    assert paths["c"] == '//XCUIElementTypeApplication[@name="App"]/XCUIElementTypeWindow/XCUIElementTypeButton'


def test_what_is_off_screen_or_has_no_name_is_left_out():
    xml = (
        '<AppiumAUT><XCUIElementTypeApplication name="App"><XCUIElementTypeOther name="seen" visible="true"/>'
        '<XCUIElementTypeOther name="hidden" visible="false"/><XCUIElementTypeOther/></XCUIElementTypeApplication></AppiumAUT>'
    )
    assert [s.locator for s in screen.parse_ios_source(xml) if not s.locator.startswith("//")] == ["seen"]


def test_a_webdriveragent_that_is_already_running_is_read_without_opening_a_session(monkeypatch):
    monkeypatch.setattr(screen, "_wda_source", lambda port: WDA if port == 8100 else None)
    monkeypatch.setattr(screen, "_appium_source", lambda *args: 1 / 0)

    assert screen._ios_source("U", None) == WDA


def test_the_wda_port_comes_from_the_suites_capabilities(monkeypatch):
    seen = []
    monkeypatch.setattr(screen, "_wda_source", lambda port: seen.append(port) or WDA)

    screen._ios_source("U", {"capabilities": {"wdaLocalPort": 8201}})

    assert seen == [8201]


def test_with_no_webdriveragent_a_session_is_opened_with_the_suites_capabilities_and_closed(monkeypatch):
    calls = []

    def http(method, url, body=None, timeout=15):
        calls.append((method, url.replace("http://127.0.0.1:4723/wd/hub", ""), body))
        return {"value": {"sessionId": "S1"} if method == "POST" else WDA if url.endswith("/source") else None}

    monkeypatch.setattr(screen, "_wda_source", lambda port: None)
    monkeypatch.setattr(screen, "_http", http)
    block = {"capabilities": {"platformName": "iOS", "udid": "U", "bundleId": "com.x"}}

    assert screen._ios_source("U", block) == WDA
    assert [(m, u) for m, u, _ in calls] == [("POST", "/session"), ("GET", "/session/S1/source"), ("DELETE", "/session/S1")]
    assert calls[0][2] == {"capabilities": {"alwaysMatch": {"platformName": "iOS", "appium:udid": "U", "appium:bundleId": "com.x"}}}


def test_a_session_that_fails_to_read_is_still_closed(monkeypatch):
    calls = []

    def http(method, url, body=None, timeout=15):
        calls.append(method)
        if url.endswith("/source"):
            raise OSError("reset")
        return {"value": {"sessionId": "S1"}}

    monkeypatch.setattr(screen, "_wda_source", lambda port: None)
    monkeypatch.setattr(screen, "_http", http)

    with pytest.raises(OSError):
        screen._ios_source("U", None)
    assert calls == ["POST", "GET", "DELETE"]


def test_an_appium_that_is_not_running_says_so(monkeypatch):
    monkeypatch.setattr(screen, "_wda_source", lambda port: None)
    monkeypatch.setattr(screen, "_http", lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))

    with pytest.raises(screen.Missing, match="Appium is not running at http://127.0.0.1:4723/wd/hub"):
        screen._ios_source("U", None)


def test_a_remote_appium_hub_is_not_opened_for_suggestions(monkeypatch):
    monkeypatch.setattr(screen, "_wda_source", lambda port: 1 / 0)
    monkeypatch.setattr(screen, "_http", lambda *a, **k: 1 / 0)

    with pytest.raises(screen.Missing, match="remote"):
        screen._ios_source("U", {"url": "https://appium-hub.example.com/wd/hub"})


def test_the_config_keeps_the_appium_settings_for_the_device_it_names(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "driver_sources:\n  - appium:\n      url: http://127.0.0.1:4725/wd/hub\n      capabilities:\n"
        "        platformName: iOS\n        udid: SIM\n        wdaLocalPort: 8201\n"
    )

    assert screen.config_device(tmp_path, tmp_path) == "ios:SIM"
    assert screen._appium["ios:SIM"]["url"] == "http://127.0.0.1:4725/wd/hub"


def test_an_ios_snapshot_reads_the_screen_through_appium(monkeypatch):
    monkeypatch.setattr(screen, "_ios_source", lambda udid, block: WDA)

    assert "home-card-1" in [s.locator for s in screen.snapshot("ios:SIM")]
