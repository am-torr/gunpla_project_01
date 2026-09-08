# Gunpla Verified News — Claude Code Implementation Brief

## Goal
Replicate the Hermes “What’s the latest Gunpla news?” workflow as a standalone pipeline under `D:\PROJECT\Gunpla-tracker-verified\`.

---

## 1. Architecture (3 levels)

### Level 1 — Trigger / Router
- Input: user prompt `What’s the latest Gunpla news? [optional topic]`
- Router rules:
  - If topic contains `life-size`, `odaiba`, `unicorn gundam statue` → **focused brief mode**
  - Else → **full brief mode** (latest N articles)
- Skills to load first:
  - `gunpla-news-gatherer`
  - `gunpla-source-guide`
  - `gunpla-verification`

### Level 2 — Source Gathering (direct HTTP only)
**Mandatory:** Do NOT use web_search. All fetching is direct HTTP with a browser User-Agent header.

Primary sources (in order):
1. `https://en.gundam-official.com/news/` — latest article IDs from homepage JSON/HTML
2. `https://en.gundam-official.com/news/<id>` — individual article pages
3. `https://global.bandai-hobby.net/en-us/site/gbase_worldtour/` — event pages

Extract from each article:
- `title`
- `datePublished`
- `seriesTags[]`
- `categories[]`
- `summary/description`
- `body content` (for images and detailed kit info)

Output: raw candidate list of dicts.

### Level 3 — Verification + Working Data + Export
Apply `gunpla-verification` rules to each candidate:
- `official` + live page verified = **High**
- `primary_retail` with confirmed date/price = **High** for availability, **Medium** for first reveals
- `competitor_uncited` without official link = **RUMOR / exclude from Verified Brief**
- Single Reddit post = **RUMOR** unless 3+ sources or official link cited

Build **Working Data table** (18 columns, exact order):
```
kit_item | series | grade_type | release | msrp | exclusivity | source_tier | confidence | source_url | context_hook | image_checked | ImageURL1 | ImageURL2 | ImageURL3 | UG's take | community_consensus | engagement_question
```

Export outputs:
1. `verified_brief_YYYY-MM-DD.md` — human-readable brief with source links
2. `working_data_YYYY-MM-DD.md` — markdown table
3. `working_data_YYYY-MM-DD.json` — JSON array (use provided `export_json.py` logic)

---

## 2. Skills Location

```
C:\Users\amtor\AppData\Local\hermes\skills\
├── productivity/
│   ├── gunpla-news-gatherer/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── export_json.py
│   ├── gunpla-source-guide/
│   │   └── SKILL.md
│   └── gunpla-verification/
│       └── SKILL.md
```

Read these 3 SKILL.md files first. They contain the full rules.

---

## 3. Non-Negotiable Details

### Source tiers (from gunpla-source-guide)
| Tier | Examples | Use for |
|---|---|---|
| `official` | en.gundam-official.com, global.bandai-hobby.net, Bandai Namco Filmworks | Any factual claim |
| `primary_retail` | HLJ, Gundam Planet, Toy-People, Essential Japan | Availability, dates, prices |
| `credible_community_official` | Reddit/GKC with direct official link, official regional pages | Cross-checking, local events |
| `competitor_uncited` | Gundam Kits Collection, Gundam News without official link | Leads only — never copy claims without independent verification |
| `community` | Reddit without official link, YouTube, forums | Leads only — treat as rumor unless corroborated |

### Confidence labels (from gunpla-verification)
| Label | Meaning |
|---|---|
| `High` | Official or primary retail confirms it; I checked the page myself |
| `Medium` | Primary retail confirms availability but not first reveal; credible community corroboration |
| `Low` | Competitor/community source without independent official confirmation |
| `RUMOR` | Single-source Reddit, YouTube-only, or unconfirmed leak |

### Mandatory checks before marking High
- [ ] Did I open the official or primary retail page myself?
- [ ] If the only source is a competitor, did I find the same fact on official/primary retail?
- [ ] If either is no → downgrade to Medium/Low/RUMOR

### Never output in Verified Brief
- Dates from YouTube video chapters alone
- "Expected Q4 2026" without official Bandai/Gundam-Official mention
- Prices from eBay/Amazon resale — only official MSRP
- Reddit single-source claims as fact
- Competitor-only claims as fact
- RUMOR items unless user explicitly requests them

### Reddit community consensus rules
- 1 Reddit post alone is NOT enough
- Require ≥3 separate posts/comments corroborating same fact, OR comment must directly cite official Bandai/Gundam-Official source
- High-credibility Reddit poster/mod role does NOT replace 3-source rule unless linking primary material
- If Reddit is inaccessible from the environment → log as `community_consensus: "unavailable — Reddit blocked"` and continue without it

### Image handling
- Extract all `https://gundam-official.com/media/...` URLs from article body
- Verify each with HTTP HEAD — must return `200` + `image/*`
- Flag `image_checked: true` only after HEAD verification
- Safe-use assessment: official source footer says `*Note: Reproduction of content and images is strictly prohibited.` → flag as `reuse_not_permitted` in metadata
- Do NOT include site chrome/footer images (`resized_Rectangle_*`)

### Two-axis labeling
Every Working Data entry must have:
- `source_tier`: `official`, `primary_retail`, `credible_community_official`, `competitor_uncited`, `community`
- `confidence`: `High`, `Medium`, `Low`, `RUMOR`

---

## 4. Working Data Schema (exact)

```json
{
  "kit_item": "string — kit/item name or event title",
  "series": "string — e.g. UNICORN, SEED, ALL series",
  "grade_type": "string — Kit, Event, Figure, Media, Goods, Apparel",
  "release": "string — date or date range",
  "msrp": "string — yen price or TBA or -",
  "exclusivity": "string — Premium / Retail / Event / -",
  "source_tier": "string — official | primary_retail | credible_community_official | competitor_uncited | community",
  "confidence": "string — High | Medium | Low | RUMOR",
  "source_url": "string — official article URL",
  "context_hook": "string — 1-line why this matters",
  "image_checked": "boolean — true only after HEAD verification",
  "ImageURL1": "string — primary image URL or -",
  "ImageURL2": "string — secondary image URL or -",
  "ImageURL3": "string — tertiary image URL or -",
  "UG_take": "string — 1-line editorial take",
  "community_consensus": "string — Reddit/community sentiment or unavailable",
  "engagement_question": "string — question to drive comments"
}
```

---

## 5. Export Rules

### Markdown brief (`verified_brief_YYYY-MM-DD.md`)
- Title: `# Gunpla News Brief — YYYY-MM-DD`
- Sections:
  - `## Focused Brief` (if topic filter active) or `## Verified Brief`
  - `## Viability Check` — confidence table
  - `## Image Assets` — verified URLs with reuse flag
  - `## Sources` — all source URLs

### Working Data table (`working_data_YYYY-MM-DD.md`)
- Exact 18-column markdown table
- Sort by `confidence` desc, then `datePublished` desc

### JSON (`working_data_YYYY-MM-DD.json`)
- Compact array of objects matching schema above
- Generated by parsing the markdown table (see `export_json.py` logic)

---

## 6. Image Verification Script Pattern

```python
import urllib.request

def verify_image(url):
    req = urllib.request.Request(url, method='HEAD')
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200 and r.headers.get('Content-Type','').startswith('image')

# Usage:
# for url in extracted_urls:
#     safe = verify_image(url)
#     mark image_checked=true only if safe
```

---

## 7. Anti-Patterns (explicitly forbidden)

- ❌ Using `web_search` / Firecrawl — environment has no credits
- ❌ Trusting competitor-only claims without official/primary verification
- ❌ Single-source Reddit claims as fact
- ❌ Including `resized_Rectangle_*` footer images as article assets
- ❌ Marking images `image_checked=true` without HTTP HEAD verification
- ❌ Outputting RUMOR items in Verified Brief unless explicitly requested
- ❌ Using site footer note `Reproduction of content and images is strictly prohibited.` as permission to reuse

---

## 8. Project Structure Target

```
D:\PROJECT\Gunpla-tracker-verified\
├── README.md
├── ARCHITECTURE.md          ← this file
├── src/
│   ├── fetch_news.py        ← Level 2: direct HTTP fetcher
│   ├── verify.py            ← Level 3: gunpla-verification rules
│   ├── build_working_data.py← Level 3: schema + table builder
│   ├── export_json.py       ← Level 3: MD table → JSON
│   └── verify_images.py     ← Level 3: HEAD check + safe-use flag
├── skills/                  ← copy of 3 SKILL.md files
│   ├── gunpla-news-gatherer/
│   ├── gunpla-source-guide/
│   └── gunpla-verification/
├── output/
│   ├── verified_brief_YYYY-MM-DD.md
│   ├── working_data_YYYY-MM-DD.md
│   └── working_data_YYYY-MM-DD.json
└── tests/
    └── test_verify.py
```

---

## 9. First Implementation Steps for Claude Code

1. Copy the 3 SKILL.md files into `skills/`
2. Build `fetch_news.py`:
   - `fetch_latest_ids()` → scrape `en.gundam-official.com/news/` for IDs
   - `fetch_article(id)` → extract title, date, series, categories, body
3. Build `verify.py`:
   - Apply confidence rules from `gunpla-verification`
   - Apply source-tier rules from `gunpla-source-guide`
4. Build `build_working_data.py`:
   - Map verified articles to 18-column schema
   - Output markdown table
5. Build `export_json.py`:
   - Parse markdown table → JSON array
6. Build `verify_images.py`:
   - Extract `gundam-official.com/media/` URLs
   - HEAD verify each
   - Flag `reuse_not_permitted`
7. Wire into main `brief.md` generator
8. Test with topic `life-size gundam odaiba`

---

## 10. Key Principle

**Official-source confirmation is for factual accuracy, NOT for redistribution rights.**
Always check the site footer/reuse policy before allowing images to be republished.
Flag explicitly: `reuse_not_permitted` until explicit permission is obtained.
