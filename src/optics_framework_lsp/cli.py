"""optics-lsp — a language server for optics-framework csv suites.

With no arguments it speaks LSP over stdio, which is how an editor starts it. `lint` instead
validates a whole suite in one shot and reports every finding:

    optics-lsp lint PATH        # walk a project directory; readable output
    optics-lsp lint             # read {"files":[{"name","content"}]} as JSON on stdin
    optics-lsp lint PATH --json # the machine-readable report either way

stdin is for a caller holding uploaded files in memory with nothing on disk, which is why it
always answers JSON. A path is for a person, so it prints lines.

Both branches import lazily: `lint` must not pay for pygls, and serving must not pay for
anything the linter needs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _lint(path: str | None, as_json: bool) -> int:
    """Exit 0 whenever the suite was validated — findings are data, not process failure — and
    1 if the input could not be read at all."""
    from .lint import as_text, report, walk

    if path is None:
        try:
            body = json.load(sys.stdin)
            files = [(entry["name"], entry["content"]) for entry in body["files"]]
        except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as error:
            print(
                'optics-lsp lint: expected {"files": [{"name": ..., "content": ...}]} on stdin '
                f"({type(error).__name__}: {error})",
                file=sys.stderr,
            )
            return 1
        as_json = True
    else:
        root = Path(path).expanduser()
        if not root.is_dir():
            print(f"optics-lsp lint: not a directory: {root}", file=sys.stderr)
            return 1
        files = walk(root)

    found = report(files)
    if as_json:
        json.dump(found, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(as_text(found))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="optics-lsp", description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["lint"],
        help="validate a suite instead of serving over stdio",
    )
    parser.add_argument(
        "path", nargs="?", help="project directory to walk; omitted, the suite is read on stdin"
    )
    parser.add_argument("--json", action="store_true", help="report as JSON rather than lines")
    # Unknown flags are ignored rather than rejected: editors pass their own (`--stdio`), and
    # refusing them would break a client for no gain.
    args, _ = parser.parse_known_args()

    if args.command == "lint":
        raise SystemExit(_lint(args.path, args.json))

    from .server import server

    server.start_io()


if __name__ == "__main__":
    main()
