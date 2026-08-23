# Keyword signatures read from the optics-framework installed in the user's project

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Runs in the project's interpreter, which does not have this package installed, so the
# probe is passed as source. The four classes are named rather than discovered because
# their modules also hold private helpers the runtime never registers.
_PROBE = """
import importlib, inspect, json

CLASSES = {
    "action_keyword": "ActionKeyword",
    "app_management": "AppManagement",
    "flow_control": "FlowControl",
    "verifier": "Verifier",
}

out = {}
for module, class_name in CLASSES.items():
    cls = getattr(importlib.import_module(f"optics_framework.api.{module}"), class_name)
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        required = 0
        variadic = False
        params = []
        for param_name, p in inspect.signature(fn).parameters.items():
            if param_name == "self":
                continue
            if p.kind is p.VAR_POSITIONAL:
                variadic = True
            elif p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                # A csv row can only fill positional params, never keyword-only ones.
                params.append(param_name)
                if p.default is p.empty:
                    required += 1
        out[name.replace("_", " ").title()] = {
            "required": required, "variadic": variadic, "params": params,
        }

print(json.dumps(out))
"""


@dataclass(slots=True)
class Keyword:
    required: int
    variadic: bool
    # Positional names in order. Python forbids a defaulted param before a plain one, so
    # the first `required` of these are the mandatory ones.
    params: list[str]


Catalog = dict[str, Keyword]


def candidates(folder: Path) -> list[Path]:
    """Interpreters to try. `VIRTUAL_ENV` first: every venv tool sets it, and only uv
    and pdm keep the environment in the project."""
    roots = [os.environ.get("VIRTUAL_ENV"), *(folder / n for n in (".venv", "venv", "env"))]
    pythons = [Path(root) / "bin" / "python" for root in roots if root]
    return [p for p in pythons if p.exists()] + [Path(sys.executable)]


def installed_at(folder: Path) -> tuple[str, float] | None:
    """The optics install a catalog would come from, so a later one is noticed."""
    for python in candidates(folder):
        script = python.with_name("optics")
        try:
            return str(script), script.stat().st_mtime
        except OSError:
            continue
    return None


async def _probe(python: Path) -> Catalog | None:
    process = await asyncio.create_subprocess_exec(
        str(python),
        "-c",
        _PROBE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return None

    return {
        name.lower(): Keyword(**signature)
        for name, signature in json.loads(stdout).items()
    }


async def load(folder: Path) -> Catalog | None:
    """None when no candidate interpreter can import optics-framework."""
    for python in candidates(folder):
        if (catalog := await _probe(python)) is not None:
            return catalog
    return None
