from __future__ import annotations

import math
from datetime import datetime, timedelta

from . import database
from .menu import get_menu_items, get_dashboard_workshops, get_stock_buckets


def compute_demand(window_minutes: int) -> dict:
    """Sum component demand from in-preparation orders within the time window.

    Delivered and cancelled orders no longer represent things to cook, so they
    don't contribute to demand.
    """
    cutoff = (datetime.now() - timedelta(minutes=window_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    orders = database.get_orders_since(cutoff, status="en_preparation")
    items_map = {i["id"]: i for i in get_menu_items()}

    demand: dict[str, int] = {}
    for order in orders:
        for item_id, qty in order.get("items", {}).items():
            if qty <= 0 or item_id not in items_map:
                continue
            for comp, mult in items_map[item_id].get("components", {}).items():
                demand[comp] = demand.get(comp, 0) + mult * qty
    return demand


def compute_gauge(demand: int, stock_bucket_index: int, segment_size: int) -> int:
    buckets = get_stock_buckets()
    if stock_bucket_index >= len(buckets):
        stock_bucket_index = len(buckets) - 1
    midpoint = buckets[stock_bucket_index]["midpoint"]
    net = max(0, demand - midpoint)
    segments = math.ceil(net / segment_size) if segment_size > 0 else 0
    return min(4, segments)


def get_grill_state(config: dict) -> dict:
    window_minutes = config.get("grill_window_minutes", 20)
    segment_size = config.get("grill_segment_size", 6)

    demand = compute_demand(window_minutes)
    stock = database.get_grill_stock()
    buckets = get_stock_buckets()

    dashboards = {}
    for ws in get_dashboard_workshops():
        tracks = ws.get("tracks", [])
        track_labels = ws.get("track_labels", {t: t for t in tracks})
        gauges = {
            t: compute_gauge(demand.get(t, 0), stock.get(t, 0), segment_size)
            for t in tracks
        }
        dashboards[ws["id"]] = {
            "tracks": tracks,
            "track_labels": track_labels,
            "demand": {t: demand.get(t, 0) for t in tracks},
            "stock": {t: stock.get(t, 0) for t in tracks},
            "gauges": gauges,
            "stock_buckets": buckets,
            "window_minutes": window_minutes,
            "segment_size": segment_size,
        }

    return {"dashboards": dashboards}
