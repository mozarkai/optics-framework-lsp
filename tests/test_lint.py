"""The batch commands: `lint` for every finding, `parse` for what the files say."""

import json
import subprocess
import sys

from optics_framework_lsp.keyword_catalog import CATALOG
from optics_framework_lsp.lint import parse, report
from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.validation import validate

MODULES = (
    "module_name,module_step,param_1\n"
    "M,Sleep,1\n"
    "M,Press Elemnt,${btn}\n"
)
# A module with nothing wrong with it: `Sleep` takes its duration.
CLEAN = "module_name,module_step,param_1\nM,Sleep,1\n"


def _run(*args, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "optics_framework_lsp.cli", *args],
        input=stdin, capture_output=True, text=True,
    )


def test_a_finding_carries_both_row_conventions():
    """`row` is 1-based as the framework counts rows; `range` is 0-based for an editor."""
    found = report([("m.csv", MODULES)])["diagnostics"]

    assert [d["code"] for d in found] == ["element-not-found", "keyword-not-found"]
    first = found[0]
    assert first["row"] == 3
    assert first["range"] == {"startLine": 2, "startColumn": 0, "endLine": 3, "endColumn": 0}
    assert first["severity"] == "error"
    assert first["source"] == "optics"
    assert first["uri"] == "m.csv"


def test_severity_becomes_a_string():
    body = report([
        ("m.csv", CLEAN),
        ("e.csv", "element_name,element_id\nb,//a\nb,//a\n"),
    ])
    assert {d["severity"] for d in body["diagnostics"]} == {"warning"}
    # Warnings alone do not fail the suite.
    assert body["status"] == "PASS"


def test_status_is_fail_only_on_an_error():
    assert report([("m.csv", MODULES)])["status"] == "FAIL"
    assert report([("m.csv", CLEAN)])["status"] == "PASS"
    assert report([])["status"] == "PASS"
    assert report([])["diagnostics"] == []


def test_analyzed_names_the_kind_and_skipped_names_the_rest():
    body = report([
        ("t.csv", "test_case,test_step\nTC,M\n"),
        ("m.csv", CLEAN),
        ("e.csv", "element_name,element_id\nb,//a\n"),
        ("x.csv", "error_code,match_string\nE1,boom\n"),
        ("users.csv", "name,age\nbob,3\n"),
        ("apis.yaml", "api: {}\n"),
    ])
    assert body["analyzed"] == {
        "t.csv": "test_cases", "m.csv": "modules",
        "e.csv": "elements", "x.csv": "error_definitions",
        # An api file is read by the runner too, so it is analysed rather than skipped.
        "apis.yaml": "api",
    }
    # An unrecognised file is skipped whatever it is written as, and must be visible:
    # the framework ignores it too, so silence would read as a clean file.
    assert body["skipped"] == ["users.csv"]


def test_only_csv_files_are_read_as_csv():
    """`identify_file_content` branches on the extension before looking at content, so a
    yaml file holding a csv-shaped header is yaml to the framework — and to us."""
    body = report([("modules.yaml", "module_name,module_step,param_1\nM,Nope,1\n")])

    assert body["analyzed"] == {}
    assert body["skipped"] == ["modules.yaml"]
    assert body["diagnostics"] == []


def test_a_recognised_but_empty_file_still_counts_as_analyzed():
    body = report([("m.csv", "module_name,module_step,param_1\n")])
    assert body["analyzed"] == {"m.csv": "modules"}
    assert body["skipped"] == []


def test_diagnostics_are_sorted_by_file_then_row():
    body = report([
        ("z.csv", "module_name,module_step\nZ,Nope\n"),
        ("a.csv", "module_name,module_step\nA,Nope\nA,Also Nope\n"),
    ])
    assert [(d["uri"], d["row"]) for d in body["diagnostics"]] == [
        ("a.csv", 2), ("a.csv", 3), ("z.csv", 2),
    ]


def test_no_catalog_drops_the_keyword_rules():
    codes = {d["code"] for d in report([("m.csv", MODULES)], catalog=None)["diagnostics"]}
    assert "keyword-not-found" not in codes
    assert "element-not-found" in codes


def test_the_report_says_exactly_what_the_engine_says():
    """The wire mapping must not drift from `validate`."""
    files = [("m.csv", MODULES), ("e.csv", "element_name,element_id\nbtn,//a\nbtn,//a\n")]
    body = report(files)

    engine = validate(parse_csv_sources(files), CATALOG)
    expected = sorted(
        ((uri, f.row, f.code, f.message) for uri, fs in engine.items() for f in fs),
        key=lambda row: (row[0], row[1]),
    )
    assert [(d["uri"], d["row"], d["code"], d["message"]) for d in body["diagnostics"]] == expected


def test_the_linter_never_imports_the_protocol():
    """`import lsprotocol.types` costs ~290ms, which a per-call process pays every time."""
    done = subprocess.run(
        [sys.executable, "-c",
         "import optics_framework_lsp.lint, sys;"
         "leaked = [m for m in ('lsprotocol', 'pygls') if m in sys.modules];"
         "print(leaked)"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", f"the lint path imports {done.stdout.strip()}"


def test_the_cli_reports_over_stdin():
    payload = json.dumps({"files": [{"name": "m.csv", "content": MODULES}]})
    done = _run("lint", stdin=payload)

    assert done.returncode == 0, done.stderr
    body = json.loads(done.stdout)
    assert body["status"] == "FAIL"
    assert body["analyzed"] == {"m.csv": "modules"}


SUITE = (
    "Test Cases:\n"
    "  - Login:\n"
    "      - Open App\n"
    "Modules:\n"
    "  - Open App:\n"
    "      - Sleep 5\n"
    '      - Press Element ${btn} text="two words"\n'
    "Elements:\n"
    "  btn:\n"
    "    - //a\n"
    "    - Sign in\n"
)


def test_lint_answers_findings_and_parse_answers_the_suite():
    """Two questions, two commands: neither carries the other's answer."""
    assert "suite" not in report([("s.yaml", SUITE)])
    assert "diagnostics" not in parse([("s.yaml", SUITE)])


def test_the_suite_carries_what_a_caller_has_to_store():
    """Split as the runner splits it: `Sleep 5` is a keyword and a param, and a quoted
    value is one param without its quotes."""
    found = parse([("s.yaml", SUITE)])["suite"]
    assert found["testCases"] == {"Login": ["Open App"]}
    assert found["modules"] == {
        "Open App": [
            {"keyword": "Sleep", "params": ["5"]},
            {"keyword": "Press Element", "params": ["${btn}", "text=two words"]},
        ]
    }
    assert found["elements"] == {"btn": ["//a", "Sign in"]}


def test_a_name_an_api_binds_is_listed_as_runtime():
    """A caller storing the suite has nothing to store for these: no file declares them, the
    run does. They stay in `elements` too, because `${name}` reads them like any other."""
    api = (
        "api:\n  collections:\n    alpha:\n      apis:\n        first:\n"
        "          expected_result:\n            extract:\n              code: field_a\n"
    )
    found = parse([("s.yaml", SUITE), ("api.yaml", api)])["suite"]
    assert found["runtime"] == ["code"]
    assert found["elements"]["code"] == []
    assert found["elements"]["btn"] == ["//a", "Sign in"]


def test_a_suite_with_no_api_has_nothing_at_runtime():
    assert parse([("s.yaml", SUITE)])["suite"]["runtime"] == []


def test_a_suite_reads_the_same_whichever_format_it_is_written_as():
    """One ast behind both readers, which is the whole reason a caller can ask for this."""
    csv = [
        ("test_cases.csv", "test_case,test_step\nLogin,Open App\n"),
        ("modules.csv", "module_name,module_step,param_1,param_2\n"
                        "Open App,Sleep,5,\n"
                        "Open App,Press Element,${btn},text=two words\n"),
        ("elements.csv", "Element_Name,Element_ID,Element_ID_fallback1\nbtn,//a,Sign in\n"),
    ]
    assert parse(csv)["suite"] == parse([("s.yaml", SUITE)])["suite"]


def test_an_element_repeated_gathers_its_locators():
    """`resolve_with_fallback` tries one list in turn, however many rows wrote it."""
    csv = "Element_Name,Element_ID\nbtn,//a\nbtn,Sign in\n"
    assert parse([("e.csv", csv)])["suite"]["elements"] == {"btn": ["//a", "Sign in"]}


def test_parse_says_what_it_read_as_well_as_what_it_says():
    """`analyzed` and `skipped` tell an empty suite from an upload that held none."""
    found = parse([("s.yaml", SUITE), ("data.csv", "name,plan\nada,basic\n")])
    assert found["analyzed"] == {"s.yaml": "test_cases,modules,elements"}
    assert found["skipped"] == ["data.csv"]


def test_the_cli_parses_over_stdin_and_from_a_path(tmp_path):
    payload = json.dumps({"files": [{"name": "s.yaml", "content": SUITE}]})
    (tmp_path / "s.yaml").write_text(SUITE)

    for done in (_run("parse", stdin=payload), _run("parse", str(tmp_path))):
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["suite"]["testCases"] == {"Login": ["Open App"]}


def test_the_cli_rejects_input_it_cannot_read():
    for stdin in ("not json", "{}", '{"files": [{"name": "m.csv"}]}'):
        done = _run("lint", stdin=stdin)
        assert done.returncode == 1, f"{stdin!r} should not have been accepted"
        assert "expected" in done.stderr
        assert done.stdout == ""


def test_walking_a_project_names_files_relative_to_it(tmp_path):
    """Relative, not basenames: two `modules.csv` in different folders must stay distinct."""
    from optics_framework_lsp.lint import walk

    (tmp_path / "modules").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "modules/suite.csv").write_text(CLEAN)
    (tmp_path / "tests/suite.csv").write_text("test_case,test_step\nTC,M\n")
    (tmp_path / "notes.txt").write_text("ignored")

    # optics-framework ships sample csvs of its own inside a venv; they must stay invisible.
    (tmp_path / ".venv/samples").mkdir(parents=True)
    (tmp_path / ".venv/samples/planted.csv").write_text(CLEAN)

    assert [name for name, _ in walk(tmp_path)] == ["modules/suite.csv", "tests/suite.csv"]


def test_the_cli_walks_a_directory(tmp_path):
    (tmp_path / "m.csv").write_text(MODULES)

    lines = _run("lint", str(tmp_path))
    assert lines.returncode == 0, lines.stderr
    assert "m.csv:3: error: element-not-found:" in lines.stdout
    assert "FAIL  1 files analysed, 2 errors, 0 warnings" in lines.stdout
    assert not lines.stdout.startswith("{"), "a person asked, so lines"

    body = _run("lint", str(tmp_path), "--json")
    assert json.loads(body.stdout)["analyzed"] == {"m.csv": "modules"}


def test_the_cli_rejects_a_path_that_is_not_a_directory(tmp_path):
    done = _run("lint", str(tmp_path / "nope"))
    assert done.returncode == 1
    assert "not a directory" in done.stderr


def test_the_text_report_summarises_skipped_files():
    from optics_framework_lsp.lint import as_text

    text = as_text(report([("m.csv", CLEAN), ("users.csv", "name,age\nbob,3\n")]))
    assert text == "PASS  1 files analysed, 0 errors, 0 warnings  (1 skipped: users.csv)"
