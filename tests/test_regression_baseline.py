"""AC5 -- no regression in the pre-existing gunpla_official_news / lowstock_agent code.

WHY THIS FILE EXISTS
--------------------
The reference project (D:\\project\\gunpla-tracker-verified) ships NO pytest suite
covering either package.  Searched at copy-in time:

    find . -name "test_*.py" -o -name "*_test.py"   ->  tests/test_scrapers.py
                                                        doc-ingest/supabase_test.py
    grep -rn "^def test_\\|import pytest" --include=*.py  ->  tests/test_scrapers.py only

``tests/test_scrapers.py`` is a print-driven script that exercises
``app.scrapers.hobby_planet`` / ``hobby_link_japan`` over the LIVE network and runs
work at import time; it covers neither ``gunpla_official_news`` nor
``lowstock_agent``, so copying it in would add a network-dependent, non-pytest
module and nothing else.  See tests/REGRESSION-BASELINE.md.

So "the existing suites still pass unchanged" is established the only way it can
be: by pinning the pre-existing PUBLIC BEHAVIOUR of both packages, plus a
byte-level hash baseline of every file this batch did not touch.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import pathlib
from dataclasses import fields as dataclass_fields

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = pathlib.Path(__file__).resolve().parent / "baseline_hashes.json"


# ---------------------------------------------------------------------------
# Byte-level: files this batch did not change must still be byte-identical
# ---------------------------------------------------------------------------


def _baseline() -> dict:
    with open(BASELINE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_baseline_manifest_is_populated():
    data = _baseline()
    assert len(data) >= 25
    assert "scripts/gunpla_official_news/dedupe.py" in data
    assert "scripts/lowstock_agent/parsing.py" in data


@pytest.mark.parametrize("relpath", sorted(_baseline().keys()))
def test_untouched_file_is_byte_identical(relpath):
    expected = _baseline()[relpath]
    path = ROOT / relpath
    assert path.is_file(), relpath
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, "%s was modified by this batch" % relpath


# ---------------------------------------------------------------------------
# gunpla_official_news -- pre-existing public behaviour
# ---------------------------------------------------------------------------


def test_news_item_field_set_is_unchanged():
    from gunpla_official_news.models import NewsItem

    assert [f.name for f in dataclass_fields(NewsItem)] == [
        "source_name", "source_url", "source_type", "region", "language",
        "headline", "body_summary", "announcement_type",
        "product_name_official", "line", "grade", "scale", "series",
        "limited_flag", "category",
        "preorder_open_at", "preorder_close_at", "release_month",
        "price_local", "currency", "stock_status",
        "event_name", "event_type", "event_start_at", "event_end_at", "location",
        "images", "tags", "sources",
        "canonical_product_id", "scraped_at", "source_record_hash",
    ]


def test_news_item_defaults_are_unchanged():
    from gunpla_official_news.models import NewsItem

    item = NewsItem()
    assert item.source_type == "news_article"
    assert item.announcement_type == "new_kit"
    assert item.limited_flag is False
    assert item.images == [] and item.tags == [] and item.sources == []
    assert item.product_name_official is None


def test_new_item_factory_still_stamps_and_ignores_unknown_keys():
    from gunpla_official_news.models import new_item

    item = new_item(headline="H", nonexistent_field="x")
    assert item.headline == "H"
    assert item.scraped_at.endswith("Z")
    assert not hasattr(item, "nonexistent_field")


def test_dedupe_hash_is_bit_for_bit_what_it_always_was():
    """The dedupe key is persisted downstream; changing it silently re-posts everything."""
    from gunpla_official_news.dedupe import compute_source_record_hash
    from gunpla_official_news.models import NewsItem

    item = NewsItem(
        source_name="Gundam.info",
        source_url="https://www.gundam.info/news/1",
        headline="HG Test Kit",
        product_name_official="HG 1/144 Test",
        release_month="2026-11",
    )
    expected_key = "|".join([
        "gundam.info",
        "https://www.gundam.info/news/1",
        "hg test kit",
        "hg 1/144 test",
        "2026-11",
    ])
    assert compute_source_record_hash(item) == hashlib.sha256(
        expected_key.encode("utf-8")
    ).hexdigest()


def test_dedupe_first_seen_wins_and_stamps_the_hash():
    from gunpla_official_news.dedupe import dedupe
    from gunpla_official_news.models import NewsItem

    a = NewsItem(headline="Same", source_url="u")
    b = NewsItem(headline="Same", source_url="u")
    c = NewsItem(headline="Other", source_url="v")
    out = dedupe([a, b, c])
    assert out == [a, c]
    assert a.source_record_hash and c.source_record_hash


def test_official_domain_allowlist_is_unchanged():
    # 2026-09-07: "gundam-official.com" was deliberately ADDED (not part of the
    # frozen baseline) -- en.gundam-official.com is the real, live GUNDAM
    # Official news site (confirmed against hermesmechanism/MECHANISM.md); it
    # was missing from this allowlist entirely, so real articles from it were
    # being silently dropped as unofficial. baseline_hashes.json's config.py
    # hash was updated to match. Every other domain here is untouched.
    from gunpla_official_news.config import OFFICIAL_DOMAINS
    from gunpla_official_news.verification import is_official_url

    assert OFFICIAL_DOMAINS == (
        "gundam.info", "en.gundam.info", "bandai-hobby.net", "p-bandai.com",
        "p-bandai.jp", "bandai.com", "gundam.net", "gundam-base.net",
        "gundam-official.com",
    )
    assert is_official_url("https://p-bandai.jp/item/1") is True
    assert is_official_url("https://sub.bandai-hobby.net/x") is True
    assert is_official_url("https://evil-bandai.com.attacker.net/x") is False
    assert is_official_url("https://en.gundam-official.com/news/x") is True


def test_source_registry_order_is_unchanged():
    from gunpla_official_news.config import SOURCES

    assert SOURCES == [
        "gunpla_official_news.sources.gundam_info",
        "gunpla_official_news.sources.bandai_hobby",
        "gunpla_official_news.sources.p_bandai",
        "gunpla_official_news.sources.bandai_news",
        "gunpla_official_news.sources.gundam_official",
    ]


def test_every_registered_source_still_imports_and_exposes_collect():
    from gunpla_official_news.config import SOURCES
    from gunpla_official_news.template import BaseScraper

    for path in SOURCES:
        mod = importlib.import_module(path)
        scraper_cls = getattr(mod, "Scraper")
        assert issubclass(scraper_cls, BaseScraper)
        assert callable(getattr(scraper_cls, "collect"))


def test_base_scraper_contract_is_unchanged():
    from gunpla_official_news.models import NewsItem
    from gunpla_official_news.template import BaseScraper

    with pytest.raises(NotImplementedError):
        BaseScraper().collect()

    kept = BaseScraper().drop_unofficial([
        NewsItem(source_url="https://www.gundam.info/news/1"),
        NewsItem(source_url="https://reddit.com/r/Gunpla"),
    ])
    assert len(kept) == 1
    assert kept[0].source_url == "https://www.gundam.info/news/1"


def test_runner_still_exposes_run_and_main():
    from gunpla_official_news import runner

    assert callable(runner.run)
    assert callable(runner.main)


# ---------------------------------------------------------------------------
# lowstock_agent -- pre-existing public behaviour (dependency-light modules only)
# ---------------------------------------------------------------------------


def test_lowstock_parsing_is_unchanged():
    from scripts.lowstock_agent import parsing

    assert parsing.parse_price("$12.34") == 12.34
    assert parsing.parse_price("") is None
    assert parsing.parse_price(None) is None
    assert parsing.is_gunpla("HG RX-78-2 Gundam", "BANS12345") is True
    assert parsing.is_gunpla("Anime Blu-ray Box", "ABA00001") is False


def test_lowstock_stock_count_parser_is_unchanged():
    from scripts.lowstock_agent.parsing import parse_stock_count

    assert parse_stock_count("Only 3 left") == 3
    assert parse_stock_count("In stock") is None
    assert parse_stock_count("") is None


def test_lowstock_grade_extraction_is_unchanged():
    """``extract_grade_scale`` returns ONE joined string, not a (grade, scale) pair."""
    from scripts.lowstock_agent import parsing

    assert parsing.extract_grade_scale("MG 1/100 Freedom Gundam Ver.2.0") == "MG 1/100"
    assert parsing.extract_grade_scale("RG 1/144 Nu Gundam") == "RG 1/144"


def test_lowstock_deal_check_public_api_is_unchanged():
    from scripts.lowstock_agent.checks import deal

    assert callable(deal.analyze_deal)
    assert callable(deal.parse_stock_count)


def test_lowstock_package_modules_all_import():
    """Import-level regression: a broken shared dependency shows up here first."""
    for name in (
        "scripts.lowstock_agent",
        "scripts.lowstock_agent.parsing",
        "scripts.lowstock_agent.config",
        "scripts.lowstock_agent.checks",
        "scripts.lowstock_agent.checks.deal",
        "scripts.lowstock_agent.checks.dedup",
    ):
        assert importlib.import_module(name) is not None
