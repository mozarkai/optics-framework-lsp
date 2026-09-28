# What each keyword becomes in a uiautomator2 script, and why the rest cannot.
#
# Every keyword in the catalog appears once, in EMIT or in UNSUPPORTED — a test asserts
# that, which is why this table lives beside `keywords.py` rather than in the framework:
# optics-framework's own `helper/generate.py` keeps two hand-copied keyword lists and both
# drifted to 32 of 51 without anything noticing.

from __future__ import annotations

import re

NAME = "uiautomator2"
EXTENSION = ".py"

from ..locators import REFUSED, kind


def func_name(text: str) -> str:
    """A block name as a python identifier, lowercased and joined as the framework does."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip().lower()).strip("_")
    return cleaned if cleaned and not cleaned[0].isdigit() else f"m_{cleaned}"


def literal(value: str) -> str:
    return repr(value)


def element_ref(name: str) -> str:
    return f"ELEMENTS[{name!r}]"


def var_ref(name: str) -> str:
    return f"VARS[{name!r}]"


def vet_locator(locator: str) -> str | None:
    """Why this locator has no form here, or None.

    Four of the framework's kinds have no native equivalent at all. `_find` splits a path
    from an accessibility id at run time, so nothing else needs deciding here -- except a
    path naming iOS types, which this device will never hold.
    """
    found = kind(locator)
    if found in REFUSED:
        return REFUSED[found]
    if found == "xpath" and "XCUIElementType" in locator:
        return "names XCUIElementType, which is an ios class and not an android one"
    return None


def _one(call: str):
    return lambda p: [call.format(*p)]


def _els(p: list[str]) -> str:
    """Assert keywords take one comma-separated string of locators, not one locator — the
    same split `assert_elements` makes on the value."""
    return f"_split({p[0]})"


def _to(p: list[str], i: int) -> str:
    return f"float({p[i]})" if len(p) > i and p[i] else "30"


def _rule(p: list[str], i: int) -> str:
    return p[i] if len(p) > i and p[i] else "'any'"


# keyword -> (how many params the translation reads, what it emits). Paired so a keyword
# cannot have an arity and no emitter, or the reverse.
EMIT: dict[str, tuple[int, object]] = {
    # lifecycle
    "launch app": (0, _one("d.app_start(PACKAGE, ACTIVITY, stop=True)")),
    "launch other app": (1, _one("d.app_start({0})")),
    "close and terminate app": (0, _one("d.app_stop(PACKAGE)")),
    "force terminate app": (1, _one("d.app_stop({0})")),
    "quit": (0, _one("d.app_stop(PACKAGE)")),
    "get app version": (1, _one('VARS["app_version"] = d.app_info({0})["versionName"]')),
    # pressing
    "press element": (1, _one("_find(d, {0}).click()")),
    "press element with index": (2, _one("_at(d, {0}, int({1})).click()")),
    "detect and press": (2, lambda p: [f"_press_if(d, {p[0]}, {_to(p, 1)})"]),
    "press by coordinates": (2, _one("d.click(int({0}), int({1}))")),
    "press by percentage": (2, _one("d.click(float({0}) / 100, float({1}) / 100)")),
    "press checkbox": (1, _one("_find(d, {0}).click()")),
    "press radio button": (1, _one("_find(d, {0}).click()")),
    "press keycode": (1, _one("d.press(int({0}))")),
    # text
    "enter text": (2, _one("_find(d, {0}).set_text({1})")),
    "enter number": (2, _one("_find(d, {0}).set_text(str({1}))")),
    "enter text direct": (1, _one("d.send_keys({0})")),
    "enter text using keyboard": (1, _one("d.send_keys({0})")),
    # set_text("") is the clear that works on an xpath selector too; clear_text does not.
    "clear element text": (1, _one('_find(d, {0}).set_text("")')),
    "get text": (1, _one('VARS["last_text"] = _find(d, {0}).get_text()')),
    # assertions
    "assert presence": (3, lambda p: [f"assert _wait(d, {_els(p)}, {_to(p, 1)}, {_rule(p, 2)})"]),
    "assert visibility": (
        3,
        lambda p: [f"assert _wait_visible(d, {_els(p)}, {_to(p, 1)}, {_rule(p, 2)})"],
    ),
    "validate element": (2, lambda p: [f"_record(_wait(d, {_els(p)}, {_to(p, 1)}, 'any'))"]),
    "validate screen": (
        2,
        lambda p: [f"_record(_wait(d, {_els(p)}, {_to(p, 1)}, 'any'))"],
    ),
    "is element": (3, lambda p: [f"_is(d, {p[0]}, {p[1]}, {_to(p, 2)})"]),
    "assert equality": (2, _one("assert {0} == {1}")),
    # movement
    "scroll": (1, _one("d.swipe_ext({0})")),
    "scroll from element": (3, _one("_swipe_from(d, {0}, {1}, int({2}))")),
    "scroll until element appears": (3, _one("_swipe_until(d, {0}, {1}, {2})")),
    "swipe until element appears": (3, _one("_swipe_until(d, {0}, {1}, {2})")),
    "swipe from element": (3, _one("_swipe_from(d, {0}, {1}, int({2}))")),
    "swipe": (4, _one("_swipe_at(d, int({0}), int({1}), {2}, int({3}))")),
    "swipe by percentage": (4, _one("_swipe_pct(d, float({0}), float({1}), {2}, int({3}))")),
    "swipe seekbar to right android": (1, _one("_seekbar_right(d, {0})")),
    "select dropdown option": (3, _one("_select(d, {0}, {1})")),
    # everything else
    "sleep": (1, _one("time.sleep(float({0}))")),
    "capture screenshot": (0, _one("d.screenshot(_shot_path())")),
    "capture pagesource": (0, _one("_write_pagesource(d)")),
    # resolved at generation time — a module reference is a call to the function it made.
    "execute module": (1, _one("{0}(d)")),
}

# Why a keyword produces no code. These reach the caller's report verbatim, so each says
# what would have to change rather than only that it did not work.
UNSUPPORTED: dict[str, str] = {
    "condition": "branch targets are not in the parse payload; expose them and this emits an if",
    "run loop": "loop target and count are not in the parse payload",
    "date evaluate": "parameter semantics are not exposed by parse",
    "evaluate": "needs optics' own expression evaluator over the variable store",
    "execute script": "runs an arbitrary script; nothing to translate",
    "invoke api": "needs an http runtime and a variable store the generated script has not got",
    "read data": "needs optics' csv query grammar reimplemented",
    "get screen elements": "returns data a generated script has nowhere to put",
    "get interactive elements": "returns data a generated script has nowhere to put",
    "start appium session": "uiautomator2 has no driver session; connect is the whole setup",
    "initialise setup": "the generated harness already does this",
    "get driver session id": "uiautomator2 has no session id",
}


# The helpers the emitted calls stand on, inlined so one generated file is the whole
# deliverable. `_wait` polls every 200ms; optics' own locate retries on a ~1.8s interval,
# which is where most of the wall-clock difference between the two lives.
_PRELUDE = '''\
import sys
import time
from pathlib import Path

import uiautomator2 as u2

SERIAL = {serial!r}
PACKAGE = {package!r}
ACTIVITY = {activity!r}

VARS = {{}}
SOFT = []

OUT = Path(__file__).parent / "output"


def _selector(d, locator):
    """A locator is an xpath when it reads like one, else an accessibility id — the same
    split `determine_element_type` makes, so a name resolves here as it does under optics."""
    if locator.startswith(("//", "(")):
        return d.xpath(locator)
    return d(description=locator)


def _locators(value):
    """An element is a list of fallbacks; a variable or a literal is one locator."""
    return [value] if isinstance(value, str) else value


def _now(d, value):
    """The first locator that matches right now, in the suite's order, or None."""
    for locator in _locators(value):
        selector = _selector(d, locator)
        if selector.exists:
            return selector
    return None


def _find(d, value):
    """One locator is handed to uiautomator2, which waits for it on use. Several are polled
    together inside that same wait, so a fallback costs no extra time on a miss."""
    locators = _locators(value)
    if len(locators) == 1:
        return _selector(d, locators[0])
    deadline = time.time() + d.settings["wait_timeout"]
    while True:
        selector = _now(d, locators)
        if selector is not None:
            return selector
        if time.time() >= deadline:
            raise AssertionError("none of %r matched" % (locators,))
        time.sleep(0.2)


def _at(d, value, index):
    locators = _locators(value)
    for locator in locators[:-1]:
        hits = d.xpath(locator).all() if locator.startswith(("//", "(")) else d(description=locator)
        if len(hits) > index:
            return hits[index]
    last = locators[-1]
    if last.startswith(("//", "(")):
        return d.xpath(last).all()[index]
    return d(description=last)[index]


def _split(value):
    """Assert keywords take one comma-separated string of locators. An element is already
    its own list of fallbacks, and counts as one entry."""
    if not isinstance(value, str):
        return [value]
    return [part.strip() for part in value.split(",") if part.strip()]


def _wait(d, values, timeout, rule="any"):
    deadline = time.time() + timeout
    while True:
        hits = [_now(d, value) is not None for value in values]
        if any(hits) if rule == "any" else all(hits):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def _wait_visible(d, values, timeout, rule="any"):
    """Present is in the tree; visible is on screen, which uiautomator2 reports as a
    visibleBounds with area."""
    deadline = time.time() + timeout
    while True:
        hits = []
        for value in values:
            element = _now(d, value)
            box = element.info.get("visibleBounds") if element is not None else None
            hits.append(bool(box) and box["right"] > box["left"] and box["bottom"] > box["top"])
        if any(hits) if rule == "any" else all(hits):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def _press_if(d, value, timeout):
    """Tolerant press: a miss is not a failure, as `detect_and_press` treats it."""
    if _wait(d, [value], float(timeout)):
        _now(d, value).click()


def _record(ok):
    """A soft check: recorded, never raised, the way validate_* behaves."""
    SOFT.append(bool(ok))


def _is(d, value, state, timeout):
    state = str(state).strip().lower()
    if state in ("visible", "present", "exists"):
        return _wait(d, [value], float(timeout))
    if state == "enabled":
        return _wait(d, [value], float(timeout)) and _now(d, value).info["enabled"]
    if state in ("invisible", "absent", "gone"):
        return not _wait(d, [value], float(timeout))
    raise ValueError("unknown element state: " + state)


def _bounds(d, locator):
    return _find(d, locator).info["bounds"]


_DIRECTIONS = {{"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}}


def _swipe_from(d, locator, direction, length):
    box = _bounds(d, locator)
    cx = (box["left"] + box["right"]) // 2
    cy = (box["top"] + box["bottom"]) // 2
    dx, dy = _DIRECTIONS[direction.lower()]
    d.swipe(cx, cy, cx + dx * length, cy + dy * length)


def _swipe_at(d, x, y, direction, length):
    dx, dy = _DIRECTIONS[direction.lower()]
    d.swipe(x, y, x + dx * length, y + dy * length)


def _swipe_pct(d, px, py, direction, length):
    width, height = d.window_size()
    _swipe_at(d, int(width * px / 100), int(height * py / 100), direction, length)


def _swipe_until(d, value, direction, timeout):
    deadline = time.time() + float(timeout)
    while _now(d, value) is None:
        if time.time() >= deadline:
            raise AssertionError("never appeared: %r" % (value,))
        d.swipe_ext(direction.lower())


def _seekbar_right(d, locator):
    box = _bounds(d, locator)
    cy = (box["top"] + box["bottom"]) // 2
    d.drag(box["left"], cy, box["right"], cy)


def _select(d, locator, option):
    _find(d, locator).click()
    d(text=option).click()


def _shot_path():
    OUT.mkdir(parents=True, exist_ok=True)
    return str(OUT / ("screenshot-%d.png" % int(time.time() * 1000)))


def _write_pagesource(d):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("pagesource-%d.xml" % int(time.time() * 1000))
    path.write_text(d.dump_hierarchy(), encoding="utf-8")
'''

_MAIN = '''\

def main():
    d = u2.connect(SERIAL)
    failed = 0
    for name, case in sorted(globals().items()):
        if not name.startswith("test_") or not callable(case):
            continue
        try:
            case(d)
        except Exception as error:
            failed += 1
            print("FAIL %s: %s" % (name, error))
        else:
            print("PASS %s" % name)
    if SOFT and not all(SOFT):
        print("soft checks: %d of %d passed" % (sum(SOFT), len(SOFT)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
'''


def render(config: dict, elements: dict[str, list[str]], modules: list, cases: list) -> str:
    """One module-level function per module, one per test case, and a runner."""
    out = [
        "# Generated by `optics-lsp generate`. Do not edit — regenerate instead.",
        "#",
        "# This talks to the device directly. An element's locators are tried in order, but",
        "# what optics does once they all miss (ocr, image templates, self-heal) is not here:",
        "# the step fails.",
        "",
        _PRELUDE.format(
            serial=config.get("serial", ""),
            package=config.get("package", ""),
            activity=config.get("activity", ""),
        ),
        "",
        "ELEMENTS = {",
        # One locator stays a string, so a suite without fallbacks reads as it always did.
        *[
            f"    {name!r}: {locators[0] if len(locators) == 1 else locators!r},"
            for name, locators in elements.items()
        ],
        "}",
        "",
        "",
        "# Modules",
        "",
    ]
    for name, body in modules:
        out += [f"def {func_name(name)}(d):", f"    {name!r}"]
        out += [f"    {line}" for line in body] or ["    pass"]
        out += [""]
    out += ["# Test cases", ""]
    for name, body in cases:
        out += [f"def test_{func_name(name)}(d):", f"    {name!r}"]
        out += [f"    {line}" for line in body] or ["    pass"]
        out += [""]
    return "\n".join(out) + _MAIN
