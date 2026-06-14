import os
import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DB_PATH = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd())) / "openkds.db"


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                number          INTEGER NOT NULL,
                created_at      TEXT NOT NULL,
                adulte_merguez  INTEGER NOT NULL DEFAULT 0,
                adulte_chipo    INTEGER NOT NULL DEFAULT 0,
                enfant_merguez  INTEGER NOT NULL DEFAULT 0,
                enfant_chipo    INTEGER NOT NULL DEFAULT 0,
                galette_saucisse INTEGER NOT NULL DEFAULT 0,
                barquette_frite  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS grill_stock (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                merguez     INTEGER NOT NULL DEFAULT 0,
                chipo       INTEGER NOT NULL DEFAULT 0,
                saucisse    INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL
            );

            INSERT OR IGNORE INTO grill_stock (id, merguez, chipo, saucisse, updated_at)
            VALUES (1, 0, 0, 0, datetime('now'));
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
            """INSERT INTO orders
               (number, created_at, adulte_merguez, adulte_chipo, enfant_merguez,
                enfant_chipo, galette_saucisse, barquette_frite)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                number, now,
                items.get("adulte_merguez", 0),
                items.get("adulte_chipo", 0),
                items.get("enfant_merguez", 0),
                items.get("enfant_chipo", 0),
                items.get("galette_saucisse", 0),
                items.get("barquette_frite", 0),
            )
        )
        row_id = cursor.lastrowid
    return get_order_by_id(row_id)


def get_order_by_id(order_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def get_all_orders() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY number DESC").fetchall()
    return [dict(r) for r in rows]


def delete_all_orders():
    with get_connection() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute("UPDATE grill_stock SET merguez=0, chipo=0, saucisse=0, updated_at=datetime('now') WHERE id=1")


def get_orders_since(cutoff_iso: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE created_at >= ?", (cutoff_iso,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_grill_stock() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM grill_stock WHERE id=1").fetchone()
    return dict(row) if row else {"merguez": 0, "chipo": 0, "saucisse": 0}


def update_grill_stock(merguez: int | None, chipo: int | None, saucisse: int | None) -> dict:
    stock = get_grill_stock()
    if merguez is not None:
        stock["merguez"] = merguez
    if chipo is not None:
        stock["chipo"] = chipo
    if saucisse is not None:
        stock["saucisse"] = saucisse
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "UPDATE grill_stock SET merguez=?, chipo=?, saucisse=?, updated_at=? WHERE id=1",
            (stock["merguez"], stock["chipo"], stock["saucisse"], now)
        )
    return stock


def get_stats() -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at ASC").fetchall()

    orders = [dict(r) for r in rows]
    total_orders = len(orders)

    totals = {
        "adulte_merguez": 0, "adulte_chipo": 0,
        "enfant_merguez": 0, "enfant_chipo": 0,
        "galette_saucisse": 0, "barquette_frite": 0,
    }
    components = {"frites": 0, "merguez": 0, "chipo": 0, "saucisse": 0, "boisson": 0}

    for o in orders:
        for k in totals:
            totals[k] += o[k]
        components["frites"] += (o["adulte_merguez"] + o["adulte_chipo"] +
                                  o["enfant_merguez"] + o["enfant_chipo"] +
                                  o["barquette_frite"])
        components["merguez"] += 2 * o["adulte_merguez"] + o["enfant_merguez"]
        components["chipo"] += 2 * o["adulte_chipo"] + o["enfant_chipo"]
        components["saucisse"] += o["galette_saucisse"]
        components["boisson"] += (o["adulte_merguez"] + o["adulte_chipo"] +
                                   o["enfant_merguez"] + o["enfant_chipo"])

    histogram = _build_histogram(orders)

    return {
        "total_orders": total_orders,
        "totals": totals,
        "components": components,
        "histogram": histogram,
    }


def _build_histogram(orders: list[dict]) -> list[dict]:
    if not orders:
        return []

    from datetime import datetime, timedelta

    first = datetime.fromisoformat(orders[0]["created_at"])
    slot_minutes = 10
    buckets: dict[str, int] = {}

    for o in orders:
        dt = datetime.fromisoformat(o["created_at"])
        delta = int((dt - first).total_seconds() // 60)
        slot_index = delta // slot_minutes
        slot_dt = first + timedelta(minutes=slot_index * slot_minutes)
        slot_label = slot_dt.strftime("%H:%M")
        buckets[slot_label] = buckets.get(slot_label, 0) + 1

    return [{"slot": k, "count": v} for k, v in sorted(buckets.items())]
