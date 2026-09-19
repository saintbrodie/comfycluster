from __future__ import annotations

import argparse
import sys

from .settings import DesktopSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ComfyCluster", description="ComfyCluster Windows desktop")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Validate the packaged desktop runtime and exit",
    )
    args = parser.parse_args(argv)

    if args.diagnostics:
        from PySide6 import QtCore

        settings = DesktopSettings()
        if not QtCore.qVersion() or not settings.controller_url:
            return 1
        return 0

    from .window import run_desktop

    return run_desktop(DesktopSettings())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
