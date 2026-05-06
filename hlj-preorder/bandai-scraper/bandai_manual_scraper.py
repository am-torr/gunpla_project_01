#!/usr/bin/env python3
"""
bandai_manual_scraper.py
=========================
Bandai Manual Scraper – POC for HG 1/144 Alyzeus (manual ID 4954)
Mirrors hlj_lowstock_tracker.py patterns:
  - Playwright + stealth for JS-rendered detail pages
  - BeautifulSoup for HTML parsing
  - Playwright screenshot → base64 → OpenRouter Vision LLM for PDF page 1 OCR
  - Supabase/PostgreSQL upsert via REST API (mirrors your existing stack)
  - dotenv for secrets

Phase roadmap:
  POC   → single kit: HG 1/144 Alyzeus (manual_id=4954)
  Ph2   → all HG kits released in 2026 (categories[]=1, sort=new, stop at 2025)
  Ph3   → descending from 2025 → earlier

Tables used (you already created these):
  bandai_kits     – kit catalog metadata
  mecha_specs     – mobile suit specs from manual page 1
  color_guide     – paint mix ratios from manual page 1

Run:
    python bandai_manual_scraper.py

Outputs:
    bandai_manual_poc.json  – structured result for inspection
"""

import asyncio
import json
import re
import os
import sys
import base64
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
BANDAI_BASE      = "https://manual.bandai-hobby.net"
DETAIL_URL_TPL   = f"{BANDAI_BASE}/menus/detail/{{manual_id}}"
PDF_URL_TPL      = f"{BANDAI_BASE}/pdf/{{manual_id}}.pdf"

# POC: single kit
POC_MANUAL_ID    = 4954

# Phase 2+: list URL (HG brand = categories[]=1, newest first)
LIST_URL_TPL     = (
    f"{BANDAI_BASE}/?sort=new&categories[0]=1&page={{page}}"
)
HG_CATEGORY_ID   = 1   # confirmed from URL: categories[]=1

# Rate limiting – be respectful
SCRAPE_DELAY     = 2   # seconds between requests

PHT = timezone(timedelta(hours=8))
OUTPUT_DIR = Path(__file__).resolve().parent

# ── Secrets ────────────────────────────────────────────────────────────────────
SUPABASE_URL      = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

OPENROUTER_API = os.getenv("OPENROUTER_API")  # for vision LLM OCR

# ── OpenRouter Vision LLM – extracts specs from manual page 1 image ────────────
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL     = "mistralai/pixtral-12b"   # swap to "google/gemini-flash-1.5" if preferred

SPECS_PROMPT = """You are a Gundam model kit data extractor.
This is page 1 of a Bandai HG model kit instruction manual.
Extract ALL mobile suit specifications and color guide data.

Return ONLY valid JSON in this exact structure (no markdown, no extra text):
{
  "model_number": "",
  "name": "",
  "classification": "",
  "head_height": "",
  "weight_empty": "",
  "weight_total": "",
  "generator_output": "",
  "thruster_output": "",
  "material": "",
  "armaments": [],
  "color_guide": [
    {
      "part_name": "",
      "color_name": "",
      "paint_brand": "Mr. Color",
      "mix_ratios": [
        {"color": "", "percentage": 0}
      ]
    }
  ]
}

Rules:
- armaments: each weapon as a separate string in the array
- color_guide: one entry per color swatch block
- If a field is not visible, use null
- Numbers as strings (preserve units: "26.7m", "83.0t", "3,500kW")
"""

# ── Supabase helpers (mirrors your existing pattern) ───────────────────────────
def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",  # upsert behavior
    }

def supabase_upsert(table: str, data: dict) -> bool:
    """Upsert a single record into a Supabase table."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print(f"  WARN: No Supabase credentials – skipping DB upsert for {table}")
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        resp = requests.post(
            url,
            headers=_sb_headers(),
            json=data,
            timeout=10
        )
        if resp.status_code in (200, 201):
            print(f"  [DB] Upserted → {table}")
            return True
        else:
            print(f"  [DB] ERROR {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  [DB] Exception: {e}")
        return False

def supabase_upsert_many(table: str, rows: list) -> bool:
    """Upsert multiple records."""
    if not rows:
        return True
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print(f"  WARN: No Supabase credentials – skipping batch upsert for {table}")
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        resp = requests.post(
            url,
            headers=_sb_headers(),
            json=rows,
            timeout=15
        )
        if resp.status_code in (200, 201):
            print(f"  [DB] Batch upserted {len(rows)} rows → {table}")
            return True
        else:
            print(f"  [DB] Batch ERROR {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  [DB] Batch exception: {e}")
        return False

# ── Step 1: Parse kit metadata from detail page HTML ───────────────────────────
def parse_detail_html(html: str, manual_id: int, source_url: str) -> dict:
    """
    Extracts kit metadata from the Bandai manual detail page.
    Fields: name_jp, name_en, part_no, release_date, brand, series_jp
    """
    soup = BeautifulSoup(html, "html.parser")
    
    kit = {
        "bandai_manual_id": manual_id,
        "source_url": source_url,
        "scraped_at": datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }

    # Page title format: "HG 1/144 アリュゼウス - バンダイプラモデルWEB取説 | ..."
    title = soup.find("title")
    if title:
        raw_title = title.text.strip()
        # Split off the site name suffix
        name_part = raw_title.split(" - ")[0].strip() if " - " in raw_title else raw_title
        kit["name_jp"] = name_part

    # Scan all text for known field labels
    full_text = soup.get_text(separator="\n")

    # Part No: 品番 followed by 7-digit number
    pn_match = re.search(r"品番[^\d]*(\d{7})", full_text)
    kit["part_no"] = pn_match.group(1) if pn_match else None

    # Release date: YYYY年M月D日発売
    rd_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日発売", full_text)
    if rd_match:
        y, m, d = rd_match.groups()
        kit["release_date"] = f"{y}-{int(m):02d}-{int(d):02d}"
    else:
        kit["release_date"] = None
    
    # Replace the brand/series regex with more flexible patterns
    brand_match = re.search(r"(?:ブランド|BRAND)[^\n]*\n+([^\n]+)", full_text)
    kit["brand"] = brand_match.group(1).strip() if brand_match else None
    
    series_match = re.search(r"(?:作品|SERIES)[^\n]*\n+([^\n]+)", full_text)
    kit["series_jp"] = series_match.group(1).strip() if series_match else None
    
    
    # English name: extract from any en-text span or secondary heading
    # The list page provides it but the detail page often doesn't — set None for now
    # Phase 2 crawler will populate this from list page bilingual titles
    kit["name_en"] = None
    kit["series_en"] = None

    return kit

# ── Step 2: Capture manual PDF page 1 as screenshot via Playwright ─────────────
async def capture_manual_page1(page, manual_id: int) -> str | None:
    """
    Opens the manual viewer page, waits for the PDF to render,
    and takes a screenshot of page 1.
    Returns: base64-encoded PNG string, or None on failure.
    """
    viewer_url = DETAIL_URL_TPL.format(manual_id=manual_id)
    print(f"  Opening manual viewer: {viewer_url}")

    try:
        await page.goto(viewer_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)  # allow PDF viewer JS to fully render

        # The manual viewer renders inside the main page iframe or canvas
        # Click the "取扱説明書" (manual) button if it's on the detail landing page
        manual_btn = await page.query_selector('a[href*="menus/detail"], button')
        # Try to find the actual PDF viewer — it may already be loaded
        # Wait for any canvas or iframe that indicates PDF rendering
        try:
            await page.wait_for_selector("canvas, iframe[src*='pdf']", timeout=8000)
            print("  PDF viewer canvas/iframe detected")
        except Exception:
            print("  WARN: No canvas/iframe found, attempting screenshot anyway")

        await asyncio.sleep(2)

        # Full page screenshot then crop to the right half (specs panel)
        screenshot_bytes = await page.screenshot(full_page=False)
        b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        print(f"  Screenshot captured ({len(screenshot_bytes)//1024} KB)")
        return b64

    except Exception as e:
        print(f"  ERROR capturing page 1: {e}")
        return None

# ── Step 3: Extract specs from screenshot via OpenRouter Vision LLM ────────────
def extract_specs_via_vision(image_b64: str) -> dict | None:
    """
    Sends page 1 screenshot to a vision LLM and returns parsed specs JSON.
    """
    if not OPENROUTER_API:
        print("  WARN: No OPENROUTER_API – skipping LLM extraction")
        return None

    print(f"  Sending to vision LLM ({VISION_MODEL})...")

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": SPECS_PROMPT
                    }
                ]
            }
        ],
        "temperature": 0.1,   # low temp = deterministic extraction
        "max_tokens": 2000,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-gunpla-pipeline",
        "X-Title": "Bandai Manual Scraper"
    }

    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"  LLM response received ({len(content)} chars)")

        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        specs = json.loads(content)
        print(f"  Parsed: model={specs.get('model_number')}, "
              f"armaments={len(specs.get('armaments', []))}, "
              f"color_guide={len(specs.get('color_guide', []))}")
        return specs

    except json.JSONDecodeError as e:
        print(f"  ERROR: LLM returned non-JSON: {e}")
        print(f"  Raw content: {content[:300]}")
        return None
    except Exception as e:
        print(f"  ERROR: Vision LLM call failed: {e}")
        return None

# ── Step 4: Save to DB ─────────────────────────────────────────────────────────
def save_to_db(kit: dict, specs: dict | None, manual_id: int) -> None:
    """
    Upserts kit metadata, mecha_specs, and color_guide into Supabase.
    Mirrors your hlj_lowstock_tracker.py Supabase pattern.
    """
    # 1) bandai_kits
    print("\n  [DB] Upserting bandai_kits...")
    supabase_upsert("bandai_kits", kit)

    if not specs:
        print("  [DB] No specs to upsert – skipping mecha_specs + color_guide")
        return

    # 2) mecha_specs
    spec_row = {
        "bandai_manual_id":  manual_id,
        "model_number":      specs.get("model_number"),
        "classification":    specs.get("classification"),
        "head_height":       specs.get("head_height"),
        "weight_empty":      specs.get("weight_empty"),
        "weight_total":      specs.get("weight_total"),
        "generator_output":  specs.get("generator_output"),
        "thruster_output":   specs.get("thruster_output"),
        "material":          specs.get("material"),
        "armaments":         specs.get("armaments", []),  # text[] in PG
        "raw_page1_text":    json.dumps(specs, ensure_ascii=False),  # full LLM output as backup
        "extracted_at":      datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    print("  [DB] Upserting mecha_specs...")
    supabase_upsert("mecha_specs", spec_row)

    # 3) color_guide – one row per color swatch
    color_rows = []
    for swatch in specs.get("color_guide", []):
        color_rows.append({
            "bandai_manual_id": manual_id,
            "part_name":        swatch.get("part_name"),
            "color_name":       swatch.get("color_name"),
            "paint_brand":      swatch.get("paint_brand", "Mr. Color"),
            "mix_ratios":       json.dumps(swatch.get("mix_ratios", [])),
        })
    if color_rows:
        print(f"  [DB] Upserting {len(color_rows)} color_guide rows...")
        supabase_upsert_many("color_guide", color_rows)

# ── Step 5: Save JSON output (mirrors hlj save pattern) ────────────────────────
def save_json(data: dict) -> Path:
    out = OUTPUT_DIR / "bandai_manual_poc.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [JSON] -> {out}")
    return out

# ── Phase 2: List page parser (for bulk crawl) ─────────────────────────────────
def parse_list_page(html: str) -> list:
    """
    Parses a Bandai manual list page and returns list of:
    {manual_id, name_jp, name_en, release_date}
    Used in Phase 2+ bulk crawl.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Each result card is an anchor wrapping the item
    # URL pattern: /menus/detail/{id}
    links = soup.find_all("a", href=re.compile(r"/menus/detail/(\d+)"))
    for link in links:
        href = link.get("href", "")
        id_match = re.search(r"/menus/detail/(\d+)", href)
        if not id_match:
            continue
        manual_id = int(id_match.group(1))

        # Avoid duplicates (same link can appear multiple times per card)
        if any(i["manual_id"] == manual_id for i in items):
            continue

        # Name: bilingual cards have JP + EN text
        card_text = link.get_text(separator="\n").strip()
        lines = [ln.strip() for ln in card_text.splitlines() if ln.strip()]
        name_jp = lines[0] if lines else None
        name_en = lines[1] if len(lines) > 1 else None

        # Release date from nearby text — look at parent container
        parent = link.find_parent()
        parent_text = parent.get_text(separator="\n") if parent else ""
        rd_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日発売", parent_text)
        release_date = None
        if rd_match:
            y, m, d = rd_match.groups()
            release_date = f"{y}-{int(m):02d}-{int(d):02d}"

        items.append({
            "manual_id":    manual_id,
            "name_jp":      name_jp,
            "name_en":      name_en,
            "release_date": release_date,
        })

    return items

# ── Main POC ───────────────────────────────────────────────────────────────────
async def scrape_single_kit(manual_id: int) -> dict:
    """
    Full pipeline for a single Bandai manual kit:
    1. Fetch detail page → kit metadata
    2. Capture manual viewer screenshot → page 1 image
    3. Vision LLM → extract specs + color guide JSON
    4. Upsert all to Supabase
    5. Save local JSON
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f"  BANDAI MANUAL SCRAPER  |  POC  |  {ts}")
    print(f"{'='*64}")
    print(f"  Target manual ID : {manual_id}")
    print(f"  Detail URL       : {DETAIL_URL_TPL.format(manual_id=manual_id)}")
    print(f"  Vision model     : {VISION_MODEL}")
    print(f"{'='*64}\n")

    result = {
        "manual_id":  manual_id,
        "kit":        None,
        "specs":      None,
        "status":     "pending",
        "scraped_at": datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
                "--ignore-certificate-errors",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            ignore_https_errors=True,
        )

        page = await context.new_page()
        await stealth_async(page)

        # ── Step 1: Detail page → kit metadata ────────────────────────────
        print(">> STEP 1: Fetching kit metadata from detail page...")
        detail_url = DETAIL_URL_TPL.format(manual_id=manual_id)
        try:
            await page.goto(detail_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)  # allow JS to hydrate
            html = await page.content()
            kit = parse_detail_html(html, manual_id, detail_url)
            result["kit"] = kit
            print(f"  name_jp      : {kit.get('name_jp')}")
            print(f"  part_no      : {kit.get('part_no')}")
            print(f"  release_date : {kit.get('release_date')}")
            print(f"  brand        : {kit.get('brand')}")
            print(f"  series_jp    : {kit.get('series_jp')}")
        except Exception as e:
            print(f"  ERROR in Step 1: {e}")
            result["status"] = "error_metadata"
            await browser.close()
            return result

        await asyncio.sleep(SCRAPE_DELAY)

        # ── Step 2: Open manual viewer → screenshot page 1 ────────────────
        print("\n>> STEP 2: Capturing manual page 1 screenshot...")
        
        #