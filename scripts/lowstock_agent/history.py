"""Price/stock history capture (the V2 deal-signal feature, captured from V1).

Writes one snapshot per low-stock item per run into `price_history`. Runs once
per batch, before the per-item fan-out, so checks/deal.py sees the current point.
Deterministic, no LLM, idempotent on (sku, scraped_at).
"""
from typing import Optional

from .parsing import is_in_stock, parse_jpy, parse_stock_count

_PRICE_KEYS = (
    "price_jpy", "price_php", "price_sgd", "price_usd",
    "price_myr", "price_thb", "price_idr",
)


def build_snapshot(item: dict, source: str) -> Optional[dict]:
    sku = item.get("sku")
    scraped_at = item.get("scraped_at")
    if not sku or not scraped_at:
        return None  # can't key a snapshot without both
    stock = item.get("stock")
    prices = {k: item.get(k) for k in _PRICE_KEYS if item.get(k) is not None}
    return {
        "sku": sku,
        "name": item.get("name"),
        "price_jpy": parse_jpy(item.get("price_jpy")),
        "prices": prices,
        "stock_raw": stock,
        "stock_count": parse_stock_count(stock),
        "in_stock": is_in_stock(stock),
        "scraped_at": scraped_at,
        "source": source,
    }


def capture_history(supabase, items: list[dict], source: str) -> int:
    """Upsert snapshots for all items. Returns the number of snapshots sent."""
    rows = [s for s in (build_snapshot(i, source) for i in items) if s]
    if not rows:
        return 0
    # ignore_duplicates -> ON CONFLICT (sku, scraped_at) DO NOTHING
    supabase.table("price_history").upsert(
        rows, on_conflict="sku,scraped_at", ignore_duplicates=True
    ).execute()
    return len(rows)
