import math
from datetime import datetime, timedelta
from . import database

STOCK_BUCKETS = [
    {"label": "0–6",  "min": 0,  "max": 6,  "midpoint": 3},
    {"label": "6–12", "min": 6,  "max": 12, "midpoint": 9},
    {"label": "12–18","min": 12, "max": 18, "midpoint": 15},
    {"label": "18+",  "min": 18, "max": 99, "midpoint": 21},
]


def compute_demand(window_minutes: int) -> dict:
    cutoff = (datetime.now() - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    orders = database.get_orders_since(cutoff)
    return {
        "merguez":  sum(2 * o["adulte_merguez"] + o["enfant_merguez"] for o in orders),
        "chipo":    sum(2 * o["adulte_chipo"]   + o["enfant_chipo"]   for o in orders),
        "saucisse": sum(o["galette_saucisse"] for o in orders),
    }


def compute_gauge(demand: int, stock_bucket_index: int, segment_size: int) -> int:
    stock_midpoint = STOCK_BUCKETS[stock_bucket_index]["midpoint"]
    net = max(0, demand - stock_midpoint)
    segments = math.ceil(net / segment_size) if segment_size > 0 else 0
    return min(4, segments)


def get_grill_state(config: dict) -> dict:
    window_minutes = config.get("grill_window_minutes", 20)
    segment_size = config.get("grill_segment_size", 6)

    demand = compute_demand(window_minutes)
    stock = database.get_grill_stock()

    gauges = {
        "merguez":  compute_gauge(demand["merguez"],  stock["merguez"],  segment_size),
        "chipo":    compute_gauge(demand["chipo"],    stock["chipo"],    segment_size),
        "saucisse": compute_gauge(demand["saucisse"], stock["saucisse"], segment_size),
    }

    return {
        "demand": demand,
        "stock": {
            "merguez":  stock["merguez"],
            "chipo":    stock["chipo"],
            "saucisse": stock["saucisse"],
        },
        "gauges": gauges,
        "window_minutes": window_minutes,
        "segment_size": segment_size,
    }
