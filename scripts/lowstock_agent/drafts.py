"""Write draft records into `agent_drafts` (the agent's own table — never n8n's)."""
import hashlib
from typing import Optional

from .config import settings


def content_hash(item: dict) -> str:
    key = f"{item.get('sku')}|{item.get('scraped_at')}|{settings.AGENT_SOURCE_SYSTEM}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _image_urls(item: dict) -> list:
    urls = item.get("image_urls")
    if isinstance(urls, list) and urls:
        return urls
    single = item.get("image_url")
    return [single] if single else []


def build_draft_row(
    item: dict,
    classification,
    dedup: dict,
    deal: dict,
    qualified: bool,
    gate_reason: str,
    post_copy: str,
    short_link: Optional[str],
    suggested,
    caption_tone: Optional[str],
) -> dict:
    return {
        "sku": item.get("sku"),
        "name": item.get("name"),
        "source_system": settings.AGENT_SOURCE_SYSTEM,
        "source_type": settings.DEDUP_SOURCE_TYPE,
        "scraped_at": item.get("scraped_at"),
        "content_hash": content_hash(item),
        "raw_item": item,
        # classification (mirrors post_queue_stg AI columns)
        "is_gunpla": classification.is_gunpla,
        "grade_normalized": classification.grade_normalized,
        "scale_ai": classification.scale_ai,
        "product_type_ai": classification.product_type_ai,
        "brand_ai": classification.brand_ai,
        "audience_ai": classification.audience_ai,
        "classification_confidence": classification.classification_confidence,
        "ai_notes": classification.ai_notes,
        # dedup
        "posted_recently": dedup["posted_recently"],
        "last_posted_at": dedup["last_posted_at"],
        "post_count_30d": dedup["post_count_30d"],
        # deal
        "stock": item.get("stock"),
        "stock_urgency": deal["stock_urgency"],
        "deal_signal": deal["deal_signal"],
        "price_delta_pct": deal["price_delta_pct"],
        "stock_trend": deal["stock_trend"],
        "is_real_deal": deal["is_real_deal"],
        "deal_confidence": deal["deal_confidence"],
        # content: deterministic post_copy (production parity) + optional LLM suggestion
        "post_copy": post_copy,
        "short_link": short_link,
        "suggested_caption": (suggested.caption if suggested else None),
        "suggested_hashtags": (suggested.hashtags if suggested else []),
        "caption_tone": caption_tone,
        # media
        "image_urls": _image_urls(item),
        "affiliate_url": item.get("affiliate_url"),
        # review
        "qualified": qualified,
        "gate_reason": gate_reason,
        "status": "draft",
    }


def insert_draft(supabase, row: dict) -> None:
    # ignore_duplicates -> ON CONFLICT (content_hash) DO NOTHING (idempotent re-runs)
    supabase.table("agent_drafts").upsert(
        row, on_conflict="content_hash", ignore_duplicates=True
    ).execute()
