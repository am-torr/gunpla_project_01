"""Generate the recorded fixture source set used by the offline pipeline run.

Run it to regenerate `manifest.json`, `listings.json` and every `*.html` /
`*.json` page in this directory:

    python scripts/gunpla_official_news/fixtures/build_fixtures.py

The set deliberately covers ALL FIVE source tiers and ALL FOUR confidence labels
in a single end-to-end run, plus the three image edge cases (site chrome, 404,
non-image content-type) and both Reddit branches (corroborated / blocked).

Every write passes encoding="utf-8"; this box's locale default is cp1252 and the
Japanese yen sign in the fixture bodies would not survive it.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

YEN = "\u00a5"  # U+00A5 YEN SIGN, escaped so this file stays ASCII

PAGES: dict = {}
MANIFEST: dict = {}


def html_page(
    *,
    title: str,
    date: str,
    metas: dict,
    body: str,
    images: list,
    footer_notice: bool,
) -> str:
    meta_lines = ['<meta name="datePublished" content="%s">' % date]
    for k, v in metas.items():
        meta_lines.append('<meta name="%s" content="%s">' % (k, v))
    img_lines = ['<img src="%s" alt="">' % u for u in images]
    footer = (
        "<footer><p>*Note: Reproduction of content and images is strictly "
        "prohibited.</p></footer>"
        if footer_notice
        else "<footer><p>(c) Example</p></footer>"
    )
    return (
        "<!doctype html>\n<html lang=\"en\"><head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>%s</title>\n%s\n</head>\n<body>\n<article>\n<p>%s</p>\n%s\n"
        "</article>\n%s\n</body></html>\n"
        % (title, "\n".join(meta_lines), body, "\n".join(img_lines), footer)
    )


def listing_page(title: str, links: list) -> str:
    items = "\n".join('<li><a href="%s">%s</a></li>' % (u, u) for u in links)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>%s</title></head>\n<body><ul>\n%s\n</ul></body></html>\n" % (title, items)
    )


def add(url: str, filename: str, content: str, content_type: str = "text/html; charset=utf-8"):
    PAGES[filename] = content
    MANIFEST[url] = {"file": filename, "content_type": content_type}


def add_status(url: str, status: int, content_type: str = "text/html; charset=utf-8"):
    MANIFEST[url] = {"status": status, "content_type": content_type}


def add_image(url: str, content_type: str = "image/jpeg", status: int = 200):
    MANIFEST[url] = {"status": status, "content_type": content_type}


# ---------------------------------------------------------------------------
# Article URLs
# ---------------------------------------------------------------------------
A = "https://en.gundam-official.com/news/1001"          # official kit    -> High
B = "https://en.gundam-official.com/news/1002"          # official event  -> High (reddit blocked)
C = "https://global.bandai-hobby.net/en-us/site/gbase_worldtour/event-2026-osaka"
D = "https://www.hlj.com/1-100-mg-freedom-gundam-ver-2-0-bans64213"   # retail  -> High
E = "https://www.hlj.com/1-144-rg-nu-gundam-bans65118"                # reveal  -> Medium
F = "https://gundamkitscollection.com/2026/09/mg-sazabi-ver-ka-2-0.html"  # -> Low
G = "https://www.reddit.com/r/Gunpla/comments/abc123/pg_unicorn_2_leak/"  # -> RUMOR
H = "https://www.reddit.com/r/Gunpla/comments/def456/gbase_shanghai_official_post/"  # -> Medium

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
IMG_OK_1 = "https://en.gundam-official.com/media/mgex-strike-freedom-01.jpg"
IMG_OK_2 = "https://en.gundam-official.com/media/mgex-strike-freedom-02.jpg"
IMG_OK_3 = "https://en.gundam-official.com/media/mgex-strike-freedom-03.png"
IMG_OK_4 = "https://en.gundam-official.com/media/mgex-strike-freedom-04.webp"
IMG_CHROME = "https://en.gundam-official.com/media/resized_Rectangle_1180.png"
IMG_404 = "https://en.gundam-official.com/media/missing-hero.jpg"
IMG_NOT_IMAGE = "https://en.gundam-official.com/media/gallery-index.html"
IMG_EVENT = "https://en.gundam-official.com/media/next-future-tour-key.jpg"
IMG_GBASE = "https://global.bandai-hobby.net/media/gbase-osaka-hall.jpg"
IMG_HLJ_D = "https://www.hlj.com/media/bans64213-box.jpg"
IMG_HLJ_E = "https://www.hlj.com/media/bans65118-box.jpg"

add_image(IMG_OK_1, "image/jpeg")
add_image(IMG_OK_2, "image/jpeg")
add_image(IMG_OK_3, "image/png")
add_image(IMG_OK_4, "image/webp")
add_image(IMG_CHROME, "image/png")            # served fine; excluded by NAME, before any HEAD
add_image(IMG_404, "image/jpeg", status=404)  # 404 -> not verified
add_image(IMG_NOT_IMAGE, "text/html; charset=utf-8")  # 200 but not image/* -> not verified
add_image(IMG_EVENT, "image/jpeg")
add_image(IMG_GBASE, "image/jpeg")
add_image(IMG_HLJ_D, "image/jpeg")
add_image(IMG_HLJ_E, "image/jpeg")

# ---------------------------------------------------------------------------
# Reddit endpoints
# ---------------------------------------------------------------------------
REDDIT_A = "https://www.reddit.com/r/Gunpla/search.json?q=mgex+strike+freedom"
REDDIT_B = "https://www.reddit.com/r/Gunpla/search.json?q=gundam+next+future"
REDDIT_H = "https://www.reddit.com/r/Gunpla/search.json?q=gbase+shanghai"

add(
    REDDIT_A,
    "reddit_mgex_strike_freedom.json",
    json.dumps(
        [
            {"id": "p1", "title": "MGEX Strike Freedom confirmed", "cites_official": False},
            {"id": "p2", "title": "Saw the same listing on the official page", "cites_official": False},
            {"id": "p3", "title": "Price matches the announcement", "cites_official": False},
            {"id": "p4", "title": "unrelated build pic", "off_topic": True},
        ],
        indent=2,
    )
    + "\n",
    content_type="application/json",
)
# Reddit blocked from this environment -> must degrade, not raise.
add_status(REDDIT_B, 403, content_type="application/json")
add(
    REDDIT_H,
    "reddit_gbase_shanghai.json",
    json.dumps(
        [{"id": "q1", "title": "Official G-Base post", "cites_official": True}],
        indent=2,
    )
    + "\n",
    content_type="application/json",
)

# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
add(
    A,
    "article_1001_mgex_strike_freedom.html",
    html_page(
        title="MGEX 1/100 Strike Freedom Gundam announced",
        date="2026-09-04",
        metas={
            "seriesTags": "SEED, SEED DESTINY",
            "categories": "Gunpla, Kit",
            "description": "Bandai Spirits announces the MGEX Strike Freedom Gundam.",
            "kit_item": "MGEX 1/100 Strike Freedom Gundam",
            "series": "SEED",
            "context_hook": "First MGEX since the Unicorn Ver.Ka -- the line is alive again.",
            "ug_take": "The internal LED frame is the whole reason this grade exists.",
            "engagement_question": "Is an MGEX worth triple an MG to you?",
            "source_name": "GUNDAM Official",
            "reddit_url": REDDIT_A,
        },
        body=(
            "Bandai Spirits has announced the MGEX 1/100 Strike Freedom Gundam. "
            "Release: November 2026. Price " + YEN + "27,500 including tax. "
            "General retail release through hobby shops nationwide."
        ),
        images=[IMG_CHROME, IMG_OK_1, IMG_OK_2, IMG_404, IMG_NOT_IMAGE, IMG_OK_3, IMG_OK_4],
        footer_notice=True,
    ),
)

add(
    B,
    "article_1002_next_future_tour.html",
    html_page(
        title="GUNDAM NEXT FUTURE Tour 2026 dates announced",
        date="2026-09-02",
        metas={
            "seriesTags": "ALL",
            "categories": "Event",
            "description": "The touring GUNDAM NEXT FUTURE event returns for 2026.",
            "kit_item": "GUNDAM NEXT FUTURE Tour 2026",
            "series": "ALL",
            "grade_type": "Event",
            "context_hook": "Event-limited kits usually surface here first.",
            "ug_take": "Go for the event-exclusive clear parts, stay for the dioramas.",
            "engagement_question": "Which venue are you hitting?",
            "source_name": "GUNDAM Official",
            "reddit_url": REDDIT_B,
        },
        body=(
            "The GUNDAM NEXT FUTURE tour returns. Release: October 2026 for the "
            "first venue. Event exclusive merchandise will be sold on site."
        ),
        images=[IMG_EVENT, IMG_CHROME],
        footer_notice=True,
    ),
)

add(
    C,
    "article_gbase_osaka.html",
    html_page(
        title="GUNDAM BASE World Tour 2026 -- Osaka",
        date="2026-08-30",
        metas={
            "seriesTags": "ALL",
            "categories": "Event",
            "description": "Bandai Hobby brings the Gundam Base World Tour to Osaka.",
            "kit_item": "GUNDAM BASE World Tour 2026 (Osaka)",
            "series": "ALL",
            "grade_type": "Event",
            "context_hook": "Tour stops carry venue-limited colour variants.",
            "ug_take": "The limited clear HG is the only reason to queue.",
            "engagement_question": "Worth the queue or not?",
            "source_name": "Bandai Hobby Site",
        },
        body=(
            "The Gundam Base World Tour arrives in Osaka. Release: September 2026. "
            "Event exclusive kits available at the venue only."
        ),
        images=[IMG_GBASE],
        footer_notice=False,
    ),
)

add(
    D,
    "article_hlj_mg_freedom.html",
    html_page(
        title="MG 1/100 Freedom Gundam Ver. 2.0 -- in stock",
        date="2026-09-03",
        metas={
            "categories": "Kit",
            "description": "In stock and shipping now from HLJ.",
            "kit_item": "MG 1/100 Freedom Gundam Ver. 2.0",
            "series": "SEED",
            "grade_type": "Kit",
            "release": "2026-09",
            "msrp": "4,400 yen",
            "exclusivity": "Retail",
            "context_hook": "Back in stock after a nine-month gap.",
            "ug_take": "Ver 2.0 is still the best-engineered Freedom.",
            "engagement_question": "Ver 2.0 or the RG?",
            "source_name": "HobbyLink Japan",
        },
        body="MG 1/100 Freedom Gundam Ver. 2.0. Release: September 2026. 4,400 yen. In stock.",
        images=[IMG_HLJ_D],
        footer_notice=False,
    ),
)

add(
    E,
    "article_hlj_rg_nu.html",
    html_page(
        title="RG 1/144 Nu Gundam -- new listing",
        date="2026-09-01",
        metas={
            "categories": "Kit",
            "description": "A brand-new listing appeared before any official reveal.",
            "kit_item": "RG 1/144 Nu Gundam",
            "series": "CCA",
            "grade_type": "Kit",
            "release": "2026-12",
            "msrp": "4,950 yen",
            "exclusivity": "Retail",
            "is_first_reveal": "true",
            "context_hook": "Retail listing precedes the official announcement.",
            "ug_take": "A retail listing is a strong lead, not a confirmation.",
            "engagement_question": "Do you preorder off a retail listing alone?",
            "source_name": "HobbyLink Japan",
        },
        body="RG 1/144 Nu Gundam. Release: December 2026. 4,950 yen. Preorder listing.",
        images=[IMG_HLJ_E],
        footer_notice=False,
    ),
)

add(
    F,
    "article_gkc_sazabi.html",
    html_page(
        title="MG Sazabi Ver.Ka 2.0 rumoured for 2027",
        date="2026-08-28",
        metas={
            "categories": "Kit",
            "description": "Aggregator post with no official link.",
            "kit_item": "MG Sazabi Ver.Ka 2.0 (unconfirmed)",
            "series": "CCA",
            "grade_type": "Kit",
            "context_hook": "Aggregator claim with no primary source attached.",
            "ug_take": "No official page, no MSRP, no date -- treat as a lead only.",
            "engagement_question": "Would you believe a Sazabi 2.0 without an official page?",
            "source_name": "Gundam Kits Collection",
        },
        body="Rumour suggests an MG Sazabi Ver.Ka 2.0. No official confirmation exists.",
        images=[],
        footer_notice=False,
    ),
)

add(
    G,
    "article_reddit_pg_unicorn_leak.html",
    html_page(
        title="PG Unicorn 2.0 leak (single post)",
        date="2026-08-25",
        metas={
            "categories": "Kit",
            "description": "One Reddit post, no corroboration, no official link.",
            "kit_item": "PG Unicorn Gundam 2.0 (leak)",
            "series": "UNICORN",
            "grade_type": "Kit",
            "context_hook": "Single unverified community post.",
            "ug_take": "One post is not a source.",
            "engagement_question": "How many posts before you believe a leak?",
            "source_name": "Reddit r/Gunpla",
        },
        body="A single user claims a PG Unicorn 2.0 is coming. No link, no photos.",
        images=[],
        footer_notice=False,
    ),
)

add(
    H,
    "article_reddit_gbase_shanghai.html",
    html_page(
        title="G-Base Shanghai opening date (official post linked)",
        date="2026-08-27",
        metas={
            "categories": "Event",
            "description": "Community post that links the official regional announcement.",
            "kit_item": "THE GUNDAM BASE Shanghai opening",
            "series": "ALL",
            "grade_type": "Event",
            "cites_official": "true",
            "context_hook": "Regional opening, corroborated by a linked official page.",
            "ug_take": "Community post, official link -- credible, still not first-party.",
            "engagement_question": "Which Gundam Base would you fly for?",
            "source_name": "Reddit r/Gunpla",
            "reddit_url": REDDIT_H,
        },
        body=(
            "Poster links the official regional announcement for the Shanghai "
            "Gundam Base. Release: November 2026 for the opening."
        ),
        images=[],
        footer_notice=False,
    ),
)

# ---------------------------------------------------------------------------
# Listing pages (Level 2 entry points)
# ---------------------------------------------------------------------------
LISTINGS = [
    "https://en.gundam-official.com/news/",
    "https://global.bandai-hobby.net/en-us/site/gbase_worldtour/",
    "https://www.hlj.com/search/?Word=gundam&Sort=Newest",
    "https://gundamkitscollection.com/",
    "https://www.reddit.com/r/Gunpla/new/",
]

add(LISTINGS[0], "news_index.html", listing_page("GUNDAM Official news", [A, B]))
add(LISTINGS[1], "gbase_index.html", listing_page("Gundam Base World Tour", [C]))
add(LISTINGS[2], "hlj_index.html", listing_page("HLJ newest", [D, E]))
add(LISTINGS[3], "gkc_index.html", listing_page("Gundam Kits Collection", [F]))
add(LISTINGS[4], "reddit_index.html", listing_page("r/Gunpla new", [G, H]))


def main() -> int:
    for name, content in PAGES.items():
        with open(HERE / name, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    with open(HERE / "manifest.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(MANIFEST, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(HERE / "listings.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(LISTINGS, fh, indent=2)
        fh.write("\n")
    print("wrote %d pages + manifest (%d URLs)" % (len(PAGES), len(MANIFEST)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
