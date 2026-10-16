"""The saved kettle (ip, token, did, model) in ~/.config/kettle/config.json, mode 600."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.path.expanduser("~/.config/kettle/config.json"))


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    os.chmod(CONFIG_PATH, 0o600)
