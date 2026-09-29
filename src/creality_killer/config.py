"""Where to find the printer: CLI flag > $K1C_HOST > saved config."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "creality_killer" / "config.json"


def load() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save(**values) -> None:
    cfg = load() | values
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def resolve_host(cli_host: str | None) -> str | None:
    return cli_host or os.environ.get("K1C_HOST") or load().get("host")
