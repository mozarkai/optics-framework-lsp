# Keyword signatures read from the optics-framework installed in the user's project

from __future__ import annotations

import asyncio
import json
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


async def load(folder: Path) -> Catalog | None:
    """None when optics-framework is not importable; callers then skip keyword rules."""
    venv = folder / ".venv" / "bin" / "python"
    process = await asyncio.create_subprocess_exec(
        str(venv) if venv.exists() else sys.executable,
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
