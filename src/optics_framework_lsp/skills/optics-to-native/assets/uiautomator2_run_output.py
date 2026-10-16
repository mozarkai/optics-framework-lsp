# pyright: reportUndefinedVariable=false
# Android step 7 (references/run-output.md): copy the three parts into the script built from
# uiautomator2_example.py. This file is not run on its own. Replace the ERRORS entries with the
# suite's error definitions (an empty dict when it has none).

# --- Part 1: imports to add, and the settings that replace `OUT = ...` ---
# Put these with the script's other imports; `ast`, `csv`, `io` and `re` go there too when the
# flow-control or data patterns use them.

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime

WAIT_TIMEOUT = float(os.environ.get("OPTICS_WAIT_TIMEOUT", "20"))
POLL_INTERVAL = float(os.environ.get("OPTICS_POLL_INTERVAL", "0.2"))
STEP_DELAY = float(os.environ.get("OPTICS_STEP_DELAY", "0.1"))

OUT = Path(os.environ.get("EXEC_OUTPUT", "output"))


# --- Part 2: helpers, after the runtime helpers and before ELEMENTS ---

ERRORS = {
    'E_SESSION': {'match': 'Session expired', 'description': 'Kicked back to the login screen', 'severity': 'high'},
}
SESSION = os.environ.get("SESSION_ID") or datetime.now().strftime("%Y%m%d%H%M%S")
DETECTED = []
RESULTS = []
CASE = {}
AT = ""


def _stamp():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


def _seconds(start):
    return "%.6f" % (time.time() - start)


def _origin(where):
    global AT
    AT = where
    time.sleep(STEP_DELAY)


# A screenshot is evidence, never a reason to fail a step: the app may be closed by then.
def _post(d, keyword):
    if os.environ.get("ENABLE_POST_SCREENSHOT", "1").strip().lower() in ("0", "false", "no"):
        return
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        d.screenshot(str(OUT / ("post-%s-%s.jpg" % (datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f"), keyword))))
    except Exception:
        pass


def _page_text(d):
    values = []
    for node in ET.fromstring(d.dump_hierarchy()).iter():
        for key in ("text", "content-desc", "label", "value", "hint", "name"):
            if node.get(key):
                values.append(node.get(key))
    return " ".join(values).lower()


def _detect(d, case_name):
    text = _page_text(d)
    found = []
    for code, error in ERRORS.items():
        if error["match"].lower() in text:
            on = "match_string"
        elif code.lower() in text:
            on = "code"
        else:
            continue
        found.append({"error_code": code, "matched_on": on, "match_string": error["match"],
                      "description": error["description"], "severity": error["severity"],
                      "detected_at": "end_of_test", "test_case": case_name})
    if found:
        DETECTED.extend(found)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / ("detected_errors_%s.json" % SESSION)).write_text(
            json.dumps({"timestamp": _stamp()[:19], "detected": DETECTED}, indent=2), encoding="utf-8")
    return found


# One call per module in a test function; a step after the failing one is recorded, not run.
def _step(d, name, module, owner):
    began = time.time()
    entry = {"name": name, "status": "PASS", "type": "step", "start": _stamp(), "end": "",
             "duration": "", "testSuite": "Test Cases", "testCase": CASE["name"],
             "owner": "OpticsKeywords." + owner, "subSteps": []}
    if CASE["failed"]:
        entry["status"] = "NOT RUN"
    else:
        try:
            module(d)
        except Exception as error:
            entry["status"] = "FAIL" if isinstance(error, AssertionError) else "ERROR"
            CASE["failed"] = True
            CASE["status"] = entry["status"]
            CASE["reason"] = "%s: %s" % (AT, error) if AT else str(error)
    entry["end"] = _stamp()
    entry["duration"] = _seconds(began)
    CASE["steps"].append(entry)


def _run_case(d, case, number):
    global AT
    AT = ""
    began = time.time()
    CASE.clear()
    CASE.update(name=case.__doc__, failed=False, status="PASS", steps=[],
                reason="Test completed successfully")
    start = _stamp()
    case(d)
    found = _detect(d, case.__doc__)
    if found:
        CASE["status"] = "FAIL"
        CASE["reason"] = "; ".join("%s: %s" % (f["error_code"], f["description"] or f["match_string"])
                                   for f in found)
    if CASE["status"] != "PASS":
        _post(d, "failure")
    RESULTS.append({"name": CASE["name"], "status": CASE["status"], "type": "testCase",
                    "testSuite": "Test Cases", "start": start, "end": _stamp(),
                    "duration": _seconds(began), "id": "s1-s1-s1-s1-s1-t%d" % number,
                    "reason": CASE["reason"], "steps": list(CASE["steps"])})


def _write_reports(start, began):
    OUT.mkdir(parents=True, exist_ok=True)
    status = "PASS" if all(r["status"] == "PASS" for r in RESULTS) else "FAIL"
    suite = {"name": "Test Cases", "status": status, "type": "testSuite", "start": start,
             "end": _stamp(), "duration": _seconds(began), "id": "s1-s1-s1-s1-s1",
             "appVersion": None, "testCases": RESULTS}
    (OUT / "test_report.json").write_text(json.dumps({"testSuites": [suite]}, indent=2), encoding="utf-8")
    failures = [r for r in RESULTS if r["status"] == "FAIL"]
    errors = [r for r in RESULTS if r["status"] == "ERROR"]
    root = ET.Element("testsuites")
    node = ET.SubElement(root, "testsuite", tests=str(len(RESULTS)), failures=str(len(failures)),
                         errors=str(len(errors)), skipped="0", time=suite["duration"])
    for r in RESULTS:
        case = ET.SubElement(node, "testcase", name=r["name"], classname="Test Cases", time=r["duration"])
        if r["status"] == "FAIL":
            ET.SubElement(case, "failure", message=r["reason"])
        elif r["status"] == "ERROR":
            ET.SubElement(case, "error", message=r["reason"])
    ET.ElementTree(root).write(OUT / "junit-results.xml", encoding="utf-8", xml_declaration=True)


# --- Part 3: after the test functions; replaces main() ---

# TESTS lists the test functions in suite order, never alphabetical.
def main():
    d = u2.connect(SERIAL)
    d.settings["wait_timeout"] = WAIT_TIMEOUT
    start, began = _stamp(), time.time()
    for number, case in enumerate(TESTS, 1):
        _run_case(d, case, number)
        print("%s %s" % (RESULTS[-1]["status"], case.__name__))
        if RESULTS[-1]["status"] != "PASS":
            print("  " + RESULTS[-1]["reason"])
    _write_reports(start, began)
    if SOFT and not all(SOFT):
        print("soft checks: %d of %d passed" % (sum(SOFT), len(SOFT)))
    return 1 if any(r["status"] != "PASS" for r in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
