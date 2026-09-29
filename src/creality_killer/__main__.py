from __future__ import annotations

import argparse
import sys

from creality_killer import config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ck", description="Creality K1C client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("connect", "probe the printer and save its address"),
                        ("gui", "launch the desktop app"),
                        ("tui", "launch the terminal app")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("host", nargs="?", help="printer IP/hostname (default: $K1C_HOST or saved)")
        p.add_argument("--port", type=int, default=7125)
    args = ap.parse_args(argv)

    host = config.resolve_host(args.host)
    if args.cmd == "connect":
        if not host:
            ap.error("connect needs a host")
        from creality_killer.cli.connect import main as connect
        return connect(host, args.port)
    if args.cmd == "gui":
        from creality_killer.gui.app import main as gui
        return gui(host, args.port)
    from creality_killer.tui.app import main as tui
    return tui(host, args.port)


if __name__ == "__main__":
    sys.exit(main())
