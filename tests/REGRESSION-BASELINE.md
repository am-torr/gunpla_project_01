# Regression baseline — why there is no copied-in legacy suite

AC5 requires that "the existing `gunpla_official_news` / `lowstock_agent` test
suites still pass unchanged (no regression)".

**There are no such suites in the reference project.** Searched at copy-in time
against `D:\project\gunpla-tracker-verified` (read-only):

```
find . -path ./.git -prune -o -name "test_*.py" -print -o -name "*_test.py" -print
  -> ./doc-ingest/supabase_test.py
  -> ./tests/test_scrapers.py

grep -rn "^def test_|^async def test_|import pytest" --include=*.py .
  -> tests/test_scrapers.py            (only match)

find . -name conftest.py    -> (none)
ls pytest.ini setup.cfg pyproject.toml tox.ini   -> (none)
```

`tests/test_scrapers.py` is a **print-driven script**, not a pytest module: it
runs work at import time (`asyncio.get_event_loop_policy()...set_debug(True)`),
imports `app.comparison`, and exercises `app.scrapers.hobby_planet` /
`hobby_link_japan` against the **live network**. It covers neither
`gunpla_official_news` nor `lowstock_agent`. Copying it into this workspace
would add a network-dependent module that tests other code entirely.
`doc-ingest/supabase_test.py` is likewise unrelated (Supabase connectivity).

## What was done instead

`tests/test_regression_baseline.py` establishes "unchanged" two ways:

1. **Byte-level.** `tests/baseline_hashes.json` records the SHA-256 of every
   file copied from the reference project that this batch does **not** modify —
   31 files: `gunpla_official_news/{config,dedupe,runner,template,__init__}.py`,
   all five `sources/*.py`, every `lowstock_agent/**/*.py`, and
   `app/{__init__,hlj_helpers}.py`. One parametrised test per file asserts the
   hash still matches. Any edit to an untouched file fails loudly.

   The hashes were recorded **immediately after the copy and before any edit**,
   so they are the reference project's bytes, not this batch's.

2. **Behaviour-level.** Public behaviour of the pre-existing API is pinned:
   `NewsItem`'s exact field list and defaults, the `new_item` factory, the
   `dedupe` SHA-256 key formula (recomputed independently in the test — this
   value is persisted downstream, so changing it would silently re-post
   everything), `is_official_url` + the `OFFICIAL_DOMAINS` allowlist, the
   `SOURCES` registry order, the `BaseScraper` contract, and the
   `lowstock_agent` pure helpers (`parse_price`, `is_gunpla`,
   `parse_stock_count`, `extract_grade_scale`, `checks.deal.analyze_deal`).

## Files changed by this batch

Only these, all inside `scripts/gunpla_official_news/`:

| file | change |
|---|---|
| `models.py` | ADDED `WorkingDataRow` + the three column tuples. `NewsItem` untouched. |
| `verification.py` | ADDED tiers/labels/gate/Reddit rule. `is_official_url` byte-for-byte the same logic. |
| `images.py` | new |
| `working_data.py` | new |
| `brief.py` | new |
| `http_client.py` | new |
| `article_parser.py` | new |
| `pipeline.py` | new |
| `fixtures/` | new (recorded HTTP source set + its generator) |
| `README.md` | documentation only |

## Gotchas found while pinning the lowstock API

* `parsing.extract_grade_scale(name)` returns **one joined string**
  (`"MG 1/100"`), not a `(grade, scale)` tuple — unpacking it into two names
  raises `ValueError: too many values to unpack`.
* `parsing.is_gunpla(name, sku)` takes **two** required positional arguments.
* `checks/deal.py`'s public entry point is `analyze_deal`, not `evaluate`.
* `parsing.py` imports `app.hlj_helpers` inside a `try/except` and silently
  falls back to a local copy of the rules. `app/hlj_helpers.py` is therefore
  copied into this workspace as well — without it the fallback path runs and
  the "unchanged behaviour" claim would be measuring different code.
