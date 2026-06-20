"""Canonical NewsItem schema. One dataclass, one factory, one serializer."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class NewsItem:
    source_name: str = ""
    source_url: str = ""
    source_type: str = "news_article"  # news_article|product_page|event_page|social_post
    region: str = ""
    language: str = ""

    headline: str = ""
    body_summary: str = ""

    announcement_type: str = "new_kit"  # new_kit|reissue|accessory|event|campaign|price_change

    product_name_official: Optional[str] = None
    line: Optional[str] = None
    grade: Optional[str] = None
    scale: Optional[str] = None
    series: Optional[str] = None
    limited_flag: bool = False
    category: Optional[str] = None

    preorder_open_at: Optional[str] = None
    preorder_close_at: Optional[str] = None
    release_month: Optional[str] = None

    price_local: Optional[float] = None
    currency: Optional[str] = None
    stock_status: Optional[str] = None

    event_name: Optional[str] = None
    event_type: Optional[str] = None
    event_start_at: Optional[str] = None
    event_end_at: Optional[str] = None
    location: Optional[str] = None

    images: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    canonical_product_id: Optional[str] = None
    scraped_at: str = ""
    source_record_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_item(**overrides: Any) -> NewsItem:
    """Factory that stamps scraped_at and applies overrides."""
    item = NewsItem(scraped_at=_now_iso())
    for k, v in overrides.items():
        if hasattr(item, k):
            setattr(item, k, v)
    return item
