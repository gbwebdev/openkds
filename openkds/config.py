from __future__ import annotations

import json
import os
import threading
from importlib import resources
from pathlib import Path

_DATA_DIR = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd()))
CONFIG_PATH = _DATA_DIR / "config.json"

_lock = threading.Lock()


def _load_defaults() -> dict:
    """Load defaults from openkds/defaults/config.json (bundled with the package)."""
    pkg = resources.files("openkds.defaults").joinpath("config.json")
    return json.loads(pkg.read_text(encoding="utf-8"))


def load_config() -> dict:
    """Return defaults overlaid with user settings from OPENKDS_DATA_DIR/config.json.

    The data file is only written when the user actually changes a setting
    (via save_config / update_config). It's never created automatically.
    """
    defaults = _load_defaults()
    if not CONFIG_PATH.exists():
        return defaults
    with _lock:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
    merged = dict(defaults)
    merged.update(user)
    # Dict-valued keys need merging, not replacement
    for k in ("button_colors", "printer_devices"):
        if k in user:
            combined = dict(defaults.get(k, {}))
            combined.update(user[k])
            merged[k] = combined
    return merged


def save_config(config: dict) -> None:
    with _lock:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def update_config(updates: dict) -> dict:
    config = load_config()
    for key, value in updates.items():
        if key in ("button_colors", "printer_devices") and isinstance(value, dict):
            config.setdefault(key, {}).update(value)
        else:
            config[key] = value
    save_config(config)
    return config
