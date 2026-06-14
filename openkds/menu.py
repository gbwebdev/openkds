from __future__ import annotations

import os
import yaml
from pathlib import Path
from importlib import resources

_menu_data: dict | None = None


def _load_yaml() -> dict:
    data_dir = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd()))
    override = data_dir / "menu.yaml"
    if override.exists():
        with open(override, encoding="utf-8") as f:
            return yaml.safe_load(f)
    pkg = resources.files("openkds.defaults").joinpath("menu.yaml")
    return yaml.safe_load(pkg.read_text(encoding="utf-8"))


def load_menu() -> dict:
    global _menu_data
    if _menu_data is None:
        _menu_data = _load_yaml()
    return _menu_data


def reload_menu() -> dict:
    global _menu_data
    _menu_data = _load_yaml()
    return _menu_data


def get_menu_items() -> list[dict]:
    return load_menu().get("menu", {}).get("items", [])


def get_workshops() -> list[dict]:
    return load_menu().get("workshops", [])


def get_stock_buckets() -> list[dict]:
    return load_menu().get("grill", {}).get("stock_buckets", [
        {"label": "0–6",   "min": 0,   "max": 6,   "midpoint": 3},
        {"label": "6–12",  "min": 6,   "max": 12,  "midpoint": 9},
        {"label": "12–18", "min": 12,  "max": 18,  "midpoint": 15},
        {"label": "18+",   "min": 18,  "max": 999, "midpoint": 21},
    ])


def get_printers() -> list[dict]:
    return load_menu().get("printers", [])


def get_dashboard_workshops() -> list[dict]:
    return [w for w in get_workshops() if w.get("type") == "dashboard"]


def get_ticket_workshops() -> list[dict]:
    return [w for w in get_workshops() if w.get("type") == "ticket"]


def compute_order_components(order_items: dict) -> dict:
    """Sum all components for an order dict {item_id: qty}."""
    items_map = {i["id"]: i for i in get_menu_items()}
    totals: dict[str, int] = {}
    for item_id, qty in order_items.items():
        if qty <= 0 or item_id not in items_map:
            continue
        for comp, mult in items_map[item_id].get("components", {}).items():
            totals[comp] = totals.get(comp, 0) + mult * qty
    return totals
