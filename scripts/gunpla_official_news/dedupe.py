"""Hash-based dedupe across the merged item stream."""
from __future__ import annotations

import hashlib
from typing import Iterable

from .models import NewsItem


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def compute_source_record_hash(item: NewsItem) -> str:
    """Stable hash of normalized identifying fields."""
    key = "|".join([
        _norm(item.source_name),
        _norm(item.source_url),
        _norm(item.headline),
        _norm(item.product_name_official),
        _norm(item.release_month),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def dedupe(items: Iterable[NewsItem]) -> list[NewsItem]:
    """Stamp source_record_hash and drop later duplicates (first-seen wins)."""
    seen: set[str] = set()
    out: list[NewsItem] = []
    for it in items:
        h = compute_source_record_hash(it)
        if h in seen:
            continue
        seen.add(h)
        it.source_record_hash = h
        out.append(it)
    return out
