"""Orchestrator — capture history, classify (batched), fan out checks, build copy, draft.

Flow per run:
  1. capture_history(all items)                 # snapshot price+stock (no LLM)
  2. classify_items(all items)                  # batched Haiku, mirrors post_queue_stg AI cols
  3. for each item, in parallel (semaphore-limited):
        gather( dedup [DB], deal [DB] )
        gate: is_gunpla AND NOT posted_recently AND stock-urgency-qualifies
              (V2: AND is_real_deal, when settings.USE_PRICE_DELTA_GATE)
        build deterministic post_copy (parity with 02) over a shortened link
        if gated AND ENABLE_SUGGESTED_CAPTION -> LLM suggested_caption
        write draft row into agent_drafts
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

from .checks.deal import analyze_deal
from .checks.dedup import check_dedup
from .config import get_supabase, settings
from .drafts import build_draft_row, insert_draft
from .history import capture_history
from .postcopy import build_post_copy
from .shortener import shorten
from .subagents.caption import write_caption
from .subagents.classifier import classify_items


@dataclass
class RunStats:
    total: int = 0
    snapshots: int = 0
    qualified: int = 0
    written: int = 0


def _gate(classification, dedup: dict, deal: dict) -> tuple[bool, str]:
    reasons = []
    if not classification.is_gunpla:
        reasons.append("not_gunpla")
    if dedup["posted_recently"]:
        reasons.append("posted_recently")
    stock_ok = (
        deal["stock_urgency"] is not None
        and deal["stock_urgency"] <= settings.STOCK_URGENCY_THRESHOLD
    )
    if not stock_ok:
        reasons.append("stock_not_urgent")
    if settings.USE_PRICE_DELTA_GATE and not deal.get("is_real_deal"):
        reasons.append("not_real_deal")

    qualified = not reasons
    return qualified, ("qualified" if qualified else "blocked:" + ",".join(reasons))


async def process_item(supabase, item: dict, classification, dry_run: bool, stats: RunStats) -> dict:
    sku = item.get("sku")

    dedup, deal = await asyncio.gather(
        asyncio.to_thread(check_dedup, supabase, sku),
        asyncio.to_thread(analyze_deal, supabase, item),
    )

    qualified, gate_reason = _gate(classification, dedup, deal)

    # Deterministic post copy (production parity). Skip the network shortener on dry runs.
    link = item.get("affiliate_url")
    if not dry_run:
        link = await shorten(link)
    post_copy = build_post_copy(item, link)

    suggested = None
    caption_tone = None
    if qualified:
        stats.qualified += 1
        if settings.ENABLE_SUGGESTED_CAPTION:
            suggested, caption_tone = await write_caption(item, classification)

    row = build_draft_row(
        item, classification, dedup, deal, qualified, gate_reason,
        post_copy=post_copy, short_link=link,
        suggested=suggested, caption_tone=caption_tone,
    )

    if not dry_run:
        await asyncio.to_thread(insert_draft, supabase, row)
        stats.written += 1

    flag = "[QUALIFIED]" if qualified else "[skip]     "
    print(
        f"  {flag}  {sku}  gunpla={row['is_gunpla']} "
        f"type={row['product_type_ai']} stock={row['stock_urgency']} "
        f"recent={row['posted_recently']}  [{gate_reason}]"
    )
    return row


async def run(items: list[dict], dry_run: bool = False) -> RunStats:
    stats = RunStats(total=len(items))
    supabase = get_supabase()

    if dry_run:
        print(f"DRY RUN - {len(items)} items, no DB writes (history + drafts skipped)")
    else:
        stats.snapshots = await asyncio.to_thread(
            capture_history, supabase, items, settings.AGENT_SOURCE_SYSTEM
        )
        print(f"Captured {stats.snapshots} price_history snapshot(s)")

    # Batched classification up front (cheap Haiku, hard-reject prefilter).
    classifications = await classify_items(items)
    print(f"Classified {len(items)} item(s)")

    sem = asyncio.Semaphore(settings.MAX_CONCURRENCY)

    async def guarded(it: dict) -> dict:
        async with sem:
            cls = classifications.get(it.get("sku"))
            return await process_item(supabase, it, cls, dry_run, stats)

    await asyncio.gather(*(guarded(it) for it in items))

    print(
        f"\nDone: {stats.total} items | {stats.qualified} qualified | "
        f"{stats.written} drafts written"
        + (" (dry run)" if dry_run else "")
    )
    return stats
