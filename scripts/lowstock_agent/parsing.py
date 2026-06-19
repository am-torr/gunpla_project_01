"""Small deterministic parsers, reusing the project's gunpla rules where possible.

Pulls the gunpla prefilter + grade extraction from app/hlj_helpers.py so the
classifier's cheap prefilter stays in sync with the existing scraper rules.
Falls back to local minimal versions if that module can't be imported.
"""
import re
from typing import Optional

try:  # reuse the canonical rules from the scraper
    from app.hlj_helpers import (
        NON_GUNPLA_SKU_PREFIXES,
        extract_grade_scale,
        is_gunpla,
        parse_price,
    )
except Exception:  # pragma: no cover - fallback if app package isn't importable
    NON_GUNPLA_SKU_PREFIXES = ("ABA", "KBY", "AZM", "KPM", "AZMP", "HBJ", "GNZ")
    _GRADE = re.compile(r"\b(MGEX|MGSD|PG|MG|RG|EG|SD|BB|HG[A-Z]{0,6})\b", re.I)
    _SCALE = re.compile(r"1/(144|100|60|48|35)", re.I)

    def parse_price(text):
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", str(text))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def extract_grade_scale(name: str) -> str:
        m = _GRADE.search(name or "")
        return m.group(1).upper() if m else "Unknown"

    def is_gunpla(name: str, sku: str) -> bool:
        if (sku or "").upper().startswith(NON_GUNPLA_SKU_PREFIXES):
            return False
        return bool(_GRADE.search(name or "") or _SCALE.search(name or ""))


_ONLY_N = re.compile(r"only\s+(\d+)\s+left", re.I)


def parse_stock_count(stock: Optional[str]) -> Optional[int]:
    """'Only 3 left in stock.' -> 3 ; None if not parseable."""
    if not stock:
        return None
    m = _ONLY_N.search(stock)
    return int(m.group(1)) if m else None


def is_in_stock(stock: Optional[str]) -> Optional[bool]:
    if not stock:
        return None
    s = stock.lower()
    if "out of stock" in s or "sold out" in s:
        return False
    return True


def parse_jpy(value) -> Optional[float]:
    """Accept '¥4,241' or a number -> 4241.0."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_price(value)


def sku_excluded(sku: str) -> bool:
    """True if the SKU prefix is a known non-gunpla category (books, tools, etc.)."""
    return (sku or "").upper().startswith(NON_GUNPLA_SKU_PREFIXES)
