# gunpla_official_news

Official-first Gunpla announcements collector. Outputs a JSON array of normalized items
(`models.NewsItem`) to stdout. Designed to be piped into n8n / Supabase later.

## Sources (first batch, official-only)

| Module | Source | Region |
|---|---|---|
| `sources.gundam_info`     | Gundam.info Gunpla topic     | GLOBAL |
| `sources.bandai_hobby`    | Bandai Hobby Site            | JP |
| `sources.p_bandai`        | Premium Bandai (limited kits)| GLOBAL |
| `sources.bandai_news`     | Bandai.com news              | US |
| `sources.gundam_official` | GUNDAM Official (gundam.net) | GLOBAL |

Non-official domains are dropped at `verification.is_official_url`.

## Install + run

```powershell
pip install -r scripts/gunpla_official_news/requirements.txt
python -m gunpla_official_news.runner > news.json
```

Run from the `scripts/` directory so the package imports resolve. Logs go to stderr;
the JSON array goes to stdout.

## Add a new official source

1. Create `sources/<name>.py` with a `Scraper(BaseScraper)` class implementing `collect()`.
2. Add its hostname to `OFFICIAL_DOMAINS` in `config.py`.
3. Register the module path in `SOURCES` in `config.py`.

That's it — `runner.py` discovers it via the registry.

## Verified-news pipeline (ARCHITECTURE.md contract)

On top of the raw collector above, the package implements the full
`ARCHITECTURE.md` Working Data / confidence / source-tier / image-verification
contract.

| Module | Role |
|---|---|
| `http_client.py`    | `UrllibTransport` (direct HTTP, browser UA) and `FixtureTransport` (recorded source set). No `web_search`, no Firecrawl. |
| `article_parser.py` | Level 2 extraction: title, `datePublished`, series tags, categories, summary, body, images, price/release/exclusivity. |
| `verification.py`   | Two-axis labelling: 5 source tiers, 4 confidence labels, the mandatory-checks gate, the Reddit >=3-post rule. |
| `images.py`         | HTTP HEAD verification (`200` + `image/*`), `resized_Rectangle_*` exclusion, `reuse_not_permitted` flag. |
| `working_data.py`   | Column table: build, sort (confidence desc, then `datePublished` desc), render, and the markdown -> JSON export. |
| `brief.py`          | `verified_brief_<date>.md` with the four documented sections. |
| `pipeline.py`       | Wires Levels 1-3 and writes the three output files. |
| `n8n_push.py`       | Ports `post_to_n8n.py`'s exact payload contract: POSTs `{brief_text, working_data, job_id, run_at}` + `X-Hermes-Secret` header to the "Hermes News Webhook Ingest" n8n webhook. Fail-soft (never raises, never exits non-zero). |
| `scheduler.py`      | Native APScheduler-style runner (mirrors `scripts/lowstock_agent/scheduler.py`'s pattern) -- fires the pipeline on an interval, then pushes its output via `n8n_push`. No Hermes-side cron/config involved. |

### Run it

```powershell
# offline, against the bundled recorded source set
$env:PYTHONPATH = "scripts"
python -m gunpla_official_news.pipeline --fixtures --date 2026-09-06 --output-dir output

# live (direct HTTP against the real sources)
python -m gunpla_official_news.pipeline --live --output-dir output

# focused brief
python -m gunpla_official_news.pipeline --fixtures --topic "life-size gundam odaiba"
```

Outputs (all UTF-8, LF):
`output/verified_brief_<date>.md`, `output/working_data_<date>.md`,
`output/working_data_<date>.json`.

### Regenerate the fixture source set

```powershell
python scripts/gunpla_official_news/fixtures/build_fixtures.py
```

It covers all five source tiers, all four confidence labels, three image edge
cases (site chrome / 404 / non-image content-type) and both Reddit branches
(corroborated and blocked) in one run.

### Push to n8n / run the scheduler

```powershell
# one-off push of an already-produced run (parity with post_to_n8n.py's CLI)
$env:N8N_WEBHOOK_URL = "http://localhost:5679/webhook/hermes-gunpla-news"
$env:N8N_WEBHOOK_SECRET = "<shared secret>"
python -m gunpla_official_news.n8n_push --brief-file output/verified_brief_2026-09-06.md `
    --data-file output/working_data_2026-09-06.json --job-id gunpla-news-2026-09-06 `
    --run-at 2026-09-06T09:00:00+08:00

# native scheduled runner (fires the pipeline on an interval, then pushes its
# output) -- no Hermes cron involved at all
$env:GUNPLA_NEWS_RUN_INTERVAL_HOURS = "24"
$env:GUNPLA_NEWS_USE_FIXTURES = "true"   # omit/false for live HTTP
python -m gunpla_official_news.scheduler
```

Both `N8N_WEBHOOK_URL` / `N8N_WEBHOOK_SECRET` are the exact same env var names
the Hermes `gunpla-news-gatherer` skill's `post_to_n8n.py` already reads --
one shared secret config powers either delivery path. Missing either one is
not an error: the push is skipped (logged to stderr) and the caller still
exits 0.

## Notes

- Selectors in each source module are conservative stubs with `TODO` markers. Tighten
  them against live HTML before relying on output.
- Dedupe key: SHA-256 of `source_name | source_url | headline | product_name_official | release_month`.
- Schema lives in `models.NewsItem` — keep changes additive so downstream consumers stay safe.
- The Working Data contract lives in `models.WORKING_DATA_COLUMNS` /
  `WORKING_DATA_FIELDS` / `WORKING_DATA_JSON_KEYS` (three index-aligned tuples).
  See `../../CONTRACT-NOTES.md` for the documented "18 columns vs 17 names"
  discrepancy and how it was resolved.
- **Always pass `encoding="utf-8"` when opening a file.** This box's locale
  default is cp1252; `tests/test_encoding_convention.py` enforces the rule over
  the AST of every new/changed module.
