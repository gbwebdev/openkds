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
        # Step 1 — create tables. Use IF NOT EXISTS so this is idempotent and
        # leaves pre-existing tables untouched (their columns may be missing).
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

            CREATE TABLE IF NOT EXISTS grill_stock (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                stock      TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            INSERT OR IGNORE INTO grill_stock (id, stock, updated_at)
            VALUES (1, '{}', datetime('now'));

            CREATE TABLE IF NOT EXISTS helloasso_tickets (
                qr_code          TEXT PRIMARY KEY,
                customer_name    TEXT,             -- payer "Nom Prénom"
                items            TEXT NOT NULL,    -- JSON {item_id: qty}
                imported_at      TEXT NOT NULL,
                redeemed_at      TEXT,
                order_id         INTEGER REFERENCES orders(id) ON DELETE SET NULL,
                precommande_id   TEXT,
                participant_name TEXT,             -- who's eating (CSV: Nom + Prénom participant)
                ticket_number    TEXT,             -- CSV: Numéro de billet (= QR before ':')
                tarif            TEXT,             -- CSV: human-readable Tarif label
                order_date       TEXT,             -- CSV: Date de la commande
                payer_email      TEXT
            );
        """)
        # Step 2 — add columns missing from pre-existing tables. Must happen
        # BEFORE creating indexes that reference those columns.
        _ensure_column(conn, "orders", "status",
                       "TEXT NOT NULL DEFAULT 'en_preparation'")
        _ensure_column(conn, "orders", "delivered_at", "TEXT")
        _ensure_column(conn, "orders", "delivery_delay_seconds",
                       "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "helloasso_tickets", "precommande_id", "TEXT")
        _ensure_column(conn, "helloasso_tickets", "participant_name", "TEXT")
        _ensure_column(conn, "helloasso_tickets", "ticket_number", "TEXT")
        _ensure_column(conn, "helloasso_tickets", "tarif", "TEXT")
        _ensure_column(conn, "helloasso_tickets", "order_date", "TEXT")
        _ensure_column(conn, "helloasso_tickets", "payer_email", "TEXT")
        # Step 3 — create indexes once we know the columns exist.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_helloasso_precommande "
            "ON helloasso_tickets(precommande_id)"
        )


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
        # Tickets stay imported — operators don't want to re-upload a CSV after
        # every reset — but their redemption is cleared so they're reusable.
        conn.execute(
            "UPDATE helloasso_tickets SET redeemed_at = NULL, order_id = NULL"
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


# ── Hello Asso tickets ────────────────────────────────────────────────────────

def _row_to_ticket(row) -> dict:
    d = dict(row)
    if isinstance(d.get("items"), str):
        d["items"] = json.loads(d["items"])
    return d


def import_helloasso_tickets(rows: list[dict], replace: bool) -> dict:
    """Bulk-insert tickets. Each row dict must have qr_code, items (dict).
    Optional keys: customer_name, precommande_id, participant_name,
    ticket_number, tarif, order_date, payer_email.

    `replace=True` clears the table first (typical for a fresh CSV upload).
    Returns counters: {imported, skipped_duplicate, total_in_db}.
    """
    imported = 0
    skipped = 0
    now = _now()
    with get_connection() as conn:
        if replace:
            conn.execute("DELETE FROM helloasso_tickets")
        for r in rows:
            qr = r.get("qr_code")
            items = r.get("items") or {}
            if not qr or not isinstance(items, dict):
                continue
            try:
                conn.execute(
                    "INSERT INTO helloasso_tickets "
                    "(qr_code, customer_name, items, imported_at, precommande_id, "
                    "participant_name, ticket_number, tarif, order_date, payer_email) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (qr, r.get("customer_name"), json.dumps(items), now,
                     r.get("precommande_id") or None,
                     r.get("participant_name") or None,
                     r.get("ticket_number") or None,
                     r.get("tarif") or None,
                     r.get("order_date") or None,
                     r.get("payer_email") or None),
                )
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1
        total = conn.execute("SELECT COUNT(*) FROM helloasso_tickets").fetchone()[0]
    return {"imported": imported, "skipped_duplicate": skipped, "total_in_db": total}


def _canonical_qr(raw: str) -> str:
    """Reduce a scanned QR payload to the ticket-number prefix stored in DB.

    Hello Asso QR codes carry the **base64 encoding** of "<ticket>:<event>",
    e.g. `MTg3ODU4OTUzOjYzOTE1ODM3MjU3OTg2MzczMw==` decodes to
    `187858953:639158372579863733`. The CSV export only holds the ticket
    number, so to look up a scan we must:
      1. fall back to the prefix when ':' is already present in the raw
         value (covers operators who paste a pre-decoded QR by hand), and
      2. otherwise try a base64 decode and split on ':' to handle the
         normal camera-scanned payload.
    Whatever we cannot decode is returned unchanged so the caller can still
    try a direct exact-match lookup.
    """
    if not raw:
        return raw
    if ":" in raw:
        return raw.split(":", 1)[0]
    try:
        import base64
        decoded = base64.b64decode(raw, validate=False).decode("ascii")
    except Exception:
        return raw
    return decoded.split(":", 1)[0] if ":" in decoded else decoded


def get_helloasso_ticket(qr_code: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM helloasso_tickets WHERE qr_code = ?", (qr_code,)
        ).fetchone()
        if row is None:
            canon = _canonical_qr(qr_code)
            if canon and canon != qr_code:
                row = conn.execute(
                    "SELECT * FROM helloasso_tickets WHERE qr_code = ?", (canon,)
                ).fetchone()
    return _row_to_ticket(row) if row else None


def get_helloasso_precommande(qr_code: str) -> dict | None:
    """Return the scanned ticket + all unredeemed siblings sharing its precommande_id.

    None if the QR is unknown. If the ticket has no precommande_id, the returned
    dict still contains the single ticket — letting the caller treat it as a
    one-element group with no special handling.
    """
    seed = get_helloasso_ticket(qr_code)
    if seed is None:
        return None
    precommande_id = seed.get("precommande_id")
    if not precommande_id:
        return {
            "precommande_id": None,
            "seed": seed,
            "tickets": [seed],
            "aggregated_items": seed.get("items", {}),
        }
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM helloasso_tickets WHERE precommande_id = ? "
            "AND (redeemed_at IS NULL OR qr_code = ?) ORDER BY qr_code",
            (precommande_id, qr_code),
        ).fetchall()
    tickets = [_row_to_ticket(r) for r in rows]
    aggregated: dict[str, int] = {}
    for t in tickets:
        for item_id, qty in (t.get("items") or {}).items():
            aggregated[item_id] = aggregated.get(item_id, 0) + qty
    return {
        "precommande_id": precommande_id,
        "seed": seed,
        "tickets": tickets,
        "aggregated_items": aggregated,
    }


def redeem_helloasso_ticket(qr_code: str, order_id: int) -> bool:
    """Mark a ticket as redeemed against a specific order. Idempotent: returns
    False if the ticket is unknown or already redeemed. Falls back to the
    Hello Asso prefix when the raw QR isn't found verbatim."""
    canon = _canonical_qr(qr_code)
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE helloasso_tickets SET redeemed_at = ?, order_id = ? "
            "WHERE qr_code = ? AND redeemed_at IS NULL",
            (_now(), order_id, qr_code),
        )
        if cur.rowcount == 0 and canon != qr_code:
            cur = conn.execute(
                "UPDATE helloasso_tickets SET redeemed_at = ?, order_id = ? "
                "WHERE qr_code = ? AND redeemed_at IS NULL",
                (_now(), order_id, canon),
            )
        return cur.rowcount > 0


def list_helloasso_precommandes(search: str | None = None) -> list[dict]:
    """Return all precommandes as a tree, optionally filtered by a substring
    matching surname, order number, ticket number or payer email.

    Each precommande aggregates its tickets along with the order number it
    was redeemed in (joined from the orders table) so the UI can link back
    to the Commandes screen.
    """
    sql = """
        SELECT ht.*, o.number AS order_number
        FROM helloasso_tickets ht
        LEFT JOIN orders o ON o.id = ht.order_id
        ORDER BY ht.order_date DESC, ht.precommande_id, ht.ticket_number
    """
    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
    for r in rows:
        if isinstance(r.get("items"), str):
            r["items"] = json.loads(r["items"])

    # Apply the search filter if any. Case-insensitive substring across the
    # name/email/order/ticket fields.
    needle = (search or "").strip().lower()
    def matches(r: dict) -> bool:
        if not needle:
            return True
        haystack = " ".join(str(r.get(k) or "") for k in (
            "customer_name", "participant_name", "payer_email",
            "precommande_id", "ticket_number",
        )).lower()
        return needle in haystack

    rows = [r for r in rows if matches(r)]

    # Group by precommande_id (tickets sharing the same Hello Asso order).
    # Cash-payment rows (no precommande_id) are grouped per row via a synthetic
    # key so each appears as its own one-line precommande.
    groups: dict[str, dict] = {}
    for r in rows:
        gid = r.get("precommande_id") or f"single:{r['qr_code']}"
        g = groups.get(gid)
        if g is None:
            g = {
                "precommande_id": r.get("precommande_id"),
                "date": r.get("order_date"),
                "customer_name": r.get("customer_name"),
                "payer_email": r.get("payer_email"),
                "tickets": [],
                "redeemed_count": 0,
            }
            groups[gid] = g
        g["tickets"].append({
            "qr_code": r["qr_code"],
            "ticket_number": r.get("ticket_number"),
            "participant_name": r.get("participant_name"),
            "tarif": r.get("tarif"),
            "items": r.get("items") or {},
            "redeemed_at": r.get("redeemed_at"),
            "order_id": r.get("order_id"),
            "order_number": r.get("order_number"),
        })
        if r.get("redeemed_at"):
            g["redeemed_count"] += 1

    out = list(groups.values())
    for g in out:
        g["total_tickets"] = len(g["tickets"])
        g["fully_redeemed"] = g["redeemed_count"] == g["total_tickets"]
        g["any_redeemed"] = g["redeemed_count"] > 0
    return out


def get_helloasso_summary() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM helloasso_tickets").fetchone()[0]
        redeemed = conn.execute(
            "SELECT COUNT(*) FROM helloasso_tickets WHERE redeemed_at IS NOT NULL"
        ).fetchone()[0]
    return {"total": total, "redeemed": redeemed, "remaining": total - redeemed}


def clear_helloasso_tickets() -> int:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM helloasso_tickets")
        return cur.rowcount


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
