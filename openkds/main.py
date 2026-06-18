from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import (
    FastAPI, HTTPException, WebSocket, WebSocketDisconnect,
    Request, Header, UploadFile, File,
)
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import load_config, save_config, update_config
from .database import (
    init_db, insert_order, get_order_by_id, get_all_orders, get_orders_by_status,
    set_order_status, add_order_delay, delete_all_orders, update_grill_stock, get_stats,
    import_helloasso_tickets, get_helloasso_ticket, redeem_helloasso_ticket,
    get_helloasso_summary, clear_helloasso_tickets, get_helloasso_precommande,
)
from .models import (
    OrderCreate, OrderStatusUpdate, OrderDelayUpdate, OrderStatus,
    GrillStockUpdate, PrinterTestRequest, ConfigUpdate,
)
from .grill import get_grill_state
from .menu import get_menu_items, get_workshops, get_ticket_workshops, get_printers, compute_order_components
from .printers import try_get_printer, print_with_status
from .renderer import render_ticket, print_test_ticket

logger = logging.getLogger(__name__)
AUTO_DELIVERY_TICK_SECONDS = 30

FRONTEND_DIR = Path(__file__).parent / "frontend"

connected_clients: list[WebSocket] = []

# Printer connection cache — avoids re-opening libusb on every request.
_printer_cache: dict[str, object] = {}


def _get_cached_printer(device: str):
    if not device:
        return None, "Device not configured"
    if device in _printer_cache:
        return _printer_cache[device], None
    p, err = try_get_printer(device)
    if p is not None:
        _printer_cache[device] = p
    return p, err


def _invalidate_printer(device: str):
    _printer_cache.pop(device, None)


def _device_for(printer_id: str, config: dict) -> str:
    return config.get("printer_devices", {}).get(printer_id, "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    auto_task = asyncio.create_task(_auto_delivery_loop())
    try:
        yield
    finally:
        auto_task.cancel()
        try:
            await auto_task
        except asyncio.CancelledError:
            pass
        for p in _printer_cache.values():
            try:
                p.close()
            except Exception:
                pass


app = FastAPI(title="OpenKDS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


async def broadcast(message: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


# ── Captive portal ────────────────────────────────────────────────────────────

@app.get("/generate_204")
async def generate_204():
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/hotspot-detect.html")
@app.get("/success.html")
async def captive_success():
    return HTMLResponse("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")

@app.get("/connecttest.txt")
async def connecttest():
    return PlainTextResponse("Microsoft Connect Test")

@app.get("/ncsi.txt")
async def ncsi():
    return PlainTextResponse("Microsoft NCSI")


# ── SPA ───────────────────────────────────────────────────────────────────────

_SPA_PATHS = ("/", "/orders", "/stats", "/settings", "/grill")


@app.get("/", response_class=HTMLResponse)
@app.get("/orders", response_class=HTMLResponse)
@app.get("/stats", response_class=HTMLResponse)
@app.get("/settings", response_class=HTMLResponse)
@app.get("/grill", response_class=HTMLResponse)
async def serve_index():
    """SPA entry point — every known route serves the same index.html."""
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/favicon.ico")
async def favicon():
    """Browsers may request /favicon.ico directly outside /static/."""
    from fastapi.responses import FileResponse, Response
    f = FRONTEND_DIR / "favicon.ico"
    if f.exists():
        return FileResponse(f)
    return Response(status_code=404)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(ws) if hasattr(connected_clients, "discard") else None
        if ws in connected_clients:
            connected_clients.remove(ws)


# ── Menu & workshops ──────────────────────────────────────────────────────────

@app.get("/api/menu")
async def get_menu():
    config = load_config()
    color_overrides = config.get("button_colors", {})
    return [
        {**item, "color": color_overrides.get(item["id"], item.get("color", "#888"))}
        for item in get_menu_items()
    ]


@app.get("/api/workshops")
async def api_workshops():
    return get_workshops()


# ── Orders ────────────────────────────────────────────────────────────────────

def _build_workshop_context(order: dict, workshop: dict, config: dict) -> dict:
    items_map = {i["id"]: i for i in get_menu_items()}
    order_items: dict[str, int] = order.get("items", {})
    ws_id = workshop["id"]

    workshop_items = []
    workshop_components: dict[str, int] = {}
    for item_id, qty in order_items.items():
        if qty <= 0 or item_id not in items_map:
            continue
        item = items_map[item_id]
        if ws_id not in item.get("workshops", []):
            continue
        workshop_items.append({
            "id": item_id,
            "label": item["label"],
            "qty": qty,
            "components": item.get("components", {}),
        })
        for comp, mult in item.get("components", {}).items():
            workshop_components[comp] = workshop_components.get(comp, 0) + mult * qty

    return {
        "order": {
            "id": order["id"],
            "number": order["number"],
            "created_at": order["created_at"],
            "items": order_items,
        },
        "config": config,
        "workshop": workshop,
        "workshop_items": workshop_items,
        "workshop_components": workshop_components,
        "order_components": compute_order_components(order_items),
    }


def _print_order(order: dict, config: dict) -> dict[str, dict]:
    """Print all ticket workshops. Returns {printer_id: {ok, error}}."""
    printer_results: dict[str, dict] = {}

    for ws in get_ticket_workshops():
        ws_id = ws["id"]
        printer_id = ws.get("printer", "")
        template_name = ws.get("template", f"{ws_id}.j2")

        ctx = _build_workshop_context(order, ws, config)
        if not ctx["workshop_items"]:
            continue

        device = _device_for(printer_id, config)
        printer, _ = _get_cached_printer(device)

        r = print_with_status(printer, lambda p, t=template_name, c=ctx: render_ticket(p, t, c))
        if not r["ok"]:
            _invalidate_printer(device)

        # Accumulate: a printer is ok only if ALL its workshops succeed
        if printer_id not in printer_results:
            printer_results[printer_id] = r
        elif not r["ok"]:
            printer_results[printer_id] = r

    return printer_results


@app.post("/api/orders")
async def create_order(order_data: OrderCreate):
    # Validate item IDs exist in menu
    valid_ids = {i["id"] for i in get_menu_items()}
    unknown = [k for k in order_data.items if k not in valid_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown item IDs: {unknown}")

    config = load_config()
    number = config["next_order_number"]
    save_config({**config, "next_order_number": number + 1})

    items = {k: v for k, v in order_data.items.items() if v > 0}
    order = insert_order(number, items)

    # Tie any Hello Asso tickets the cashier attached. Best-effort: a failure
    # to redeem (already used, unknown QR) doesn't block the order — the
    # cashier already committed by clicking VALIDER. The frontend decides
    # which QRs to attach: a single scanned ticket in single mode, the whole
    # precommande group in group mode (the cashier ticked "tout ou rien").
    qrs_to_redeem: list[str] = []
    if order_data.helloasso_qr:
        qrs_to_redeem.append(order_data.helloasso_qr)
    if order_data.helloasso_qrs:
        qrs_to_redeem.extend(order_data.helloasso_qrs)
    for qr in qrs_to_redeem:
        redeem_helloasso_ticket(qr, order["id"])

    printer_results = _print_order(order, config)

    grill_state = get_grill_state(config)
    await broadcast({
        "type": "order_created",
        "order": _enrich_order(order, config),
        "grill": grill_state,
    })

    all_ok = all(r["ok"] for r in printer_results.values())
    if not all_ok:
        for printer_id, r in printer_results.items():
            if not r["ok"]:
                await broadcast({
                    "type": "printer_error",
                    "printer": printer_id,
                    "message": f"{printer_id}: {r['error']}",
                })

    response = {
        "id": order["id"],
        "number": order["number"],
        "created_at": order["created_at"],
        **{f"{k}_status": "ok" if v["ok"] else (v["error"] or "error")
           for k, v in printer_results.items()},
    }
    return JSONResponse(content=response, status_code=200 if all_ok else 207)


def _enrich_order(order: dict, config: dict) -> dict:
    """Attach computed timestamps (epoch seconds) to the order.

    - `created_at_ts` is always set: epoch seconds derived from `created_at`.
      The client must use this for time math instead of parsing the display
      string, which would otherwise produce different epoch values when the
      server and the browser run in different timezones (typical of Docker:
      UTC container + local browser).
    - `auto_delivery_at` is the absolute target time for auto-delivery, or
      None when the order is not in_preparation or auto-delivery is disabled.
    """
    enriched = dict(order)
    created = datetime.fromisoformat(order["created_at"])
    enriched["created_at_ts"] = created.timestamp()

    if order.get("status") != "en_preparation" or not config.get("auto_delivery_enabled"):
        enriched["auto_delivery_at"] = None
        return enriched
    minutes = config.get("auto_delivery_minutes", 20)
    delay = order.get("delivery_delay_seconds", 0)
    target = created + timedelta(seconds=minutes * 60 + delay)
    enriched["auto_delivery_at"] = target.timestamp()
    return enriched


@app.get("/api/orders")
async def list_orders(status: str | None = None):
    config = load_config()
    if status:
        orders = get_orders_by_status(status)
    else:
        orders = get_all_orders()
    return [_enrich_order(o, config) for o in orders]


@app.patch("/api/orders/{order_id}/status")
async def patch_order_status(order_id: int, payload: OrderStatusUpdate):
    if get_order_by_id(order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order = set_order_status(order_id, payload.status.value)
    config = load_config()
    enriched = _enrich_order(order, config)
    await broadcast({"type": "order_status_changed", "order": enriched})
    # Demand changes when an order leaves en_preparation
    await broadcast({"type": "grill_updated", "grill": get_grill_state(config)})
    return enriched


@app.post("/api/orders/{order_id}/delay")
async def push_order_delay(order_id: int, payload: OrderDelayUpdate):
    order = get_order_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] != "en_preparation":
        raise HTTPException(status_code=409, detail="Order is not in preparation")
    order = add_order_delay(order_id, payload.additional_seconds)
    enriched = _enrich_order(order, load_config())
    await broadcast({"type": "order_status_changed", "order": enriched})
    return enriched


@app.post("/api/orders/{order_id}/reprint")
async def reprint_order(order_id: int):
    order = get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    config = load_config()
    printer_results = _print_order(order, config)
    return {f"{k}_status": "ok" if v["ok"] else (v["error"] or "error")
            for k, v in printer_results.items()}


@app.delete("/api/orders")
async def reset_orders(x_confirm_reset: str = Header(None, alias="X-Confirm-Reset")):
    if x_confirm_reset != "yes":
        raise HTTPException(status_code=400, detail="Header X-Confirm-Reset: yes required")
    delete_all_orders()
    update_config({"next_order_number": 1})
    return {"reset": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_statistics():
    return get_stats(get_menu_items())


# ── Grill ─────────────────────────────────────────────────────────────────────

@app.get("/api/grill")
async def get_grill():
    return get_grill_state(load_config())


@app.put("/api/grill/stock")
async def update_grill(request: Request):
    updates: dict[str, int] = await request.json()
    update_grill_stock(updates)
    state = get_grill_state(load_config())
    await broadcast({"type": "grill_updated", "grill": state})
    return state


# ── i18n ─────────────────────────────────────────────────────────────────────

_AVAILABLE_LANGS = ("fr", "en")


def _load_locale(lang: str) -> dict:
    from importlib import resources
    if lang not in _AVAILABLE_LANGS:
        lang = "fr"
    pkg = resources.files("openkds.locales").joinpath(f"{lang}.json")
    return json.loads(pkg.read_text(encoding="utf-8"))


@app.get("/api/i18n")
async def api_i18n(lang: str | None = None):
    """Return the requested language dict (or the one configured by the user)."""
    chosen = lang or load_config().get("ui_lang", "fr")
    if chosen not in _AVAILABLE_LANGS:
        chosen = "fr"
    return {"lang": chosen, "available": list(_AVAILABLE_LANGS), "strings": _load_locale(chosen)}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return load_config()


@app.put("/api/config")
async def put_config(data: ConfigUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    config = update_config(updates)
    if any(k in updates for k in
           ("grill_window_minutes", "grill_segment_size", "grill_demand_threshold")):
        await broadcast({"type": "grill_updated", "grill": get_grill_state(config)})
    return config


# ── Printers ──────────────────────────────────────────────────────────────────

# ── Hello Asso pre-paid tickets ───────────────────────────────────────────────

def _parse_helloasso_csv(text: str, valid_item_ids: set[str]) -> list[dict]:
    """Parse OpenKDS' canonical Hello Asso CSV format.

    Expected columns:
      - qr_code (required) — the raw QR payload, stored as opaque key
      - customer_name (optional)
      - precommande_id (optional) — groups tickets from the same Hello Asso
        order so the operator can redeem them in one scan ("group" mode).
      - one column per menu item ID, the cell value is the integer quantity
      - any other column is ignored

    Returns a list of dicts ready for import_helloasso_tickets().
    """
    import csv, io
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        qr = (raw.get("qr_code") or "").strip()
        if not qr:
            continue
        items: dict[str, int] = {}
        for col, val in raw.items():
            if col not in valid_item_ids:
                continue
            try:
                q = int(val) if val else 0
            except (TypeError, ValueError):
                q = 0
            if q > 0:
                items[col] = q
        rows.append({
            "qr_code": qr,
            "customer_name": (raw.get("customer_name") or "").strip() or None,
            "precommande_id": (raw.get("precommande_id") or "").strip() or None,
            "items": items,
        })
    return rows


@app.post("/api/helloasso/import")
async def helloasso_import(file: UploadFile = File(...),
                           x_replace: str = Header("yes", alias="X-Replace")):
    """Upload a CSV and replace (default) or merge the existing tickets."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # tolerate Excel BOM
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    valid_ids = {i["id"] for i in get_menu_items()}
    rows = _parse_helloasso_csv(text, valid_ids)
    return import_helloasso_tickets(rows, replace=(x_replace.lower() in ("yes", "1", "true")))


@app.get("/api/helloasso/summary")
async def helloasso_summary():
    return get_helloasso_summary()


@app.get("/api/helloasso/ticket/{qr_code:path}")
async def helloasso_get(qr_code: str):
    t = get_helloasso_ticket(qr_code)
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@app.get("/api/helloasso/precommande/{qr_code:path}")
async def helloasso_precommande(qr_code: str):
    """Return the scanned ticket + all unredeemed siblings from the same
    Hello Asso order. Used by the cashier's "Ajouter toute la commande"
    toggle in the scan modal."""
    g = get_helloasso_precommande(qr_code)
    if g is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return g


@app.delete("/api/helloasso/tickets")
async def helloasso_clear(x_confirm_reset: str = Header(None, alias="X-Confirm-Reset")):
    if x_confirm_reset != "yes":
        raise HTTPException(status_code=400, detail="Header X-Confirm-Reset: yes required")
    deleted = clear_helloasso_tickets()
    return {"deleted": deleted}


# ── Printers ──────────────────────────────────────────────────────────────────

@app.get("/api/printers")
async def api_printers():
    """Return all declared printers with their device path and connection status."""
    from .printers import get_printer_status
    config = load_config()
    result = []
    for p in get_printers():
        pid = p["id"]
        device = _device_for(pid, config)
        printer, err = _get_cached_printer(device)
        if printer:
            status = get_printer_status(printer)
        else:
            status = {"connected": False, "paper_ok": False, "error": err}
        result.append({**p, "device": device, "status": status})
    return result


@app.post("/api/printers/test")
async def printers_test(data: PrinterTestRequest):
    config = load_config()
    results = {}
    targets = [p["id"] for p in get_printers()] if data.printer == "all" else [data.printer]
    for pid in targets:
        device = _device_for(pid, config)
        p, _ = _get_cached_printer(device)
        r = print_with_status(p, lambda p, name=pid: print_test_ticket(p, name))
        if not r["ok"]:
            _invalidate_printer(device)
        results[pid] = "ok" if r["ok"] else (r["error"] or "error")
    return results


async def _auto_delivery_loop():
    """Periodically mark in-preparation orders as delivered once their target time passes.

    Runs every AUTO_DELIVERY_TICK_SECONDS. Cheap when there are few orders.
    No-ops when auto_delivery_enabled is False in config.
    """
    while True:
        try:
            await asyncio.sleep(AUTO_DELIVERY_TICK_SECONDS)
            config = load_config()
            if not config.get("auto_delivery_enabled"):
                continue
            minutes = config.get("auto_delivery_minutes", 20)
            now_ts = datetime.now().timestamp()
            delivered_any = False
            for order in get_orders_by_status("en_preparation"):
                created = datetime.fromisoformat(order["created_at"])
                target = created + timedelta(seconds=minutes * 60 + order.get("delivery_delay_seconds", 0))
                if now_ts >= target.timestamp():
                    updated = set_order_status(order["id"], "livre")
                    if updated:
                        await broadcast({
                            "type": "order_status_changed",
                            "order": _enrich_order(updated, config),
                            "auto": True,
                        })
                        delivered_any = True
            if delivered_any:
                await broadcast({"type": "grill_updated", "grill": get_grill_state(config)})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("auto-delivery loop iteration failed")


def main():
    import uvicorn
    uvicorn.run("openkds.main:app", host="0.0.0.0", port=8000)
