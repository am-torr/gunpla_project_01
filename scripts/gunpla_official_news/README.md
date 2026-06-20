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

## Notes

- Selectors in each source module are conservative stubs with `TODO` markers. Tighten
  them against live HTML before relying on output.
- Dedupe key: SHA-256 of `source_name | source_url | headline | product_name_official | release_month`.
- Schema lives in `models.NewsItem` — keep changes additive so downstream consumers stay safe.
