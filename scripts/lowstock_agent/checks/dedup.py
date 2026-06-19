"""Sub-agent 2 — dedup checker (deterministic, no LLM).

Calls the read-only `check_repost_cooldown` RPC, which reuses the exact
post_queue -> post_queue_batch cooldown join from import_post_queue_stg.sql.
Never inserts into the n8n tables.

Returns: {posted_recently, post_count_30d, last_posted_at}
"""
from .. import config


def _empty() -> dict:
    return {"posted_recently": False, "post_count_30d": 0, "last_posted_at": None}


def check_dedup(supabase, sku: str) -> dict:
    s = config.settings
    try:
        resp = supabase.rpc(
            "check_repost_cooldown",
            {
                "p_source_type": s.DEDUP_SOURCE_TYPE,
                "p_source_id": sku,
                "p_days": s.REPOST_COOLDOWN_DAYS,
            },
        ).execute()
    except Exception as exc:  # surface but don't crash the whole run
        print(f"  WARN dedup({sku}): {exc}")
        return _empty()

    data = resp.data or {}
    if isinstance(data, list):  # some PostgREST versions wrap scalar returns
        data = data[0] if data else {}
    return {
        "posted_recently": bool(data.get("posted_recently", False)),
        "post_count_30d": int(data.get("post_count_30d", 0) or 0),
        "last_posted_at": data.get("last_posted_at"),
    }
