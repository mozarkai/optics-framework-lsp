from __future__ import annotations

from .server import server


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
