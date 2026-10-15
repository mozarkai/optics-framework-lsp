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

    assert screen.config_serial(tmp_path / "elements", tmp_path) == "emulator-5554"


def test_a_config_for_ios_or_without_a_device_gives_none_and_does_not_climb_further(tmp_path):
    _config(tmp_path, udid="emulator-5554")
    _config(tmp_path / "ios", platform="iOS", udid="ABCD-1234")

    assert screen.config_serial(tmp_path / "ios", tmp_path) is None
    assert screen.config_serial(tmp_path / "missing", tmp_path / "missing") is None


def test_a_broken_config_gives_none(tmp_path):
    (tmp_path / "config.yaml").write_text("driver_sources: [unclosed")
    assert screen.config_serial(tmp_path, tmp_path) is None


def test_a_preferred_device_wins_then_the_device_views_pick_then_the_only_one(monkeypatch):
    dumped = []
    monkeypatch.setattr(screen, "dump", lambda serial: dumped.append(serial) or "<hierarchy/>")
    monkeypatch.setattr(screen, "_busy", lambda serial: False)
    monkeypatch.setattr(screen, "_connected", lambda: ["a", "b"])

    monkeypatch.setattr(screen, "selected", lambda: "android:b")
    screen.snapshot("a")
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

    monkeypatch.delenv("OPTICS_ANDROID_SERIAL", raising=False)
    assert _device_hint(uri, folder) == "from-config"
    monkeypatch.setenv("OPTICS_ANDROID_SERIAL", "from-env")
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
        cache.get("emulator-5554")
        time.sleep(0.01)

    assert len(dumped) == 1
    assert [s.locator for s in cache.get("emulator-5554")] == ['//a.B[@text="Hi"]']
