import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from optics_framework_lsp.keyword_catalog import CATALOG, OPTICS_VERSION, Keyword
from optics_framework_lsp.parser.csv_parser import parse_csv_sources
from optics_framework_lsp.validation import validate

REPO = Path(__file__).resolve().parent.parent


def test_the_shipped_table_is_the_real_signatures():
    """No install needed — this is the point of hardcoding."""
    assert len(CATALOG) == 51
    assert OPTICS_VERSION

    press = CATALOG["press element"]
    assert press.required == 1
    assert press.params[0] == "element"
    assert len(press.params) == 10

    sleep, loop = CATALOG["sleep"], CATALOG["run loop"]
    assert (sleep.required, sleep.variadic, sleep.params) == (1, False, ["duration"])
    assert (loop.required, loop.variadic, loop.params) == (1, True, ["target"])
    assert CATALOG["condition"].variadic

    # Hover shows this, so it has to survive generation.
    assert sleep.doc.startswith("Sleep for a specified duration.")
    # And defaults, which hover and signature help both render.
    assert CATALOG["press element"].defaults["repeat"] == "'1'"


def test_the_facade_keywords_are_in_the_table():
    """`_parse_module_step` resolves against these two as well, so a step reading
    `Press Element With Index ...` must not bind to the shorter `Press Element`."""
    found = CATALOG["press element with index"]
    assert (found.required, found.params) == (1, ["element", "index", "event_name"])
    assert CATALOG["quit"].params == []


def test_what_the_runtime_would_not_register_is_absent():
    # `_HealProviders` sits beside `ActionKeyword` and has a `pagesource` method. The
    # generator reads only the named class body, so it must never surface as a keyword.
    assert "pagesource" not in CATALOG


def test_a_deprecationwarning_decorator_excludes_a_keyword(tmp_path):
    """The generator's filter, pinned against a synthetic source. No optics release carries
    `@DeprecationWarning` today, so the shipped table can no longer exercise this — and
    without a test the filter is code nobody can see the purpose of."""
    api = tmp_path / "optics_framework" / "api"
    api.mkdir(parents=True)
    for module, class_name in (
        ("action_keyword", "ActionKeyword"),
        ("app_management", "AppManagement"),
        ("flow_control", "FlowControl"),
        ("verifier", "Verifier"),
    ):
        (api / f"{module}.py").write_text(
            f"class {class_name}:\n"
            "    def kept(self, element): pass\n"
            "    @DeprecationWarning\n"
            "    def dropped(self, element): pass\n"
        )

    _facade_source(tmp_path)

    found = _generator().signatures(tmp_path / "optics_framework")
    assert "kept" in found
    assert "dropped" not in found


def _facade_source(root, names=("press_element_with_index", "quit")):
    """The `optics.py` the generator reads the facade keywords out of."""
    body = "class Optics:\n" + "".join(
        f'    @keyword("x")\n    def {name}(self, element): pass\n' for name in names
    )
    (root / "optics_framework" / "optics.py").write_text(body)


def test_a_facade_keyword_the_source_lost_is_loud(tmp_path):
    """The pair is hardcoded here and in the runner. If the facade drops one, say so
    rather than shipping a table that silently mis-splits every step naming it."""
    api = tmp_path / "optics_framework" / "api"
    api.mkdir(parents=True)
    for module, class_name in (
        ("action_keyword", "ActionKeyword"),
        ("app_management", "AppManagement"),
        ("flow_control", "FlowControl"),
        ("verifier", "Verifier"),
    ):
        (api / f"{module}.py").write_text(f"class {class_name}:\n    def kept(self): pass\n")
    _facade_source(tmp_path, names=("quit",))

    with pytest.raises(SystemExit, match="press_element_with_index"):
        _generator().signatures(tmp_path / "optics_framework")


def _generator():
    """`scripts/` is not a package, so load the generator by path."""
    spec = importlib.util.spec_from_file_location(
        "update_catalog", REPO / "scripts" / "update_catalog.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_table_is_not_stale():
    """Regenerate from a real optics and diff. This test is why the table can be trusted."""
    venv = os.environ.get("OPTICS_PROBE_VENV")
    if not venv or not Path(venv, "bin", "python").exists():
        pytest.skip("set OPTICS_PROBE_VENV to a venv with optics-framework installed")

    done = subprocess.run(
        [sys.executable, "scripts/update_catalog.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "VIRTUAL_ENV": venv},
    )
    assert done.returncode == 0, done.stdout + done.stderr


CATALOG_FOR_TESTS = {
    "press element": Keyword(1, False, ["element"] + [f"opt{i}" for i in range(9)]),
    "enter text": Keyword(2, False, ["element", "text"] + [f"opt{i}" for i in range(5)]),
    "condition": Keyword(0, True, []),
}


def _check(modules: str):
    return validate(
        parse_csv_sources([("file:///w/modules.csv", modules)]), CATALOG_FOR_TESTS
    ).get("file:///w/modules.csv", [])


def test_unknown_keyword_is_reported():
    codes = [d.code for d in _check(
        "module_name,module_step,param_1\nM,Press Elemnt,${btn}\n"
    )]
    assert "keyword-not-found" in codes


def test_nested_module_call_is_allowed():
    codes = [d.code for d in _check(
        "module_name,module_step,param_1\n"
        "Helper,Condition,x\n"
        "M,Helper\n"
    )]
    assert "keyword-not-found" not in codes


def test_too_few_params_is_reported():
    (diagnostic,) = [d for d in _check(
        "module_name,module_step,param_1,param_2\nM,Enter Text,${field},,\n"
    ) if d.code == "keyword-arity"]
    assert "needs 'text'" in diagnostic.message


# --- name=value params, as `split_params_by_signature` reads them ------------- #

def test_a_named_param_fills_its_slot():
    (diagnostic,) = [d for d in _check(
        "module_name,module_step,param_1,param_2\nM,Enter Text,${field},opt0=x\n"
    ) if d.code == "keyword-arity"]
    assert "needs 'text'" in diagnostic.message

    assert "keyword-arity" not in [d.code for d in _check(
        "module_name,module_step,param_1,param_2,param_3\nM,Enter Text,${field},hi,opt1=2\n"
    )]


def test_a_locator_strategy_is_not_a_named_param():
    """`text` is no parameter of `Press Element`, so it stays the element."""
    assert not [d for d in _check(
        "module_name,module_step,param_1\nM,Press Element,text=Login\n"
    ) if d.code.startswith("keyword-")]


def test_a_param_given_twice_is_reported():
    (by_name,) = [d for d in _check(
        "module_name,module_step,param_1,param_2,param_3\nM,Press Element,${f},opt0=2,opt0=3\n"
    ) if d.code == "keyword-param-repeated"]
    assert "more than once" in by_name.message

    (both_ways,) = [d for d in _check(
        "module_name,module_step,param_1,param_2,param_3\nM,Press Element,${f},2,opt0=3\n"
    ) if d.code == "keyword-param-repeated"]
    assert "by position and by name" in both_ways.message


def test_variadic_keyword_accepts_any_count():
    codes = [d.code for d in _check(
        "module_name,module_step,param_1,param_2,param_3,param_4\n"
        "M,Condition,a,b,c,d\n"
    )]
    assert "keyword-arity" not in codes


def test_no_catalog_means_no_keyword_diagnostics():
    found = validate(
        parse_csv_sources(
            [("file:///w/m.csv", "module_name,module_step\nM,Totally Made Up\n")]
        )
    )
    assert found == {}


def test_the_real_catalog_accepts_the_real_keywords():
    """A sanity sweep with the shipped table rather than a stub."""
    found = validate(
        parse_csv_sources([
            ("file:///w/m.csv",
             "module_name,module_step,param_1,param_2\n"
             "M,Sleep,1\n"
             "M,Press Element,${btn}\n"
             "M,Enter Text,${field},hello\n"),
            ("file:///w/e.csv", "element_name,element_id\nbtn,//a\nfield,//b\n"),
        ]),
        CATALOG,
    )
    assert found == {}
