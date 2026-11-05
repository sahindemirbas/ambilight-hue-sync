"""Command line entry point: ``ambilight-hue-sync run|register|check``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ambilight-hue-sync")
    ap.add_argument("-c", "--config", type=Path, help="path to config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="stream Ambilight to Hue until stopped")
    sub.add_parser("check", help="validate the config and print the light mapping")
    reg = sub.add_parser("register", help="create Hue Entertainment credentials")
    reg.add_argument("--host", required=True, help="Hue Bridge IP address")
    reg.add_argument("--out", type=Path,
                     default=Path("~/.config/ambilight-hue-sync/hue.json").expanduser())
    a = ap.parse_args(argv)

    if a.cmd == "register":
        from .register import register
        register(a.host, a.out.expanduser())
        return 0
    try:
        cfg = config.load(a.config)
    except (OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if a.cmd == "check":
        print(f"TV {cfg.tv_host}, bridge {cfg.hue_host}, area {cfg.area!r}")
        for lt in cfg.lights:
            print(f"  {lt.name}: {lt.side} {lt.start:.2f}-{lt.end:.2f} x{lt.scale}")
        return 0
    from .sync import Sync
    Sync(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
