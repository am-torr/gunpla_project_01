"""AC4 -- the whole pipeline against the recorded fixture HTTP source set.

Nothing here is hand-written output: every assertion reads files produced by
``pipeline.run_fixtures()``, which walks listing pages, fetches articles, applies
the verification rules and issues HTTP HEADs through the fixture transport's
``opener`` seam -- the same code path a live run uses.
"""
from __future__ import annotations

import json

import pytest

from gunpla_official_news.brief import EM_DASH
from gunpla_official_news.http_client import FixtureTransport
from gunpla_official_news.models import WORKING_DATA_COLUMNS, WORKING_DATA_JSON_KEYS
from gunpla_official_news import pipeline as P
from gunpla_official_news import working_data as W
from gunpla_official_news.verification import CONFIDENCE_RANK, SOURCE_TIERS

DATE = "2026-09-06"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("output")
    report = P.run_fixtures(output_dir=out, date=DATE)
    return out, report


@pytest.fixture(scope="module")
def artifacts(run_dir):
    out, report = run_dir
    with open(out / ("working_data_%s.md" % DATE), "r", encoding="utf-8") as fh:
        md = fh.read()
    with open(out / ("working_data_%s.json" % DATE), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    with open(out / ("verified_brief_%s.md" % DATE), "r", encoding="utf-8") as fh:
        brief = fh.read()
    return md, data, brief, report


# ---------------------------------------------------------------------------
# The three files
# ---------------------------------------------------------------------------


def test_produces_all_three_named_outputs(run_dir):
    out, _ = run_dir
    for name in (
        "verified_brief_%s.md" % DATE,
        "working_data_%s.md" % DATE,
        "working_data_%s.json" % DATE,
    ):
        path = out / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_working_data_md_has_the_documented_columns(artifacts):
    md, _, _, _ = artifacts
    header = md.splitlines()[0]
    assert header == "| " + " | ".join(WORKING_DATA_COLUMNS) + " |"
    for line in md.splitlines()[2:]:
        if not line.strip():
            continue
        assert len(line.strip().strip("|").split("|")) == len(WORKING_DATA_COLUMNS)


def test_working_data_json_matches_the_markdown_table(artifacts):
    md, data, _, _ = artifacts
    assert data == W.parse_markdown_table(md)
    assert all(tuple(rec.keys()) == WORKING_DATA_JSON_KEYS for rec in data)


def test_rows_are_sorted_by_confidence_then_date(artifacts):
    md, data, _, report = artifacts
    rows = W.rows_from_markdown(md)
    # date_published is metadata, so re-derive the key from the run's own report.
    ranks = [CONFIDENCE_RANK[r.confidence] for r in rows]
    assert ranks == sorted(ranks, reverse=True)

    # Within the top band, dates must descend. date_published is metadata and so
    # is absent from the exported files -- rebuild the rows to check it.
    transport = FixtureTransport.from_dir(P.FIXTURE_DIR)
    with open(P.FIXTURE_DIR / "listings.json", "r", encoding="utf-8") as fh:
        listings = json.load(fh)
    articles = P.gather_articles(transport, listings)
    built = W.sort_rows([P.build_row(transport, a) for a in articles])
    high_dates = [r.date_published for r in built if r.confidence == "High"]
    assert high_dates == sorted(high_dates, reverse=True)
    assert len(high_dates) >= 2


# ---------------------------------------------------------------------------
# The rules actually fired end to end
# ---------------------------------------------------------------------------


def test_the_run_exercises_every_tier_and_every_label(artifacts):
    _, data, _, _ = artifacts
    assert {r["source_tier"] for r in data} == set(SOURCE_TIERS)
    assert {r["confidence"] for r in data} == {"High", "Medium", "Low", "RUMOR"}


def test_image_checked_is_true_only_where_a_head_succeeded(artifacts):
    _, data, _, report = artifacts
    checked = [r for r in data if r["image_checked"]]
    assert checked, "the fixture set must verify at least one image"
    for rec in checked:
        assert rec["ImageURL1"], "image_checked without a verified URL"
    for rec in data:
        if not rec["image_checked"]:
            assert rec["ImageURL1"] == ""
    assert report.images_verified > 0
    assert report.images_failed > 0, "the 404 / non-image fixtures must have failed"


def test_site_chrome_never_reaches_the_output(artifacts):
    md, data, brief, report = artifacts
    assert report.images_excluded_chrome > 0
    for blob in (md, brief, json.dumps(data)):
        assert "resized_Rectangle_" not in blob


def test_blocked_reddit_degraded_instead_of_failing_the_run(artifacts):
    _, data, _, report = artifacts
    assert report.reddit_unavailable == 1
    degraded = [r for r in data if r["community_consensus"].startswith("unavailable")]
    assert len(degraded) == 1
    # The item still made it into the output with a real confidence label.
    assert degraded[0]["confidence"] in ("High", "Medium", "Low", "RUMOR")


def test_reddit_corroboration_reached_three_posts(artifacts):
    _, data, _, _ = artifacts
    corroborated = [r for r in data if "corroborated: 3" in r["community_consensus"]]
    assert len(corroborated) == 1


# ---------------------------------------------------------------------------
# The brief
# ---------------------------------------------------------------------------


def test_brief_has_the_documented_sections_and_title(artifacts):
    _, _, brief, _ = artifacts
    assert brief.splitlines()[0] == "# Gunpla News Brief %s %s" % (EM_DASH, DATE)
    for section in ("## Verified Brief", "## Viability Check", "## Image Assets", "## Sources"):
        assert section in brief


def test_rumor_items_are_kept_out_of_the_brief_body(artifacts):
    _, data, brief, _ = artifacts
    rumors = [r for r in data if r["confidence"] == "RUMOR"]
    assert rumors
    body = brief.split("## Viability Check")[0]
    for rec in rumors:
        assert rec["kit_item"] not in body
    # ...but they stay auditable in the Viability Check table.
    viability = brief.split("## Viability Check")[1]
    for rec in rumors:
        assert rec["kit_item"] in viability


def test_reuse_flag_surfaces_in_the_image_assets_section(artifacts):
    _, _, brief, _ = artifacts
    assets = brief.split("## Image Assets")[1].split("## Sources")[0]
    assert "reuse_not_permitted" in assets


# ---------------------------------------------------------------------------
# Level 1 routing
# ---------------------------------------------------------------------------


def test_topic_filter_produces_a_focused_brief(tmp_path):
    report = P.run_fixtures(output_dir=tmp_path, date=DATE, topic="strike freedom")
    with open(report.outputs["verified_brief"], "r", encoding="utf-8") as fh:
        brief = fh.read()
    assert "## Focused Brief" in brief
    assert "## Verified Brief" not in brief
    assert report.rows == 1


def test_include_rumors_puts_them_back_in(tmp_path):
    report = P.run_fixtures(output_dir=tmp_path, date=DATE, include_rumors=True)
    with open(report.outputs["verified_brief"], "r", encoding="utf-8") as fh:
        body = fh.read().split("## Viability Check")[0]
    assert "PG Unicorn Gundam 2.0 (leak)" in body


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def test_fixture_transport_serves_and_404s():
    t = FixtureTransport.from_dir(P.FIXTURE_DIR)
    ok = t.get("https://en.gundam-official.com/news/")
    assert ok.ok and "<a href" in ok.text
    missing = t.get("https://en.gundam-official.com/news/does-not-exist")
    assert missing.status == 404
    assert missing.ok is False


def test_no_web_search_or_firecrawl_anywhere_in_the_package():
    """ARCHITECTURE.md section 7 forbids both; direct HTTP only.

    Checked over the AST, not the raw text: the module docstrings legitimately
    NAME the forbidden tools in order to forbid them, and a substring scan would
    flag exactly the comments that document the rule.
    """
    import ast
    import pathlib

    banned = {"web_search", "firecrawl", "web_fetch"}
    pkg = pathlib.Path(P.__file__).resolve().parent
    for path in pkg.rglob("*.py"):
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0].lower() not in banned, path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0].lower() not in banned, path
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert name.lower() not in banned, (path, name)
