from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd())) / "openkds.db"


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                number       INTEGER NOT NULL,
                created_at   TEXT NOT NULL,
                items        TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS grill_stock (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                stock      TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            INSERT OR IGNORE INTO grill_stock (id, stock, updated_at)
            VALUES (1, '{}', datetime('now'));
        """)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_order(number: int, items: dict) -> dict:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO orders (number, created_at, items) VALUES (?, ?, ?)",
            (number, now, json.dumps(items)),
        )
        row_id = cursor.lastrowid
    return get_order_by_id(row_id)


def _row_to_dict(row) -> dict:
    d = dict(row)
    if "items" in d and isinstance(d["items"], str):
        d["items"] = json.loads(d["items"])
    return d


def get_order_by_id(order_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_orders() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY number DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_all_orders():
    with get_connection() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute(
            "UPDATE grill_stock SET stock='{}', updated_at=datetime('now') WHERE id=1"
        )


def get_orders_since(cutoff_iso: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE created_at >= ?", (cutoff_iso,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_grill_stock() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT stock FROM grill_stock WHERE id=1").fetchone()
    return json.loads(row["stock"]) if row else {}


def update_grill_stock(updates: dict) -> dict:
    stock = get_grill_stock()
    stock.update(updates)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "UPDATE grill_stock SET stock=?, updated_at=? WHERE id=1",
            (json.dumps(stock), now),
        )
    return stock


def get_stats(menu_items: list[dict]) -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at ASC").fetchall()

    orders = [_row_to_dict(r) for r in rows]
    items_map = {i["id"]: i for i in menu_items}

    item_totals: dict[str, int] = {}
    component_totals: dict[str, int] = {}

    for order in orders:
        for item_id, qty in order.get("items", {}).items():
            if qty <= 0:
                continue
            item_totals[item_id] = item_totals.get(item_id, 0) + qty
            if item_id in items_map:
                for comp, mult in items_map[item_id].get("components", {}).items():
                    component_totals[comp] = component_totals.get(comp, 0) + mult * qty

    items_summary = [
        {
            "id": item["id"],
            "label": item["label"].replace("\n", " "),
            "total": item_totals.get(item["id"], 0),
        }
        for item in menu_items
    ]

    return {
        "total_orders": len(orders),
        "items": items_summary,
        "components": component_totals,
        "histogram": _build_histogram(orders),
    }


def _build_histogram(orders: list[dict]) -> list[dict]:
    if not orders:
        return []
    from datetime import timedelta
    first = datetime.fromisoformat(orders[0]["created_at"])
    slot_minutes = 10
    buckets: dict[str, int] = {}
    for o in orders:
        dt = datetime.fromisoformat(o["created_at"])
        slot_index = int((dt - first).total_seconds() // 60) // slot_minutes
        slot_dt = first + timedelta(minutes=slot_index * slot_minutes)
        label = slot_dt.strftime("%H:%M")
        buckets[label] = buckets.get(label, 0) + 1
    return [{"slot": k, "count": v} for k, v in sorted(buckets.items())]
