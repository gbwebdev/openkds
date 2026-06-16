from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import load_config, save_config, update_config
from .database import (
    init_db, insert_order, get_order_by_id, get_all_orders,
    delete_all_orders, update_grill_stock, get_stats,
)
from .models import OrderCreate, GrillStockUpdate, PrinterTestRequest, ConfigUpdate
from .grill import get_grill_state
from .menu import get_menu_items, get_workshops, get_ticket_workshops, get_printers, compute_order_components
from .printers import try_get_printer, print_with_status
from .renderer import render_ticket, print_test_ticket

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
    yield
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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
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

    printer_results = _print_order(order, config)

    grill_state = get_grill_state(config)
    await broadcast({"type": "order_created", "grill": grill_state})

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


@app.get("/api/orders")
async def list_orders():
    return get_all_orders()


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


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return load_config()


@app.put("/api/config")
async def put_config(data: ConfigUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    config = update_config(updates)
    if "grill_window_minutes" in updates or "grill_segment_size" in updates:
        await broadcast({"type": "grill_updated", "grill": get_grill_state(config)})
    return config


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


def main():
    import uvicorn
    uvicorn.run("openkds.main:app", host="0.0.0.0", port=8000)
