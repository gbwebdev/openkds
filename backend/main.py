import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import load_config, update_config
from .database import (
    init_db, insert_order, get_order_by_id, get_all_orders,
    delete_all_orders, update_grill_stock, get_stats
)
from .models import OrderCreate, GrillStockUpdate, PrinterTestRequest, ConfigUpdate
from .grill import get_grill_state
from .printers import try_get_printer, print_with_status
from .tickets import print_client_ticket, print_assembly_ticket, print_billigs_ticket, print_test_ticket

MENU_ITEMS = [
    {
        "id": "adulte_merguez",
        "label": "Menu Adulte\nMerguez",
        "components": {"frites": 1, "merguez": 2, "boisson": 1}
    },
    {
        "id": "adulte_chipo",
        "label": "Menu Adulte\nChipolatas",
        "components": {"frites": 1, "chipo": 2, "boisson": 1}
    },
    {
        "id": "enfant_merguez",
        "label": "Menu Enfant\nMerguez",
        "components": {"frites": 1, "merguez": 1, "boisson": 1}
    },
    {
        "id": "enfant_chipo",
        "label": "Menu Enfant\nChipolatas",
        "components": {"frites": 1, "chipo": 1, "boisson": 1}
    },
    {
        "id": "galette_saucisse",
        "label": "Galette\nSaucisse",
        "components": {"saucisse": 1}
    },
    {
        "id": "barquette_frite",
        "label": "Barquette\nFrite",
        "components": {"frites": 1}
    },
]

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Bazaar KDS", lifespan=lifespan)
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


def _get_printers(config: dict):
    p1, e1 = try_get_printer(config.get("printer1_vendor_id", ""), config.get("printer1_product_id", ""))
    p2, e2 = try_get_printer(config.get("printer2_vendor_id", ""), config.get("printer2_product_id", ""))
    return (p1, e1), (p2, e2)


# ── Captive portal detection (Android / iOS / Windows) ───────────────────────
# dnsmasq resolves all DNS to 192.168.50.1; iptables redirects port 80 → 8000.
# Returning the expected responses prevents Android from falling back to mobile
# data and iOS from blocking the connection behind a captive portal prompt.

@app.get("/generate_204")
async def generate_204():
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/hotspot-detect.html")
async def hotspot_detect():
    return HTMLResponse("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")

@app.get("/success.html")
async def success_html():
    return HTMLResponse("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")

@app.get("/connecttest.txt")
async def connecttest():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("Microsoft Connect Test")

@app.get("/ncsi.txt")
async def ncsi():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("Microsoft NCSI")


# ── Static SPA ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index = FRONTEND_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


# ── Menu ─────────────────────────────────────────────────────────────────────

@app.get("/api/menu")
async def get_menu():
    config = load_config()
    colors = config.get("button_colors", {})
    items = []
    for item in MENU_ITEMS:
        items.append({**item, "color": colors.get(item["id"], "#cccccc")})
    return items


# ── Orders ───────────────────────────────────────────────────────────────────

@app.post("/api/orders")
async def create_order(order_data: OrderCreate):
    config = load_config()

    number = config["next_order_number"]
    config["next_order_number"] = number + 1

    from .config import save_config
    save_config(config)

    items = order_data.model_dump()
    order = insert_order(number, items)

    (p1, e1), (p2, e2) = _get_printers(config)

    # Printer 1 — client ticket
    r1 = print_with_status(p1, lambda p: print_client_ticket(p, order, config))

    # Printer 2 — assembly + optional billigs
    def print_p2(p):
        print_assembly_ticket(p, order)
        if order.get("galette_saucisse", 0) > 0:
            print_billigs_ticket(p, order)

    r2 = print_with_status(p2, print_p2)

    p1_status = "ok" if r1["ok"] else (r1["error"] or "error")
    p2_status = "ok" if r2["ok"] else (r2["error"] or "error")

    grill_state = get_grill_state(config)
    await broadcast({
        "type": "order_created",
        "grill": {
            "demand": grill_state["demand"],
            "gauges": grill_state["gauges"],
        }
    })

    if not r1["ok"] or not r2["ok"]:
        if not r1["ok"]:
            await broadcast({"type": "printer_error", "printer": 1, "message": f"Imprimante 1 : {r1['error']}"})
        if not r2["ok"]:
            await broadcast({"type": "printer_error", "printer": 2, "message": f"Imprimante 2 : {r2['error']}"})

    response = {
        "id": order["id"],
        "number": order["number"],
        "created_at": order["created_at"],
        "printer1_status": p1_status,
        "printer2_status": p2_status,
    }

    status_code = 207 if (not r1["ok"] or not r2["ok"]) else 200
    from fastapi.responses import JSONResponse
    return JSONResponse(content=response, status_code=status_code)


@app.get("/api/orders")
async def list_orders():
    return get_all_orders()


@app.post("/api/orders/{order_id}/reprint")
async def reprint_order(order_id: int):
    order = get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Commande introuvable")

    config = load_config()
    (p1, e1), (p2, e2) = _get_printers(config)

    r1 = print_with_status(p1, lambda p: print_client_ticket(p, order, config))

    def print_p2(p):
        print_assembly_ticket(p, order)
        if order.get("galette_saucisse", 0) > 0:
            print_billigs_ticket(p, order)

    r2 = print_with_status(p2, print_p2)

    return {
        "printer1_status": "ok" if r1["ok"] else (r1["error"] or "error"),
        "printer2_status": "ok" if r2["ok"] else (r2["error"] or "error"),
    }


@app.delete("/api/orders")
async def reset_orders(x_confirm_reset: str = Header(None, alias="X-Confirm-Reset")):
    if x_confirm_reset != "yes":
        raise HTTPException(status_code=400, detail="Header X-Confirm-Reset: yes requis")
    delete_all_orders()
    update_config({"next_order_number": 1})
    return {"reset": True}


# ── Stats ────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_statistics():
    return get_stats()


# ── Grill ─────────────────────────────────────────────────────────────────────

@app.get("/api/grill")
async def get_grill():
    config = load_config()
    return get_grill_state(config)


@app.put("/api/grill/stock")
async def update_grill(data: GrillStockUpdate):
    update_grill_stock(data.merguez, data.chipo, data.saucisse)
    config = load_config()
    state = get_grill_state(config)
    await broadcast({"type": "grill_updated", "grill": state})
    return state


# ── Config ───────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return load_config()


@app.put("/api/config")
async def put_config(data: ConfigUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    config = update_config(updates)

    # Broadcast grill update if window or segment changed
    if "grill_window_minutes" in updates or "grill_segment_size" in updates:
        state = get_grill_state(config)
        await broadcast({"type": "grill_updated", "grill": state})

    return config


# ── Printers ─────────────────────────────────────────────────────────────────

@app.get("/api/printers/status")
async def printers_status():
    config = load_config()
    (p1, e1), (p2, e2) = _get_printers(config)

    from .printers import get_printer_status

    if p1:
        s1 = get_printer_status(p1)
    else:
        s1 = {"connected": False, "paper_ok": False, "error": e1}

    if p2:
        s2 = get_printer_status(p2)
    else:
        s2 = {"connected": False, "paper_ok": False, "error": e2}

    return {"printer1": s1, "printer2": s2}


@app.post("/api/printers/test")
async def printers_test(data: PrinterTestRequest):
    config = load_config()
    (p1, e1), (p2, e2) = _get_printers(config)

    results = {}

    if data.printer in (1, "both"):
        r = print_with_status(p1, lambda p: print_test_ticket(p, 1))
        results["printer1"] = "ok" if r["ok"] else (r["error"] or "error")

    if data.printer in (2, "both"):
        r = print_with_status(p2, lambda p: print_test_ticket(p, 2))
        results["printer2"] = "ok" if r["ok"] else (r["error"] or "error")

    return results
