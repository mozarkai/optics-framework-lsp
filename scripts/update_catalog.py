#!/usr/bin/env python3
"""Regenerate `keywords.py` from an optics-framework source tree.

    python scripts/update_catalog.py PATH        # an optics checkout, or a site-packages dir
    python scripts/update_catalog.py             # discovered from VIRTUAL_ENV
    python scripts/update_catalog.py --check      # exit 1 if the committed table is stale

Prefer passing PATH: `uv run` replaces `VIRTUAL_ENV` with this project's env, which does not
have optics installed, so discovery finds nothing there.

Signatures are read with `ast`, never imported. That is deliberate: importing
`optics_framework.api.*` pulls `numpy`, `cv2`, `pandas` and `skimage` through
`common.optics_builder`, so an import-based generator would need a ~342 MB install where this
one runs against `pip install --no-deps` — or against a bare checkout, which is what makes it
usable for comparing releases.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

# The four classes the runtime registers. Named rather than discovered: their modules also
# hold private helpers `KeywordRegistry` never sees.
CLASSES = {
    "action_keyword": "ActionKeyword",
    "app_management": "AppManagement",
    "flow_control": "FlowControl",
    "verifier": "Verifier",
}

OUT = Path(__file__).resolve().parent.parent / "src/optics_framework_lsp/keywords.py"

_HEADER = '''# GENERATED — do not edit. Run `python scripts/update_catalog.py` to refresh.
#
# Keyword signatures read from optics-framework {version}. `required` counts the leading
# positional params with no default; `variadic` means the keyword takes `*args`, so any
# number of params is legal.

OPTICS_VERSION = {version!r}

KEYWORDS: dict[str, dict] = {{
'''


def find_package(given: str | None) -> Path:
    """The `optics_framework` package directory, from an explicit path or a venv."""
    if given:
        root = Path(given).expanduser().resolve()
        for candidate in (root / "optics_framework", root):
            if (candidate / "api").is_dir():
                return candidate
        raise SystemExit(f"no optics_framework package under {root}")

    if root := os.environ.get("VIRTUAL_ENV"):
        # `optics_framework/__init__.py` is empty, so importing it costs nothing and works
        # even on a --no-deps install.
        python = Path(root) / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        if python.exists():
            probe = subprocess.run(
                [str(python), "-c", "import optics_framework as o; print(o.__file__)"],
                capture_output=True, text=True,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                return Path(probe.stdout.strip()).parent

    raise SystemExit(
        "could not find optics-framework. Pass a path, or set VIRTUAL_ENV to an env that has "
        "it installed (`pip install --no-deps optics-framework` is enough)."
    )


def version_of(package: Path) -> str:
    """Whatever the source tree says about itself, else the installed dist name."""
    pyproject = package.parent / "pyproject.toml"
    if pyproject.is_file():
        found = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.M)
        if found:
            return found.group(1)

    for dist in package.parent.glob("optics_framework-*.dist-info"):
        return dist.name.removeprefix("optics_framework-").removesuffix(".dist-info")

    return "unknown"


def signatures(package: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}

    for module, class_name in CLASSES.items():
        source = package / "api" / f"{module}.py"
        if not source.is_file():
            raise SystemExit(f"missing {source}")

        tree = ast.parse(source.read_text())
        cls = next(
            (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None
        )
        if cls is None:
            raise SystemExit(f"{source}: no class {class_name}")
        if cls.bases:
            # Reading only the class body would silently drop inherited keywords, and the
            # runtime registers those too (`KeywordRegistry` walks `dir(instance)`).
            raise SystemExit(
                f"{class_name} now has base classes {[ast.unparse(b) for b in cls.bases]}; "
                "this generator only reads the class body and would miss inherited keywords."
            )

        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name.startswith("_"):
                continue
            # `@DeprecationWarning` rebinds the attribute to an exception *instance*, which is
            # not callable, so `KeywordRegistry.register`'s `callable()` check skips it.
            if any(ast.unparse(d) == "DeprecationWarning" for d in fn.decorator_list):
                continue

            args = fn.args
            # Only params a csv row can fill: positional, never keyword-only.
            names = [p.arg for p in args.posonlyargs + args.args if p.arg != "self"]
            pad = len(names) - len(args.defaults)
            found[fn.name.replace("_", " ").lower()] = {
                "required": pad,
                "variadic": args.vararg is not None,
                "params": names,
                "defaults": {names[pad + i]: ast.unparse(d) for i, d in enumerate(args.defaults)},
                "doc": ast.get_docstring(fn) or "",
            }

    if not found:
        raise SystemExit("no keywords found — has the api package moved?")
    return found


def render(keywords: dict[str, dict], version: str) -> str:
    lines = [_HEADER.format(version=version)]
    for name in sorted(keywords):
        signature = keywords[name]
        lines.append(f"    {name!r}: {{\n")
        for key in ("required", "variadic", "params", "defaults"):
            lines.append(f"        {key!r}: {signature[key]!r},\n")
        lines.append(f"        'doc': {signature['doc']!r},\n")
        lines.append("    },\n")
    lines.append("}\n")
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="optics checkout or installed package dir")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args()

    package = find_package(args.path)
    version = version_of(package)
    keywords = signatures(package)
    rendered = render(keywords, version)

    if args.check:
        current = OUT.read_text() if OUT.is_file() else ""
        if current != rendered:
            raise SystemExit(f"{OUT.name} is stale — run scripts/update_catalog.py")
        print(f"{OUT.name} is up to date ({len(keywords)} keywords, optics {version})")
        return

    OUT.write_text(rendered)
    print(f"wrote {os.path.relpath(OUT)}: {len(keywords)} keywords, optics {version}")
    print(f"  source: {package}")


if __name__ == "__main__":
    main()
