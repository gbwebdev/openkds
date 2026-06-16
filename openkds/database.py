from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd())) / "openkds.db"

# Valid order statuses — kept in sync with models.OrderStatus.
_VALID_STATUSES = ("en_preparation", "livre", "annule")


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                number                 INTEGER NOT NULL,
                created_at             TEXT NOT NULL,
                items                  TEXT NOT NULL DEFAULT '{}',
                status                 TEXT NOT NULL DEFAULT 'en_preparation'
                                       CHECK(status IN ('en_preparation', 'livre', 'annule')),
                delivered_at           TEXT,
                delivery_delay_seconds INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

            CREATE TABLE IF NOT EXISTS grill_stock (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                stock      TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            INSERT OR IGNORE INTO grill_stock (id, stock, updated_at)
            VALUES (1, '{}', datetime('now'));
        """)
        # Defensive: add new columns if the table predates this schema.
        _ensure_column(conn, "orders", "status",
                       "TEXT NOT NULL DEFAULT 'en_preparation'")
        _ensure_column(conn, "orders", "delivered_at", "TEXT")
        _ensure_column(conn, "orders", "delivery_delay_seconds",
                       "INTEGER NOT NULL DEFAULT 0")


def _ensure_column(conn, table: str, name: str, definition: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


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


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def insert_order(number: int, items: dict) -> dict:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO orders (number, created_at, items) VALUES (?, ?, ?)",
            (number, _now(), json.dumps(items)),
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


def get_orders_by_status(status: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY number ASC",
            (status,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def set_order_status(order_id: int, status: str, delivered_at: str | None = None) -> dict | None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if status == "livre" and delivered_at is None:
        delivered_at = _now()
    elif status != "livre":
        delivered_at = None
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, delivered_at = ? WHERE id = ?",
            (status, delivered_at, order_id),
        )
    return get_order_by_id(order_id)


def add_order_delay(order_id: int, additional_seconds: int) -> dict | None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE orders SET delivery_delay_seconds = delivery_delay_seconds + ? "
            "WHERE id = ? AND status = 'en_preparation'",
            (additional_seconds, order_id),
        )
    return get_order_by_id(order_id)


def delete_all_orders():
    with get_connection() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute(
            "UPDATE grill_stock SET stock='{}', updated_at=datetime('now') WHERE id=1"
        )


def get_orders_since(cutoff_iso: str, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM orders WHERE created_at >= ?"
    args: list = [cutoff_iso]
    if status:
        sql += " AND status = ?"
        args.append(status)
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_grill_stock() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT stock FROM grill_stock WHERE id=1").fetchone()
    return json.loads(row["stock"]) if row else {}


def update_grill_stock(updates: dict) -> dict:
    stock = get_grill_stock()
    stock.update(updates)
    with get_connection() as conn:
        conn.execute(
            "UPDATE grill_stock SET stock=?, updated_at=? WHERE id=1",
            (json.dumps(stock), _now()),
        )
    return stock


def get_stats(menu_items: list[dict]) -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at ASC").fetchall()

    orders = [_row_to_dict(r) for r in rows]
    items_map = {i["id"]: i for i in menu_items}

    item_totals: dict[str, int] = {}
    component_totals: dict[str, int] = {}
    status_counts: dict[str, int] = {"en_preparation": 0, "livre": 0, "annule": 0}

    for order in orders:
        status_counts[order.get("status", "en_preparation")] = (
            status_counts.get(order.get("status", "en_preparation"), 0) + 1
        )
        # Cancelled orders don't count toward item/component totals
        if order.get("status") == "annule":
            continue
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
        "status_counts": status_counts,
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
