# Runbook — Low-stock Agent SDK pipeline

Operational guide for `scripts/lowstock_agent`. For design/architecture see the root
[CLAUDE.md](../../CLAUDE.md).

## 1. What it is
A Claude Agent SDK pipeline that turns HLJ low-stock items into **draft** Facebook posts
for a human to review. It runs **in parallel to the n8n flow and never auto-posts**.

**Hard boundary:** writes ONLY to `agent_drafts` and `price_history`; reads `post_queue` /
`post_queue_batch` read-only via the `check_repost_cooldown` RPC. It must NEVER write to
`post_queue`, `post_queue_stg`, `post_queue_batch`, or `hlj_posts`.

**Where things live**
- Code: `scripts/lowstock_agent/` (runner, review UI, Ralph loop)
- DB objects: `m-hub-db/database/sql/agent_drafts.sql`, `price_history.sql`,
  `m-hub-db/database/function/check_repost_cooldown.sql`
- Input service: `hlj-lowstock` FastAPI (`:8001` host / `:8000` in-network)
- Review UI: `:8011`

## 2. Prerequisites
- **Python 3.12** + deps: `pip install -r scripts/lowstock_agent/requirements.txt`
- **Claude Code CLI on PATH** — the SDK drives it as a subprocess:
  `npm install -g @anthropic-ai/claude-code`
- **`.env`** keys: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
  (optional: `BITLY_ACCESS_TOKEN`)
- **DB migration applied** (additive): `agent_drafts`, `price_history`,
  `check_repost_cooldown`. Verify with the query in §7.
- **For live runs:** the `hlj-lowstock` service reachable (`docker compose up -d hlj-lowstock`).

## 3. Run modes

```bash
# Offline dry run on the bundled fixture — no DB writes, no scrape
python -m scripts.lowstock_agent --dry-run \
  --input scripts/lowstock_agent/fixtures/sample_low_stock.json

# On-demand live run (scrapes :8001, writes drafts + snapshots)
python -m scripts.lowstock_agent --threshold 5 --limit 20

# Ralph loop — polish qualified-draft captions until a checker passes
python -m scripts.lowstock_agent.ralph_loop --max-drafts 20 --max-attempts 4

# Scheduled + review UI as containers
docker compose up -d --build lowstock-agent lowstock-review
# review at http://<host>:8011  (mobile friendly)
```

CLI flags: `--threshold` (stock threshold), `--limit` (cap items), `--input <file>`
(read items from JSON instead of the API), `--dry-run` (no writes), `--source-type`.

## 4. Config (env, defaults in `config.py`)
| Var | Default | Notes |
|---|---|---|
| `HLJ_LOWSTOCK_URL` | `http://localhost:8001` | in Docker: `http://hlj-lowstock:8000` |
| `HLJ_FETCH_TIMEOUT` | `600` | scrape is a slow Playwright job — keep this high |
| `DEDUP_SOURCE_TYPE` | `hlj` | MUST match what n8n writes to `post_queue` |
| `REPOST_COOLDOWN_DAYS` | `30` | "posted recently" window |
| `STOCK_URGENCY_THRESHOLD` | `5` | qualify when stock_count <= this |
| `CLASSIFIER_MODEL` / `CAPTION_MODEL` | `haiku` / `sonnet` | set both to `haiku` to cut cost |
| `CLASSIFIER_BATCH_SIZE` | `20` | items per Haiku classify call |
| `ENABLE_SUGGESTED_CAPTION` / `ENABLE_SHORTENER` | `true` | |
| `USE_PRICE_DELTA_GATE` | `false` | V2: also require `is_real_deal` to qualify |
| `RUN_INTERVAL_HOURS` / `RUN_THRESHOLD` / `RUN_LIMIT` / `RUN_ON_START` | `6` / `5` / `20` / `false` | scheduled runner |
| `MAX_CONCURRENCY` | `4` | per-item fan-out cap |

## 5. Operate
- **Review drafts:** open `:8011` → Approve sets `status='approved'`, Reject sets
  `status='rejected'`. Or by SQL:
  `select sku,name,post_copy,suggested_caption,qualified,gate_reason from agent_drafts where status='draft';`
- **A draft "qualifies"** when `is_gunpla AND NOT posted_recently AND stock_urgency<=THRESHOLD`.
  Non-qualifying items are still saved (audit) with `qualified=false` + `gate_reason`.
- **Deal signal:** `stock_urgency_v1` until a SKU has >=2 `price_history` snapshots, then
  `price_delta_v2` auto-activates (`checks/deal.py`).

## 6. Troubleshooting — what to do when it breaks
| Symptom | Cause | Fix |
|---|---|---|
| `WARN ...: Credit balance is too low` | Anthropic **API** org out of prepaid credit | Top up at console.anthropic.com → Billing (the org that owns `ANTHROPIC_API_KEY`); enable auto-reload |
| `httpx.ReadTimeout` on fetch | `/low-stock` scrape > client timeout | raise `HLJ_FETCH_TIMEOUT` (default 600s); confirm `hlj-lowstock` healthy: `curl :8001/health` |
| `WARN dedup/deal: Could not find function/table` | migration not applied to this DB | apply `agent_drafts`/`price_history`/`check_repost_cooldown` (§7) |
| Dedup never matches (always `posted_recently=false`) | wrong `DEDUP_SOURCE_TYPE` | must be `hlj` (what n8n writes to `post_queue`), not `hlj_low_stock` |
| `Reached maximum number of turns (1)` | `max_turns` too low for structured output | already set to 4; don't lower it |
| Docker build `pip ResolutionImpossible` | loose version floors pick incompatible deps | requirements are pinned (supabase 2.31 + httpx 0.28.1) — keep pins |
| `UnicodeEncodeError 'charmap'` (Windows) | cp1252 console vs `¥`/`₱`/emoji | the entrypoints reconfigure stdout to UTF-8; run via `python -m ...` |
| Docker Desktop "Inference manager" crash on start | Docker AI / Model Runner stale socket | set `"EnableDockerAI": false` in `%APPDATA%\Docker\settings-store.json`, `wsl --shutdown`, rename `%LOCALAPPDATA%\Docker\run` aside, relaunch |
| `claude` CLI not found / SDK errors | Claude Code CLI missing | `npm install -g @anthropic-ai/claude-code`; ensure on PATH |

## 7. Verify / health
```sql
-- objects exist + RPC works
select
  (select count(*) from information_schema.tables where table_name='agent_drafts')  as has_drafts,
  (select count(*) from information_schema.tables where table_name='price_history')  as has_history,
  public.check_repost_cooldown('hlj','BAN225753',30)                                 as cooldown_probe;
```
```bash
curl :8001/health        # scraper
curl :8011/health        # review UI
python -m compileall -q scripts/lowstock_agent && echo OK   # syntax
```

## 8. Recovery / rollback
- **Resume after a crash:** just re-run — inserts are idempotent (`agent_drafts.content_hash`
  unique; `price_history (sku,scraped_at)` unique). The Ralph loop is resumable via the
  saved `suggested_caption`.
- **Restart services:** `docker compose restart lowstock-agent lowstock-review`
- **Full rollback (additive migration):**
  ```sql
  DROP FUNCTION IF EXISTS public.check_repost_cooldown(text,text,integer);
  DROP TABLE IF EXISTS public.agent_drafts;
  DROP TABLE IF EXISTS public.price_history;
  ```
  This removes only the agent's own objects; n8n's tables are untouched.
