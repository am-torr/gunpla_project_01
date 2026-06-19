# gunpla-tracker — agent notes

## Low-stock Agent SDK pipeline (`scripts/lowstock_agent`)

A Claude Agent SDK port of the HLJ low-stock pipeline that runs **in parallel to
the existing n8n workflow — it does not replace it**. n8n keeps owning scraping
and Facebook auto-posting. This agent only produces **drafts for a human to
review**; it never posts.

### Hard boundary (do not cross)
- The agent writes ONLY to **`agent_drafts`** (its drafts) and **`price_history`**
  (its snapshots), and reads `post_queue` / `post_queue_batch` **read-only** via
  the `check_repost_cooldown` RPC.
- It must NEVER write to n8n's tables: `post_queue`, `post_queue_stg`,
  `post_queue_batch`, `hlj_posts`.
- No auto-posting. No scheduling (run on demand). Runs as a local script,
  outside the Docker stack.

### Orchestration pattern (hybrid)
One async orchestrator. Deterministic checks are plain Python run in parallel;
the LLM is used only where it adds value.

```
fetch /low-stock ──> capture_history(all items)   # snapshot price+stock (no LLM)
                 ──> classify_items(all items)     # batched Haiku -> post_queue_stg AI cols
                 ──> per item, asyncio.gather(
                       dedup()  # DB — check_repost_cooldown RPC -> posted_recently,...
                       deal()   # DB — price_history -> price_delta/stock_trend, else stock-urgency
                     )
                     gate: is_gunpla AND NOT posted_recently AND stock-urgency-qualifies
                     post_copy = deterministic template (parity with n8n "02") over a shortened link
                     if gated -> suggested_caption()  # optional LLM — caption-generator tones
                     write row -> agent_drafts (status='draft')
```

- Per-item fan-out is `asyncio.gather`; blocking Supabase calls are wrapped in
  `asyncio.to_thread`. Concurrency across items is capped by `MAX_CONCURRENCY`.
- **Classifier** (`subagents/classifier.py`) follows the gunpla-classifier skill:
  hard-reject prefilter (SKU prefix / keyword / price) with no LLM, then a
  **batched Haiku** call for the rest. Output mirrors the live `post_queue_stg` AI
  columns (`grade_normalized`, `scale_ai`, `product_type_ai`, `brand_ai`,
  `audience_ai`, `classification_confidence`, `ai_notes`).
- **Post copy** (`postcopy.py`) is deterministic and matches n8n `02`'s
  "Build Facebook Post Copy" exactly; the link is shortened Bitly→TinyURL→affiliate
  (`shortener.py`). `suggested_caption` is an *optional* LLM extra for the reviewer.

### Parity with the live n8n `02 - Create Post Queue Candidates`
Verified against the exported active workflow. `02` reads pre-staged `post_queue_stg`
rows, builds a **deterministic** post copy (no LLM), shortens the link, and inserts
into `post_queue` via the `import_post_queue` RPC (dedup = `ON CONFLICT
(source_type,source_id) WHERE status NOT IN ('posted','rejected','archived')`).
This agent integrates the upstream classification step too, and writes only to
`agent_drafts` — never to `post_queue`. The LLM caption + price-history/deal signal
are deliberate enhancements that `02` does not have.

### Deal-signal lifecycle (V1 → V2)
- **V1 (now):** every run captures a `price_history` snapshot, and the caption
  gate uses **stock urgency** ("Only N left", `N <= STOCK_URGENCY_THRESHOLD`).
- **V2 (auto-activates):** once a SKU has ≥2 snapshots, `checks/deal.py` computes
  a real `price_delta_pct` + `stock_trend` and sets `is_real_deal`
  (`deal_signal='price_delta_v2'`). To make the gate *require* it, set
  `USE_PRICE_DELTA_GATE=true` — that is the only change needed.

### Running it
Prerequisites: Python 3.12, and the **Claude Code CLI** on PATH (the Python
Agent SDK drives it as a subprocess): `npm install -g @anthropic-ai/claude-code`.

```bash
pip install -r scripts/lowstock_agent/requirements.txt

# Offline dry run on the bundled fixture (no DB writes):
python -m scripts.lowstock_agent --dry-run \
  --input scripts/lowstock_agent/fixtures/sample_low_stock.json

# Live run (needs the hlj-lowstock service on :8001 and Supabase reachable):
python -m scripts.lowstock_agent --threshold 5 --limit 20
```

### Config / env (`.env`, reused from the rest of the project)
- `ANTHROPIC_API_KEY` — the key already provisioned for RAG.
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — backend read/write.
- `HLJ_LOWSTOCK_URL` (default `http://localhost:8001`), `DEDUP_SOURCE_TYPE`
  (default `hlj` — matches what n8n writes to `post_queue`), `REPOST_COOLDOWN_DAYS`,
  `STOCK_URGENCY_THRESHOLD` (default 5, matches `02`), `DEAL_DROP_PCT`,
  `USE_PRICE_DELTA_GATE`, `CLASSIFIER_MODEL` (default `haiku`), `CLASSIFIER_BATCH_SIZE`,
  `CAPTION_MODEL` (default `sonnet`), `ENABLE_SUGGESTED_CAPTION`, `ENABLE_SHORTENER`,
  `BITLY_ACCESS_TOKEN`, `MAX_CONCURRENCY`. See `scripts/lowstock_agent/config.py`.

### Database objects (this feature)
- `agent_drafts` — `m-hub-db/database/sql/agent_drafts.sql`
- `price_history` — `m-hub-db/database/sql/price_history.sql`
- `check_repost_cooldown(source_type, source_id, days)` —
  `m-hub-db/database/function/check_repost_cooldown.sql` (read-only; reuses the
  cooldown join from `import_post_queue_stg.sql`).
