#!/usr/bin/env python3
"""bandai_manual_scraper.py v5 - vision LLM + Supabase 3-table upsert"""

import asyncio, json, re, os, base64, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup

BANDAI_BASE    = "https://manual.bandai-hobby.net"
DETAIL_URL_TPL = f"{BANDAI_BASE}/menus/detail/{{manual_id}}"
LIST_URL_TPL   = f"{BANDAI_BASE}/?sort=new&categories[0]=1&page={{page}}"
SCRAPE_DELAY   = 2
PHT            = timezone(timedelta(hours=8))
OUTPUT_DIR     = Path("/app/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL   = os.getenv("SUPABASE_URL")
SUPABASE_KEY   = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
OPENROUTER_API = os.getenv("OPENROUTER_API")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL   = "google/gemini-flash-1.5"

# ─────────────────────────────────────────────────────────────────────
# PROMPT — structured extraction from manual page 1 screenshot
# ─────────────────────────────────────────────────────────────────────
SPECS_PROMPT = """You are a Gundam model kit data extractor.
This is page 1 of a Bandai HG Gunpla instruction manual.
Extract ALL visible mobile suit specifications and color guide data.
Return ONLY valid JSON (no markdown, no code fences, no extra text):
{
  "model_number": "",
  "name_en": "",
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
      "mix_ratios": [{"color": "", "percentage": 0}]
    }
  ]
}
Rules:
- armaments = flat array of weapon name strings (English if visible)
- Numbers must include units, e.g. "26.7m", "83.0t", "3500kW"
- mix_ratios percentages must sum to 100 per color entry
- If a field is not visible in the image, use null
- paint_brand: use "Mr. Color" unless another brand is explicitly shown"""

# ─────────────────────────────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

def supabase_upsert(table, data, conflict_col="bandai_manual_id"):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"  WARN: No Supabase credentials"); return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict_col}"
    try:
        r = requests.post(url, headers=_sb_headers(), json=data, timeout=10)
        if r.status_code in (200, 201):
            print(f"  [DB] ✓ Upserted -> {table}"); return True
        print(f"  [DB] ERROR {r.status_code} on {table}: {r.text[:400]}")
        return False
    except Exception as e:
        print(f"  [DB] Exception on {table}: {e}"); return False

def supabase_upsert_many(table, rows, conflict_col="bandai_manual_id"):
    if not rows: return True
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"  WARN: No Supabase credentials"); return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict_col}"
    try:
        r = requests.post(url, headers=_sb_headers(), json=rows, timeout=15)
        if r.status_code in (200, 201):
            print(f"  [DB] ✓ Batch {len(rows)} rows -> {table}"); return True
        print(f"  [DB] Batch ERROR {r.status_code} on {table}: {r.text[:400]}")
        return False
    except Exception as e:
        print(f"  [DB] Exception on {table}: {e}"); return False

# ─────────────────────────────────────────────────────────────────────
# STEP 1 — Metadata from detail page DOM
# ─────────────────────────────────────────────────────────────────────

async def extract_metadata_from_page(page, manual_id, source_url):
    kit = {
        "bandai_manual_id": str(manual_id),
        "source_url":       source_url,
        "scraped_at":       datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "name_jp":          None,
        "name_en":          None,
        "part_no":          None,
        "release_date":     None,
        "brand":            None,
        "series_jp":        None,
        "series_en":        None,
    }
    try:
        title = await page.title()
        kit["name_jp"] = title.split(" - ")[0].strip() if " - " in title else title.strip()

        full_text = await page.inner_text("body")

        pn = re.search(r"品番[^\d]*(\d{7})", full_text)
        kit["part_no"] = pn.group(1) if pn else None

        rd = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日発売", full_text)
        if rd:
            kit["release_date"] = f"{rd.group(1)}-{int(rd.group(2)):02d}-{int(rd.group(3)):02d}"
        else:
            # partial date like "2026年4月発売" → day = 01
            rd2 = re.search(r"(\d{4})年(\d{1,2})月発売", full_text)
            if rd2:
                kit["release_date"] = f"{rd2.group(1)}-{int(rd2.group(2)):02d}-01"

        kit["brand"] = await page.evaluate("""
            () => {
                for (const dt of document.querySelectorAll('dt')) {
                    if (dt.textContent.trim() === 'ブランド') {
                        const dd = dt.nextElementSibling;
                        return dd ? dd.textContent.trim() : null;
                    }
                }
                return null;
            }
        """)

        kit["series_jp"] = await page.evaluate("""
            () => {
                for (const dt of document.querySelectorAll('dt')) {
                    if (dt.textContent.trim() === '作品') {
                        const dd = dt.nextElementSibling;
                        return dd ? dd.textContent.trim() : null;
                    }
                }
                return null;
            }
        """)

    except Exception as e:
        print(f"  WARN metadata: {e}")
    return kit

# ─────────────────────────────────────────────────────────────────────
# STEP 2 — Screenshot manual page 1 from PDF viewer popup
# ─────────────────────────────────────────────────────────────────────

async def capture_manual_page1(page):
    """
    Click 取扱説明書 → intercept popup PDF viewer → screenshot page 1.
    The viewer renders as a canvas — wait for it to paint before screenshotting.
    Falls back to detail-page screenshot if popup fails.
    """
    screenshot_bytes = None
    try:
        print("  Looking for manual button...")
        btn = await page.query_selector("a:has-text('取扱説明書'), button:has-text('取扱説明書')")
        if not btn:
            raise Exception("Manual button not found")

        print("  Waiting for popup...")
        async with page.expect_popup(timeout=15000) as popup_info:
            await btn.click()

        viewer = await popup_info.value
        print(f"  Popup URL: {viewer.url}")

        # Wait for page to fully load
        await viewer.wait_for_load_state("networkidle", timeout=20000)
        await asyncio.sleep(4)

        # Wait for canvas (PDF rendered via PDF.js or similar)
        try:
            await viewer.wait_for_selector("canvas", timeout=12000)
            print("  Canvas detected — waiting for render...")
            await asyncio.sleep(4)
        except Exception:
            print("  No canvas — proceeding with screenshot")

        # Scroll to top to ensure page 1
        await viewer.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        screenshot_bytes = await viewer.screenshot(full_page=False)
        print(f"  Screenshot: {len(screenshot_bytes) // 1024} KB")
        await viewer.close()

    except Exception as e:
        print(f"  Popup capture failed: {e} — using detail page fallback")
        try:
            screenshot_bytes = await page.screenshot(full_page=False)
            print(f"  Fallback screenshot: {len(screenshot_bytes) // 1024} KB")
        except Exception as e2:
            print(f"  Fallback also failed: {e2}")

    if not screenshot_bytes:
        return None, None

    b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    return screenshot_bytes, b64

# ─────────────────────────────────────────────────────────────────────
# STEP 3 — Vision LLM extraction
# ─────────────────────────────────────────────────────────────────────

def extract_specs_via_vision(image_b64):
    if not OPENROUTER_API:
        print("  WARN: OPENROUTER_API not set — skipping vision step")
        return None
    print(f"  Calling vision model: {VISION_MODEL}")
    try:
        r = requests.post(OPENROUTER_URL, json={
            "model": VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                    },
                    {"type": "text", "text": SPECS_PROMPT}
                ]
            }],
            "temperature": 0.1,
            "max_tokens": 2000,
        }, headers={
            "Authorization": f"Bearer {OPENROUTER_API}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/gunpla-pipeline",
            "X-Title": "Bandai Manual Scraper v5",
        }, timeout=60)
        r.raise_for_status()

        content = r.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if model adds them despite instructions
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()

        specs = json.loads(content)
        print(f"  ✓ model_number={specs.get('model_number')}, "
              f"armaments={len(specs.get('armaments', []))}, "
              f"colors={len(specs.get('color_guide', []))}")
        return specs

    except json.JSONDecodeError as e:
        print(f"  ERROR: LLM returned non-JSON: {e}")
        print(f"  Raw content: {content[:500]}")
        return None
    except Exception as e:
        print(f"  ERROR vision LLM: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────
# STEP 4 — Save to Supabase (3 tables)
# ─────────────────────────────────────────────────────────────────────

def save_to_db(kit, specs, manual_id):
    mid = str(manual_id)

    # ── TABLE 1: bandai_kits ──────────────────────────────────────────
    # Merge name_en from vision specs if DOM didn't have it
    if specs and specs.get("name_en") and not kit.get("name_en"):
        kit["name_en"] = specs["name_en"]

    print("  [DB] → bandai_kits")
    supabase_upsert("bandai_kits", kit, conflict_col="bandai_manual_id")

    if not specs:
        print("  [DB] No specs extracted — skipping mecha_specs + color_guide")
        return

    # ── TABLE 2: mecha_specs ─────────────────────────────────────────
    print("  [DB] → mecha_specs")
    supabase_upsert("mecha_specs", {
        "bandai_manual_id": mid,
        "model_number":     specs.get("model_number"),
        "name_en":          specs.get("name_en"),
        "classification":   specs.get("classification"),
        "head_height":      specs.get("head_height"),
        "weight_empty":     specs.get("weight_empty"),
        "weight_total":     specs.get("weight_total"),
        "generator_output": specs.get("generator_output"),
        "thruster_output":  specs.get("thruster_output"),
        "material":         specs.get("material"),
        "armaments":        specs.get("armaments", []),    # stored as JSONB array
        "raw_page1_json":   json.dumps(specs, ensure_ascii=False),
        "extracted_at":     datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }, conflict_col="bandai_manual_id")

    # ── TABLE 3: color_guide ─────────────────────────────────────────
    color_guide = specs.get("color_guide", [])
    if not color_guide:
        print("  [DB] No color guide entries found")
        return

    # Delete existing rows for this manual_id first (clean re-insert)
    # because color_guide rows don't have a single natural unique key per row
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            del_url = f"{SUPABASE_URL}/rest/v1/color_guide?bandai_manual_id=eq.{mid}"
            requests.delete(del_url, headers=_sb_headers(), timeout=10)
            print(f"  [DB] Cleared old color_guide rows for {mid}")
        except Exception as e:
            print(f"  [DB] WARN delete old colors: {e}")

    color_rows = []
    for s in color_guide:
        if not s.get("part_name") and not s.get("color_name"):
            continue   # skip empty entries from LLM hallucinations
        color_rows.append({
            "bandai_manual_id": mid,
            "part_name":        s.get("part_name"),
            "color_name":       s.get("color_name"),
            "paint_brand":      s.get("paint_brand") or "Mr. Color",
            "mix_ratios":       json.dumps(s.get("mix_ratios", []), ensure_ascii=False),
        })

    if color_rows:
        print(f"  [DB] → color_guide ({len(color_rows)} rows)")
        # color_guide uses insert (not upsert) since we deleted first
        if SUPABASE_URL and SUPABASE_KEY:
            url = f"{SUPABASE_URL}/rest/v1/color_guide"
            headers = _sb_headers()
            headers["Prefer"] = "return=minimal"
            try:
                r = requests.post(url, headers=headers, json=color_rows, timeout=15)
                if r.status_code in (200, 201):
                    print(f"  [DB] ✓ Inserted {len(color_rows)} color_guide rows")
                else:
                    print(f"  [DB] color_guide ERROR {r.status_code}: {r.text[:400]}")
            except Exception as e:
                print(f"  [DB] color_guide exception: {e}")

# ─────────────────────────────────────────────────────────────────────
# MAIN SCRAPE — single kit
# ─────────────────────────────────────────────────────────────────────

async def scrape_single_kit(manual_id):
    ts = datetime.now(PHT).strftime("%Y-%m-%d %H:%M PHT")
    print(f"\n{'='*60}")
    print(f"  BANDAI SCRAPER v5 | manual_id={manual_id} | {ts}")
    print(f"  OPENROUTER_API : {'SET ✓' if OPENROUTER_API else 'NOT SET ✗'}")
    print(f"  SUPABASE_KEY   : {'SET ✓' if SUPABASE_KEY else 'NOT SET ✗'}")
    print(f"  VISION_MODEL   : {VISION_MODEL}")
    print(f"{'='*60}")

    result = {
        "manual_id":  str(manual_id),
        "kit":        None,
        "specs":      None,
        "status":     "pending",
        "scraped_at": datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1920,1080", "--ignore-certificate-errors",
        ])
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

        # ── STEP 1: Metadata ─────────────────────────────────────────
        print("\n>> STEP 1: Fetching kit metadata...")
        detail_url = DETAIL_URL_TPL.format(manual_id=manual_id)
        try:
            await page.goto(detail_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            kit = await extract_metadata_from_page(page, manual_id, detail_url)
            result["kit"] = kit
            print(f"  name_jp      : {kit.get('name_jp')}")
            print(f"  part_no      : {kit.get('part_no')}")
            print(f"  release_date : {kit.get('release_date')}")
            print(f"  brand        : {kit.get('brand')}")
            print(f"  series_jp    : {kit.get('series_jp')}")
        except Exception as e:
            print(f"  ERROR step 1: {e}")
            result["status"] = "error_metadata"
            await browser.close()
            return result

        # ── STEP 2: Screenshot manual page 1 ─────────────────────────
        print("\n>> STEP 2: Capturing manual page 1...")
        screenshot_bytes, image_b64 = await capture_manual_page1(page)
        if screenshot_bytes:
            ss_path = OUTPUT_DIR / f"manual_{manual_id}_page1.png"
            ss_path.write_bytes(screenshot_bytes)
            print(f"  Saved screenshot: {ss_path}")

        await browser.close()

    # ── STEP 3: Vision LLM (outside browser context to save memory) ──
    specs = None
    if image_b64:
        print("\n>> STEP 3: Vision LLM extraction...")
        specs = extract_specs_via_vision(image_b64)
        result["specs"] = specs
    else:
        print("\n>> STEP 3: SKIP — no screenshot captured")

    # ── STEP 4: Save to Supabase ─────────────────────────────────────
    print("\n>> STEP 4: Saving to Supabase...")
    if result["kit"]:
        save_to_db(result["kit"], specs, manual_id)
    else:
        print("  SKIP — no kit metadata")

    # Save local JSON
    out = OUTPUT_DIR / f"bandai_kit_{manual_id}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  [JSON] → {out}")
    result["status"] = "done"
    print(f"\n{'='*60}\n  DONE | manual_id={manual_id}\n{'='*60}\n")
    return result

# ─────────────────────────────────────────────────────────────────────
# LIST PAGE CRAWLER
# ─────────────────────────────────────────────────────────────────────

async def scrape_list_page_kits(page_num, year_cutoff=None, category=None):
    list_url = LIST_URL_TPL.format(page=page_num)
    print(f"\n>> List page {page_num}: {list_url}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            locale="ja-JP",
        )
        page = await ctx.new_page()
        await stealth_async(page)
        try:
            await page.goto(list_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(SCRAPE_DELAY)
            
            kits = []
            # Extract all detail links from list page
            links = await page.query_selector_all("a[href*='/menus/detail/']")
            seen = set()
            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                m = re.search(r'/menus/detail/(\d+)', href)
                if not m:
                    continue
                manual_id = int(m.group(1))
                if manual_id in seen:
                    continue
                seen.add(manual_id)
                
                # Get name text from link or parent card
                name = (await link.inner_text()).strip()
                if not name:
                    parent = await link.query_selector("..")
                    name = (await parent.inner_text()).strip()[:100] if parent else ""
                
                # Look for year in surrounding text
                parent_text = ""
                try:
                    card = await page.query_selector(f"a[href*='/menus/detail/{manual_id}']")
                    if card:
                        container = await card.evaluate_handle("el => el.closest('li, .item, .card, article') || el.parentElement")
                        parent_text = await container.evaluate("el => el ? el.innerText : ''")
                except:
                    pass
                
                # Year filter: include if year matches OR no cutoff set
                if year_cutoff:
                    yr = year_cutoff[:4]  # "2026"
                    if yr not in parent_text and f"{yr[2:]}年" not in parent_text:
                        # If release date not visible on card, include anyway — 
                        # detail scrape will confirm via DOM
                        pass  # Include all; filter post-detail
                
                kits.append({"manual_id": manual_id, "name": name})
            
            print(f"  Found {len(kits)} kits on page {page_num}")
            await browser.close()
            return kits

        except Exception as e:
            print(f"  ERROR list page {page_num}: {e}")
            await browser.close()
            return []