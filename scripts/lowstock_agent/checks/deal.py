"""Sub-agent 3 — deal analyzer (deterministic, no LLM).

V1: with <2 price_history snapshots for the SKU, the deal signal is stock
urgency parsed from the 'stock' string ('Only N left').

V2 (auto-activates): once >=2 snapshots exist, compute a real price_delta_pct
(current vs. the rolling max in the window) and a stock_trend, and set
is_real_deal. No code change is needed to switch on — only the gate in
orchestrator.py (settings.USE_PRICE_DELTA_GATE) decides whether to *require* it.

Returns: {stock_urgency, deal_signal, price_delta_pct, stock_trend,
          is_real_deal, deal_confidence, history_points}
"""
from datetime import datetime, timedelta, timezone

from .. import config
from ..parsing import parse_stock_count


def _fallback(stock_urgency, points: int) -> dict:
    return {
        "stock_urgency": stock_urgency,
        "deal_signal": "stock_urgency_v1",
        "price_delta_pct": None,
        "stock_trend": None,
        "is_real_deal": None,
        "deal_confidence": 0.30,
        "history_points": points,
    }


def analyze_deal(supabase, item: dict) -> dict:
    s = config.settings
    sku = item.get("sku")
    stock_urgency = parse_stock_count(item.get("stock"))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=s.REPOST_COOLDOWN_DAYS)).isoformat()
    try:
        resp = (
            supabase.table("price_history")
            .select("price_jpy,stock_count,scraped_at")
            .eq("sku", sku)
            .gte("scraped_at", cutoff)
            .order("scraped_at", desc=False)
            .execute()
        )
        rows = resp.data or []
    except Exception as exc:
        print(f"  WARN deal({sku}): {exc}")
        return _fallback(stock_urgency, 0)

    prices = [r["price_jpy"] for r in rows if r.get("price_jpy") is not None]
    counts = [r["stock_count"] for r in rows if r.get("stock_count") is not None]

    if len(prices) < 2:
        return _fallback(stock_urgency, len(prices))

    baseline = max(prices)              # highest price seen in the window
    current = prices[-1]                # most recent (captured this run)
    price_delta_pct = round((current - baseline) / baseline * 100, 2) if baseline else None

    stock_trend = None
    if len(counts) >= 2:
        if counts[-1] < counts[0]:
            stock_trend = "falling"
        elif counts[-1] > counts[0]:
            stock_trend = "rising"
        else:
            stock_trend = "flat"

    is_real_deal = price_delta_pct is not None and price_delta_pct <= -s.DEAL_DROP_PCT
    deal_confidence = round(min(1.0, len(prices) / 5.0), 2)

    return {
        "stock_urgency": stock_urgency,
        "deal_signal": "price_delta_v2",
        "price_delta_pct": price_delta_pct,
        "stock_trend": stock_trend,
        "is_real_deal": is_real_deal,
        "deal_confidence": deal_confidence,
        "history_points": len(prices),
    }
