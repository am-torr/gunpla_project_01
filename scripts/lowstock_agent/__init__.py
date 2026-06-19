"""
lowstock_agent
==============
Claude Agent SDK port of the HLJ low-stock pipeline (V1).

Runs in PARALLEL to the existing n8n workflow — it never auto-posts and never
writes to n8n's tables. It only produces draft records in `agent_drafts` for a
human to review, and accumulates price/stock snapshots in `price_history`.

Run on demand:
    python -m scripts.lowstock_agent --threshold 5 --limit 20
    python -m scripts.lowstock_agent --dry-run --input scripts/lowstock_agent/fixtures/sample_low_stock.json
"""
