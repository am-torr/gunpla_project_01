"""End-to-end pipeline: sources -> verification -> images -> output/ (AC4).

Levels 1-3 of ARCHITECTURE.md wired together:

    Level 1  route (topic filter -> Focused Brief, else Verified Brief)
    Level 2  direct-HTTP gather (a Transport; no web_search, no Firecrawl)
    Level 3  verify (two-axis labels + Reddit rule) -> image HEAD checks ->
             Working Data -> three files under ``output/``

Produces, for ``--date YYYY-MM-DD``:

    output/verified_brief_<date>.md
    output/working_data_<date>.md    (documented column table, sorted)
    output/working_data_<date>.json  (parsed back OUT of the .md, per section 5)

Run against the bundled fixture source set::

    python -m gunpla_official_news.pipeline --fixtures --date 2026-09-06

Run live (direct HTTP)::

    python -m gunpla_official_news.pipeline --live --date 2026-09-06
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urljoin

from .article_parser import Article, extract_article_links, parse_article
from .http_client import FixtureTransport, UrllibTransport
from .images import extract_image_urls, verify_images
from .models import WorkingDataRow, new_working_row
from .working_data import export_json_from_markdown, sort_rows, write_markdown
from .brief import write_brief
from .verification import (
    COMMUNITY_CONSENSUS_UNAVAILABLE,
    MandatoryChecks,
    TIER_COMPETITOR_UNCITED,
    assess_confidence,
    classify_source_tier,
    reddit_consensus,
)

log = logging.getLogger("gunpla_official_news.pipeline")

#: Where the bundled fixture source set lives.
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

#: Listing pages walked in Level 2, in ARCHITECTURE.md's documented order.
DEFAULT_LISTING_URLS = (
    "https://en.gundam-official.com/news/",
    "https://global.bandai-hobby.net/en-us/site/gbase_worldtour/",
)


@dataclass
class RunReport:
    """What a run did -- enough to audit the output files without re-running."""

    date: str = ""
    topic: Optional[str] = None
    listings: list = field(default_factory=list)
    articles: int = 0
    rows: int = 0
    images_verified: int = 0
    images_excluded_chrome: int = 0
    images_failed: int = 0
    reddit_unavailable: int = 0
    outputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["outputs"] = {k: str(v) for k, v in self.outputs.items()}
        return d


# ---------------------------------------------------------------------------
# Level 2: gather
# ---------------------------------------------------------------------------


def gather_articles(transport, listing_urls: Sequence[str]) -> list:
    """Fetch each listing page, then every article it links, via direct HTTP."""
    articles: list = []
    seen: set = set()
    for listing in listing_urls:
        resp = transport.get(listing)
        if not resp.ok:
            log.warning("listing %s -> status=%s %s", listing, resp.status, resp.error)
            continue
        for href in extract_article_links(resp.text, fallback_prefix=listing):
            if href in seen or href == listing:
                continue
            seen.add(href)
            page = transport.get(href)
            if not page.ok:
                log.warning("article %s -> status=%s", href, page.status)
                continue
            articles.append(parse_article(page.text, url=href))
    return articles


# ---------------------------------------------------------------------------
# Level 3: verify + build
# ---------------------------------------------------------------------------


def _community_consensus(transport, article: Article) -> tuple:
    """Run the Reddit rule for one article. Returns (text, corroborated, count, cites)."""
    reddit_url = article.meta("reddit_url")
    if not reddit_url:
        result = reddit_consensus([], reachable=True, summary="not checked")
        return result.community_consensus, result.corroborated, 0, False

    resp = transport.get(reddit_url)
    if not resp.ok:
        # Blocked / 403 / dead: DEGRADE, never raise (ARCHITECTURE.md section 3).
        log.info("reddit unreachable (%s) for %s", resp.status, article.url)
        result = reddit_consensus(None, reachable=False)
        return result.community_consensus, False, 0, False

    try:
        posts = json.loads(resp.text)
        if isinstance(posts, dict):
            posts = posts.get("posts", [])
    except json.JSONDecodeError:
        posts = []
    result = reddit_consensus(posts, reachable=True)
    return (
        result.community_consensus,
        result.corroborated,
        result.corroborating_posts,
        result.cites_official,
    )


def build_row(transport, article: Article, report: Optional[RunReport] = None) -> WorkingDataRow:
    """Apply the two-axis rules + image verification to one article."""
    cites_official = article.meta_flag("cites_official")
    tier = classify_source_tier(article.url, cites_official=cites_official)

    consensus_text, corroborated, n_posts, consensus_cites = _community_consensus(
        transport, article
    )
    if report is not None and consensus_text.startswith("unavailable"):
        report.reddit_unavailable += 1

    checks = MandatoryChecks(
        # The page was actually fetched and parsed in gather_articles(), so the
        # "did I open it myself?" box is genuinely ticked -- not asserted.
        opened_source_page=True,
        competitor_corroborated=(
            True if (cites_official or consensus_cites) else None
        ),
    )
    confidence = assess_confidence(
        tier,
        checks=checks,
        is_first_reveal=article.meta_flag("is_first_reveal"),
        has_confirmed_date_or_price=bool(article.release or article.msrp),
        corroborating_posts=max(n_posts, 0),
        cites_official=cites_official or consensus_cites,
        only_source_is_competitor=(tier == TIER_COMPETITOR_UNCITED),
    )

    candidate_images = extract_image_urls(article.body_html)
    # Next.js flight-payload pages carry no real <img> markup in body_html; their
    # only image (the newsResponse thumbnail) lands in article.image_urls instead
    # (see parse_article's fallback). Fold it in without disturbing the existing
    # body_html-derived candidates or their order. Resolve relative srcs against
    # the article's own URL -- verify_images/head() require an absolute URL.
    for extra in article.image_urls:
        absolute = urljoin(article.url, extra) if article.url else extra
        if absolute.startswith(("http://", "https://")) and absolute not in candidate_images:
            candidate_images.append(absolute)
    verified = verify_images(
        candidate_images,
        page_text=article.body_text,
        opener=getattr(transport, "opener", None),
    )
    if report is not None:
        report.images_verified += len(verified.verified)
        report.images_excluded_chrome += len(verified.excluded_chrome)
        report.images_failed += len(verified.failed)

    img1, img2, img3 = verified.top(3)

    return new_working_row(
        kit_item=article.meta("kit_item") or article.title,
        series=article.meta("series") or ", ".join(article.series_tags),
        grade_type=article.grade_type,
        release=article.release,
        msrp=article.msrp,
        exclusivity=article.exclusivity,
        source_tier=tier,
        confidence=confidence,
        source_url=article.url,
        context_hook=article.meta("context_hook") or article.summary,
        image_checked=verified.image_checked,
        image_url_1=img1,
        image_url_2=img2,
        image_url_3=img3,
        ug_take=article.meta("ug_take"),
        community_consensus=consensus_text,
        engagement_question=article.meta("engagement_question"),
        date_published=article.date_published,
        reuse_not_permitted=verified.reuse_not_permitted,
        source_name=article.meta("source_name"),
        notes=list(verified.flags),
    )


def _dedup_rows(rows: list) -> list:
    """Drop rows whose ``kit_item`` exactly repeats an earlier row.

    Some official listings (e.g. bandai-hobby.net's world-tour microsite) mirror
    the identical announcement across dozens of locale/region URLs -- same
    headline, different ``source_url``. Those are the same news item, not
    distinct ones. Deliberately exact-match only: a city/country-specific title
    (e.g. "... WORLD TOUR BOSTON") is kept as its own row even though the body
    text is boilerplate-similar, since collapsing those would require judging
    semantic sameness rather than just literal duplication.
    """
    out: list = []
    seen: set = set()
    for row in rows:
        key = row.kit_item
        if key and key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _matches_topic(row: WorkingDataRow, topic: str) -> bool:
    blob = " ".join(
        [row.kit_item, row.series, row.context_hook, row.grade_type, row.source_url]
    ).lower()
    return all(word in blob for word in topic.lower().split())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    *,
    transport=None,
    listing_urls: Sequence[str] = DEFAULT_LISTING_URLS,
    output_dir: Path,
    date: Optional[str] = None,
    topic: Optional[str] = None,
    include_rumors: bool = False,
) -> RunReport:
    transport = transport or UrllibTransport()
    date = date or date_cls.today().isoformat()
    output_dir = Path(output_dir)

    report = RunReport(date=date, topic=topic, listings=list(listing_urls))

    articles = gather_articles(transport, listing_urls)
    report.articles = len(articles)

    rows = [build_row(transport, a, report) for a in articles]
    rows = _dedup_rows(rows)
    if topic:
        rows = [r for r in rows if _matches_topic(r, topic)]
    rows = sort_rows(rows)
    report.rows = len(rows)

    md_path = output_dir / ("working_data_%s.md" % date)
    json_path = output_dir / ("working_data_%s.json" % date)
    brief_path = output_dir / ("verified_brief_%s.md" % date)

    write_markdown(rows, md_path, sort=False)
    # Section 5: the JSON is derived by parsing the markdown table, so the two
    # exported files provably cannot drift apart.
    export_json_from_markdown(md_path, json_path)
    write_brief(rows, brief_path, date=date, topic=topic, include_rumors=include_rumors)

    report.outputs = {
        "verified_brief": brief_path,
        "working_data_md": md_path,
        "working_data_json": json_path,
    }
    return report


def run_fixtures(
    *,
    output_dir: Path,
    date: Optional[str] = None,
    topic: Optional[str] = None,
    fixture_dir: Path = FIXTURE_DIR,
    include_rumors: bool = False,
) -> RunReport:
    """Run the whole pipeline against the bundled recorded source set."""
    transport = FixtureTransport.from_dir(fixture_dir)
    with open(Path(fixture_dir) / "listings.json", "r", encoding="utf-8") as fh:
        listings = json.load(fh)
    return run(
        transport=transport,
        listing_urls=listings,
        output_dir=output_dir,
        date=date,
        topic=topic,
        include_rumors=include_rumors,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gunpla verified-news pipeline")
    ap.add_argument("--fixtures", action="store_true", help="use the bundled fixture source set")
    ap.add_argument("--live", action="store_true", help="use direct HTTP against real sources")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD stamped into filenames")
    ap.add_argument("--topic", default=None, help="focused-brief topic filter")
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--include-rumors", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.live and args.fixtures:
        ap.error("--live and --fixtures are mutually exclusive")
    if not args.live and not args.fixtures:
        ap.error("pick one of --fixtures or --live")

    out = Path(args.output_dir)
    if args.fixtures:
        report = run_fixtures(
            output_dir=out,
            date=args.date,
            topic=args.topic,
            include_rumors=args.include_rumors,
        )
    else:
        report = run(
            output_dir=out,
            date=args.date,
            topic=args.topic,
            include_rumors=args.include_rumors,
        )

    json.dump(report.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
