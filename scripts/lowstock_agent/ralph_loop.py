"""Ralph loop — a single agent in a tight, persistent loop (vs. batch fan-out).

This is the deliberate counterpart to orchestrator.py. The orchestrator does
**breadth**: many independent items, one LLM pass each, fanned out concurrently.
This does **depth**: ONE agent works ONE draft at a time and *iterates* —
generate a caption, run a deterministic checker, and if it fails, re-prompt the
SAME agent with the exact failures, repeating until the caption passes (or it hits
the attempt cap). Then it advances to the next draft.

State lives in the DB (the saved `suggested_caption`), so the loop is resumable
and idempotent: a caption that already passes the checker is skipped on the next
run.

When to use which:
  - Batch fan-out (orchestrator.py): independent items, throughput, no per-item
    iteration needed. Parallelism wins.
  - Ralph loop (this): a quality bar that needs self-correction per item, where the
    agent must look at its own failed output and fix it. Convergence > throughput.

    python -m scripts.lowstock_agent.ralph_loop --max-drafts 20 --max-attempts 4
"""
import argparse
import asyncio
import sys
from typing import Optional

from pydantic import BaseModel

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from .config import get_supabase, settings


class PolishedCaption(BaseModel):
    caption: str
    hashtags: list[str]


# ── The checker (deterministic — the loop's exit condition) ──────────────────
SCARCITY_CUES = ("left", "stock", "only", "last", "limited", "grab")
BANNED_TOKENS = ("[", "]", "todo", "lorem", "placeholder", "insert ")


def check_caption(caption: str, hashtags: list) -> list[str]:
    """Return a list of failed checks (empty list = passes)."""
    caption = caption or ""
    hashtags = hashtags or []
    fails = []
    n = len(caption)
    if n < 60:
        fails.append(f"too short ({n} chars; need >= 60)")
    if n > 280:
        fails.append(f"too long ({n} chars; need <= 280)")
    if not any(c in caption.lower() for c in SCARCITY_CUES):
        fails.append("no scarcity/urgency cue (reference the low stock)")
    if not (3 <= len(hashtags) <= 6):
        fails.append(f"need 3-6 hashtags (got {len(hashtags)})")
    if any(b in caption.lower() for b in BANNED_TOKENS):
        fails.append("contains a placeholder/banned token")
    if hashtags and not all(str(t).startswith("#") for t in hashtags):
        fails.append("every hashtag must start with '#'")
    return fails


SYSTEM_PROMPT = (
    "You are a copywriter for the MEGALLANICA Gunpla deals page (Southeast Asian "
    "buyers). Write ONE Facebook caption (60-280 characters) for a low-stock Gunpla "
    "deal, plus 3-6 hashtags (each starting with '#'). Reference the limited stock. "
    "No price, no URL, no placeholders. If told your previous attempt failed checks, "
    "fix every one of them."
)


async def generate(item: dict, prior_failures: list[str]) -> Optional[PolishedCaption]:
    feedback = ""
    if prior_failures:
        feedback = (
            "Your previous attempt FAILED these checks — fix ALL of them:\n- "
            + "\n- ".join(prior_failures)
            + "\n\n"
        )
    prompt = (
        feedback
        + "Write the caption for this low-stock Gunpla kit.\n"
        + f"name: {item.get('name')}\n"
        + f"grade: {item.get('grade_normalized')}\n"
        + f"scale: {item.get('scale_ai')}\n"
        + f"stock: {item.get('stock')}\n"
    )
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=settings.CAPTION_MODEL,
        allowed_tools=[],
        setting_sources=[],
        max_turns=4,
        output_format={"type": "json_schema", "schema": PolishedCaption.model_json_schema()},
        env={"ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY},
    )
    structured = None
    err = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if getattr(message, "is_error", False):
                    err = message.result or "unknown error"        # e.g. "Credit balance is too low"
                elif message.subtype == "success" and message.structured_output:
                    structured = message.structured_output
    except Exception as exc:
        err = err or str(exc)
    if err and structured is None:
        print(f"      WARN generate: {err}")
    return PolishedCaption.model_validate(structured) if structured else None


def fetch_candidates(sb, limit: int) -> list[dict]:
    res = (
        sb.table("agent_drafts")
        .select("id,sku,name,grade_normalized,scale_ai,stock,suggested_caption,suggested_hashtags")
        .eq("qualified", True)
        .eq("status", "draft")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


def needs_polish(d: dict) -> bool:
    return bool(check_caption(d.get("suggested_caption") or "", d.get("suggested_hashtags") or []))


async def polish_one(sb, d: dict, max_attempts: int) -> bool:
    """Tight inner loop: iterate the SAME agent until the checker passes."""
    prior: list[str] = []
    for attempt in range(1, max_attempts + 1):
        cand = await generate(d, prior)
        if not cand:
            print(f"    attempt {attempt}: no output")
            continue
        fails = check_caption(cand.caption, cand.hashtags)
        if not fails:
            sb.table("agent_drafts").update(
                {"suggested_caption": cand.caption, "suggested_hashtags": cand.hashtags}
            ).eq("id", d["id"]).execute()
            print(f"    attempt {attempt}: PASS ({len(cand.caption)} chars) -> saved")
            return True
        print(f"    attempt {attempt}: fail -> {fails}")
        prior = fails
    print(f"    gave up after {max_attempts} attempts")
    return False


async def run(max_drafts: int, max_attempts: int) -> None:
    sb = get_supabase()
    # Outer loop over the backlog; needs_polish defines what's left to do.
    candidates = [d for d in fetch_candidates(sb, max_drafts * 3) if needs_polish(d)][:max_drafts]
    print(f"Ralph loop: {len(candidates)} qualified draft(s) need a passing caption")
    processed = passed = 0
    for d in candidates:
        print(f"  - {d['sku']}  {(d.get('name') or '')[:48]}")
        processed += 1
        if await polish_one(sb, d, max_attempts):
            passed += 1
    print(f"\nDone: {processed} processed, {passed} now pass the checker")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="scripts.lowstock_agent.ralph_loop")
    ap.add_argument("--max-drafts", type=int, default=20, help="max drafts to process this run")
    ap.add_argument("--max-attempts", type=int, default=4, help="checker retries per draft")
    args = ap.parse_args(argv)
    asyncio.run(run(args.max_drafts, args.max_attempts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
