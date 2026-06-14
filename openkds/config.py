import json
import os
import threading
from pathlib import Path

_DATA_DIR = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd()))
CONFIG_PATH = _DATA_DIR / "config.json"

_lock = threading.Lock()

DEFAULT_CONFIG = {
    "grill_window_minutes": 20,
    "grill_segment_size": 6,
    "next_order_number": 1,
    "printer1_device": "/dev/ttyACM0",
    "printer2_device": "/dev/ttyACM1",
    "button_colors": {},
    "org_name": "",
    "event_name": "",
}


def load_config() -> dict:
    with _lock:
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False))
            return dict(DEFAULT_CONFIG)
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Ensure all default keys exist
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        if "button_colors" in data:
            colors = dict(DEFAULT_CONFIG["button_colors"])
            colors.update(data["button_colors"])
            merged["button_colors"] = colors
        return merged


def save_config(config: dict) -> None:
    with _lock:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def update_config(updates: dict) -> dict:
    config = load_config()
    for key, value in updates.items():
        if key == "button_colors" and isinstance(value, dict):
            config.setdefault("button_colors", {}).update(value)
        else:
            config[key] = value
    save_config(config)
    return config
