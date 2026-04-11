#!/usr/bin/env python3
"""
hlj_lowstock_tracker.py
========================
Standalone HLJ Low-Stock Tracker – no app.config / app.database needed.
Mirrors exact selector logic from your existing scrapers:
  - _selectors.py        -> HLJSelectors (PRODUCT_CARD, PRICE_LOADED, STOCK_STATUS...)
  - hobby_link_japan.py  -> parse_product() stock-detection pattern
  - base_scraper.py      -> parse_price() pattern

Run:
    python hlj_lowstock_tracker.py

Outputs (same directory as script):
    low_stock.json   – structured data
    low_stock.csv    – UTF-8 BOM (Excel-ready)
    low_stock.html   – editable table, localStorage notes, CSV export
"""


import asyncio
import json
import csv
import re
import sys
import os
import requests
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()  # Loads .env from script dir or parent


# ── Selectors: mirrors _selectors.py exactly ─────────────────────────────────
# Try project import first (when run from D-tracker-verified/),
# otherwise falls back to the inline copy below.
try:
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from app.scrapers._selectors import HLJSelectors
    print("Using project HLJSelectors")
except ImportError:
    class HLJSelectors:
        PRODUCT_CARD  = ".search-widget-block"
        PRODUCT_NAME  = ".product-item-name a"
        PRODUCT_PRICE = '[id$="_price"]'
        PRODUCT_IMAGE = "img"
        STOCK_STATUS  = '[id$="_stockStatusDetail"]'
        ON_SALE_FLAG  = '[id$="_is_on_sale"]'
        PRICE_LOADED  = '[id$="_price"]:not(:empty)'

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from playwright_stealth import stealth_async

# ── Config ────────────────────────────────────────────────────────────────────
HLJ_BASE      = "https://www.hlj.com"
SCRAPE_URL         = f"{HLJ_BASE}/search/?Word=gundam&StockLevel=In%C2%A0Stock"
AFFILIATE_TAG      = "utm_source=speedartug&utm_medium=affiliate"
SCRAPE_DELAY       = 1        # seconds – respectful crawling
LOW_STOCK_THRESHOLD = 5       # catches "Only 1" through "Only 5 left in stock"
MAX_PAGES          = 10       # Word=gundam has ~407 items across 17 pages
OUTPUT_DIR    = Path(__file__).resolve().parent
PHT = timezone(timedelta(hours=8))

FIELDS = ["name","grade_scale","price_jpy","price_php","price_sgd","price_usd","price_myr","price_thb","price_idr","stock","sku","image_url","image_urls","affiliate_url","scraped_at","notes"]

# ── SUPABASE EXCHANGE RATES ──────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

RATES_URL = f"{SUPABASE_URL}/rest/v1/exchange_rates?base=eq.JPY&select=*&limit=1"


def fetch_rates():
    """Fetch live JPY rates from Supabase exchange_rates table."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("  WARN: No SUPABASE_URL/KEY — using hardcoded fallback")
        return {
            "php": 0.37, "sgd": 0.0095, "usd": 0.0067,
            "myr": 0.032, "thb": 0.24, "idr": 108,
            "updated_at": "fallback"
        }
    
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}"
    }
    
    try:
        resp = requests.get(RATES_URL, headers=headers, timeout=5)
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            row = {k: float(rows[0][k]) for k in ['php','sgd','usd','myr','thb','idr']}
            updated = str(rows[0].get('updated_at', 'unknown'))[:16]
            print(f"  Rates: ₱{row['php']:.4f} S${row['sgd']:.4f} ${row['usd']:.4f} "
                  f"RM{row['myr']:.4f} ฿{row['thb']:.4f} IDR{row['idr']:.0f} "
                  f"({updated})")
            return row
        else:
            print("  WARN: No rates in Supabase — using fallback")
            return {
                "php": 0.37, "sgd": 0.0095, "usd": 0.0067,
                "myr": 0.032, "thb": 0.24, "idr": 108,
                "updated_at": "fallback"
            }
    except Exception as e:
        print(f"  ERROR: Supabase rates fetch failed ({e}) — using fallback")
        return {
            "php": 0.37, "sgd": 0.0095, "usd": 0.0067,
            "myr": 0.032, "thb": 0.24, "idr": 108,
            "updated_at": "fallback"
        }


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_currency_price(text: str):
    """Returns (value, currency) or (None, None)"""
    if not text:
        return None, None
    
    # Detect currency symbol
    if '₱' in text: curr = 'PHP'
    elif '¥' in text or '円' in text: curr = 'JPY'
    elif '$' in text: curr = 'USD'
    else: curr = 'UNKNOWN'
    
    cleaned = re.sub(r"[^\d.]", "", text)
    value = float(cleaned) if cleaned else None
    return value, curr

def parse_price(text: str):
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None



def fmt_jpy(price) -> str:
    return f"¥{price:,.0f}" if price else "N/A"


def build_affiliate_url(product_url: str) -> str:
    base = product_url.split("?")[0]
    return f"{base}?{AFFILIATE_TAG}"


def extract_grade_scale(name: str) -> str:
    """Dynamic grade/scale parser — auto-detects any HG__ variant."""

    # Fixed grades — order matters (specific before generic)
    FIXED = [
        (r"\bMGEX\b", "MGEX"),
        (r"\bMGSD\b", "MGSD"),
        (r"\bPG\b",   "PG 1/60"),
        (r"\bMG\b",   "MG 1/100"),
        (r"\bRG\b",   "RG 1/144"),
        (r"\bEG\b",   "1/144 ENTRY GRADE"),
        (r"\bBB\b",   "SD BB"),
        (r"\bSD\b",   "SD"),
    ]

    # Step 1 — fixed grades first
    for pat, label in FIXED:
        if re.search(pat, name, re.I):
            scale = re.search(r"1/(\d+)", name)
            grade = label.split()[0]
            return f"{grade} 1/{scale.group(1)}" if scale else label

    # Step 2 — dynamic HG__ catch-all (HGUC, HGCE, HGIBO, HGTWFM, HGWFM, HGSD, etc.)
    hg_match = re.search(r"\bHG([A-Z]{0,6})\b", name, re.I)
    if hg_match:
        suffix = hg_match.group(1).upper()
        grade  = f"HG{suffix}" if suffix else "HG"
        scale  = re.search(r"1/(\d+)", name)
        return f"{grade} 1/{scale.group(1)}" if scale else f"{grade} 1/144"

    # Step 3 — scale only fallback
    scale = re.search(r"1/(\d+)", name)
    return f"1/{scale.group(1)}" if scale else "Unknown"

import json
from urllib.parse import urljoin

async def get_detail_images(detail_page, img_url: str) -> list:
    """Get up to 3 full-size product images from HLJ detail page."""
    def fix_url(u: str) -> str:
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        return urljoin("https://www.hlj.com", u)

    images = []

    try:
        # 1) Full-size gallery images from Fotorama anchors
        anchors = await detail_page.query_selector_all(
            ".product-images-fotorama-container a[href*='productimages']"
        )
        for a in anchors:
            href = await a.get_attribute("href")
            if href:
                u = fix_url(href)
                if u and u not in images:
                    images.append(u)
                if len(images) >= 3:
                    break

        # 2) JSON-LD fallback for single-image products
        if not images:
            scripts = await detail_page.query_selector_all(
                'script[type="application/ld+json"]'
            )
            for s in scripts:
                txt = await s.text_content()
                if not txt:
                    continue
                try:
                    data = json.loads(txt)
                    if isinstance(data, dict) and data.get("image"):
                        main_img = fix_url(data["image"])
                        if main_img and main_img not in images:
                            images.append(main_img)
                        break
                except Exception:
                    continue

        # 3) Final fallback to list image
        if not images and img_url and "noImage" not in img_url:
            images = [img_url]

    except Exception as e:
        print(f"       WARN get_detail_images: {e}")
        if img_url and "noImage" not in img_url:
            images = [img_url]

    print(f"       Images found: {len(images)}")
    return images[:3]
    
# ── Gunpla Name/SKU Filter ────────────────────────────────────────────────────
NON_GUNPLA_SKU_PREFIXES = (
    "ABA",   # Abystyle apparel / anime merch
    "KBY",   # Kibear / novelties
    "AZM",   # Aoshima model kits (aircraft, cars)
    "KPM",   # Klear Kutter masks
    "AZMP",  # Aoshima aircraft
    "HBJ",   # Gundam Weapons artbook/guide series (NOT plastic kits)
    "GNZ",   # Gunze/GSI Creos markers and paints
)

GRADE_PATTERNS = re.compile(
    r"\b(MGEX|MGSD|PG|MG|RG|EG|SD|BB|HG[A-Z]{0,6})\b", re.I
)

SCALE_PATTERNS = re.compile(r"1/(144|100|60|48|35)", re.I)

MS_KEYWORDS = [
    "gundam", "gunpla", "zaku", "rx-78", "wing zero", "strike freedom",
    "unicorn", "nu gundam", "sazabi", "sinanju", "barbatos", "astray",
    "exia", "00 raiser", "freedom", "justice", "destiny", "providence",
    "impulse", "infinite justice", "gelgoog", "gouf", "dom ", "rick dom",
    "gm ", "ball ", "jegan", "ReZEL", "kshatriya", "hyaku shiki",
]

def is_gunpla(name: str, sku: str) -> bool:
    if sku.upper().startswith(NON_GUNPLA_SKU_PREFIXES):
        return False
    name_lower = name.lower()
    return bool(
        GRADE_PATTERNS.search(name)        # any grade match
        or SCALE_PATTERNS.search(name)     # any scale match
        or any(kw in name_lower for kw in MS_KEYWORDS)  # MS name match
    )


# ── Core Scraper ──────────────────────────────────────────────────────────────
async def scrape_low_stock(threshold: int = None) -> list:
    thresh = threshold if threshold is not None else LOW_STOCK_THRESHOLD
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f"  HLJ LOW-STOCK TRACKER  |  {ts}")
    print(f"{'='*64}")
    print(f"  URL    : {SCRAPE_URL}")
    print(f"  Threshold : only ≤{thresh} left  |  Pages : {MAX_PAGES}")
    print(f"  Delay  : {SCRAPE_DELAY}s")
    print(f"{'='*64}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Manila",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            }
        )
        page = await context.new_page()
        await stealth_async(page)
        await asyncio.sleep(2)

        print(">> Fetching live exchange rates...")
        rates = fetch_rates()

        low_stock = []
        global_idx = 0

        for page_num in range(1, MAX_PAGES + 1):
            page_url = f"{SCRAPE_URL}&Page={page_num}"
            print(f"\n>> Page {page_num}/{MAX_PAGES}: {page_url}")
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                
            print(">> Waiting for price elements...")
            try:
                await page.wait_for_selector(HLJSelectors.PRICE_LOADED, timeout=8000)
            except Exception:
                print("   WARN: No prices — continuing with static HTML")

            # Extra wait for JS-injected stock divs (load AFTER price elements)
            try:
                await page.wait_for_selector(HLJSelectors.STOCK_STATUS, timeout=5000)
            except Exception:
                await asyncio.sleep(2)

            html  = await page.content()
            soup  = BeautifulSoup(html, "html.parser")
            cards = soup.select(HLJSelectors.PRODUCT_CARD)
            if not cards:
                print(f"   No cards on page {page_num} — stopping.")
                break
            print(f"\n[+] Page {page_num}: {len(cards)} products found\n")

            for card in cards:
                global_idx += 1
                idx = global_idx
                try:
                    # Name + URL
                    name_el  = card.select_one(HLJSelectors.PRODUCT_NAME)
                    name     = name_el.text.strip() if name_el else "Unknown"
                    href     = name_el.get("href", "") if name_el else ""
                    prod_url = f"{HLJ_BASE}{href}" if href else SCRAPE_URL
    
                    # SKU from price element id: "{SKU}_price"
                    price_el  = card.select_one(HLJSelectors.PRODUCT_PRICE)
                    price_txt = price_el.text.strip() if price_el else ""
                    sku = "Unknown"
                                    
                    if price_el and price_el.get("id"):
                        sku = price_el["id"].replace("_price", "")
                    print(f"       List price txt: '{price_txt}'")  # DEBUG
    
                    # Stock detection — exact logic from hobby_link_japan.py
                    order_stop = card.find(string=re.compile(r"Order Stop|Notify Me", re.I))
                    if order_stop:
                        stock = "ORDER_STOP"
                        print(f"  BLOCKED SKU:{sku}")
                    else:
                        stock = "Unknown"
                        if sku != "Unknown":
                            detail_div = card.select_one(f"div#{sku}_stockStatusDetail")
                            if detail_div:
                                stock = detail_div.get_text(strip=True)
                        if stock == "Unknown":
                            fb = card.select_one(HLJSelectors.STOCK_STATUS)
                            stock = fb.text.strip() if fb else "Unknown"
    
                    # Image
                    img_el  = card.select_one(HLJSelectors.PRODUCT_IMAGE)
                    img_src = img_el.get("src", "") if img_el else ""
                    img_url = f"https:{img_src}" if img_src.startswith("//") else img_src
    
                    # GUNPLA FILTER
                    if not is_gunpla(name, sku):
                        print(f"  [{idx:04d}] SKIP non-Gunpla: {name[:40]}")
                        continue
                    print(f"  [{idx:04d}] {name[:44]:<44} | {sku:<14} | {stock}")
    
                    # LOW-STOCK FILTER — regex threshold
                    qty_match = re.search(r"only (\d+) left", stock.lower())
                    if not qty_match or int(qty_match.group(1)) > thresh:
                        continue
                                                  
                    print(f"  !!! LOW STOCK -> {name[:60]}")
                    needs_detail = not price_txt or ('¥' not in price_txt and '円' not in price_txt)
                    images = [img_url] if img_url else []

                    try:
                        detail_page = await browser.new_page()
                        await detail_page.goto(prod_url, wait_until="domcontentloaded", timeout=10000)

                        if needs_detail:
                            detail_price_el = await detail_page.wait_for_selector(
                                f'#{sku}_price:not(:empty)', timeout=3000
                            )
                            fetched = await detail_price_el.text_content()
                            price_txt = fetched.strip() if fetched else price_txt

                        images = await get_detail_images(detail_page, img_url)

                        await detail_page.close()
                        print(f"       Product price: {price_txt}")
                        print(f"       Images found: {len(images)}")
                    except Exception as e:
                        print(f"       WARN product page: {e} — using list")
                        images = [img_url] if img_url else []
       
                 # Price conversion
                    value, curr = parse_currency_price(price_txt)
                    if value:
                        if curr == 'PHP':
                            price_php = value
                            price_jpy = round(value / rates["php"], 0)
                        elif curr == 'JPY':
                            price_jpy = value
                            price_php = round(value * rates["php"], 2)
                        else:
                            price_jpy = value  # Assume JPY default
                            price_php = round(value * rates["php"], 2)
                    else:
                        price_jpy = price_php = None
    
                
                    price_sgd = round(price_jpy * rates["sgd"], 2) if price_jpy else None
                    price_usd = round(price_jpy * rates["usd"], 2) if price_jpy else None
                    price_myr = round(price_jpy * rates["myr"], 2) if price_jpy else None
                    price_thb = round(price_jpy * rates["thb"], 2) if price_jpy else None
                    price_idr = round(price_jpy * rates["idr"], 0) if price_jpy else None                
                    
                    low_stock.append({
                        "name":          name,
                        "grade_scale":   extract_grade_scale(name),
                        "price_jpy":     fmt_jpy(price_jpy),
                        "price_php":     price_php,
                        "price_sgd":     price_sgd,
                        "price_usd":     price_usd,
                        "price_myr":     price_myr,
                        "price_thb":     price_thb,
                        "price_idr":     price_idr,
                        "stock":         stock,
                        "sku":           sku,
                        "image_url":     images[0] if images else img_url,
                        "image_urls":    images if images else [img_url] if img_url else [],
                        "affiliate_url": build_affiliate_url(prod_url),
                        "scraped_at": datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                        "notes":         ""
                    })
    
                    await asyncio.sleep(SCRAPE_DELAY)   
    
                except Exception as e:
                    print(f"  WARN [{idx}]: {e}")
                    continue

        await browser.close()

    print(f"\n{'='*64}")
    print(f"  RESULT: {len(low_stock)} low-stock items found")
    print(f"{'='*64}\n")
    return low_stock


# ── Save: JSON ────────────────────────────────────────────────────────────────
def save_json(items: list) -> Path:
    out = OUTPUT_DIR / "low_stock.json"
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [JSON]  -> {out}")
    return out


# ── Save: CSV ─────────────────────────────────────────────────────────────────
def save_csv(items: list) -> Path:
    out = OUTPUT_DIR / "low_stock.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:   
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    print(f"  [CSV]   -> {out}")
    return out


# ── Save: HTML ────────────────────────────────────────────────────────────────
def save_html(items: list) -> Path:
    out    = OUTPUT_DIR / "low_stock.html"
    ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count  = len(items)

    data_json_str = json.dumps(items, ensure_ascii=False)

    rows = ""
    if not items:
        rows = ('<tr><td colspan="14" style="text-align:center;padding:40px;color:#888">'
                "No low-stock items found. Re-run script to refresh.</td></tr>")
    else:
        for i, it in enumerate(items):
            php_str = f"₱{it['price_php']:,.2f}" if it["price_php"] else "N/A"
            sgd_str = f"S${it['price_sgd']:,.2f}" if it["price_sgd"] else "N/A"
            usd_str = f"${it['price_usd']:,.2f}" if it["price_usd"] else "N/A"
            myr_str = f"RM{it['price_myr']:,.2f}" if it["price_myr"] else "N/A"
            thb_str = f"฿{it['price_thb']:,.2f}" if it["price_thb"] else "N/A"
            idr_str = f"Rp{it['price_idr']:,.0f}" if it["price_idr"] else "N/A"

            # Multi-image thumbnails
            img_urls = it.get('image_urls', [])
            if not img_urls:
                img_urls = [it.get('image_url', '')]
            
            thumbs = ''
            for j, img in enumerate(img_urls[:3]):
                if img:
                    thumbs += f'<img src="{img}" alt="" class="th">'
            
            img_cell = f'<div class="ig">{thumbs}</div>' if thumbs else '&mdash;'
            
            rows += (
                f'<tr data-idx="{i}">'
                f'<td>{img_cell}</td>'
                f'<td class="nc"><a href="{it["affiliate_url"]}" target="_blank">{it["name"]}</a></td>'
                f'<td><span class="gr">{it["grade_scale"]}</span></td>'
                f'<td class="mu">{it["price_jpy"]}</td>'
                f'<td class="ph">{php_str}</td>'
                f'<td class="sgd">{sgd_str}</td>'
                f'<td class="usd">{usd_str}</td>'
                f'<td class="myr">{myr_str}</td>'
                f'<td class="thb">{thb_str}</td>'
                f'<td class="idr">{idr_str}</td>'
                f'<td><span class="sl">&#9888; {it["stock"]}</span></td>'
                f'<td class="sk">{it["sku"]}</td>'
                f'<td><a href="{it["affiliate_url"]}" target="_blank" class="bb">&#128722; Buy</a></td>'
                f'<td><span class="nt" contenteditable="true" data-idx="{i}"'
                f' onblur="sn(this)">{it["notes"]}</span></td>'
                f'</tr>'
            )

    html_out = (
        "<!DOCTYPE html>\\n"
        '<html lang="en">\\n'
        "<head>\\n"
        '<meta charset="UTF-8">\\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\\n'
        "<title>HLJ Low-Stock Tracker</title>\\n"
        "<style>\\n"
        ":root{--bg:#0f0f13;--card:#1a1a24;--acc:#e85d04;--txt:#e0e0e0;"
        "--mu:#888;--bd:#2a2a3a;--gn:#2ecc71;--rd:#e74c3c;--pu:#9b8dff}\\n"
        "*{box-sizing:border-box;margin:0;padding:0}\\n"
        "body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',sans-serif;padding:20px}\\n"
        "header{display:flex;align-items:center;justify-content:space-between;"
        "margin-bottom:20px;flex-wrap:wrap;gap:10px}\\n"
        ".ttl{font-size:1.35rem;font-weight:700;color:var(--acc)}\\n"
        ".meta{font-size:.78rem;color:var(--mu);margin-top:3px}\\n"
        ".bdg{background:var(--acc);color:#fff;padding:4px 14px;border-radius:20px;"
        "font-size:.82rem;font-weight:700}\\n"
        ".bar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}\\n"
        "button{padding:7px 16px;border:none;border-radius:6px;cursor:pointer;"
        "font-size:.82rem;font-weight:600;transition:opacity .2s}\\n"
        "button:hover{opacity:.8}\\n"
        ".bcsv{background:#27ae60;color:#fff}.bref{background:#2980b9;color:#fff}"
        ".bclr{background:#555;color:#fff}\\n"
        ".fi{background:var(--card);border:1px solid var(--bd);color:var(--txt);"
        "padding:6px 11px;border-radius:6px;font-size:.82rem;width:220px}\\n"
        ".wrap{overflow-x:auto;border-radius:8px;border:1px solid var(--bd)}\\n"
        "table{width:100%;border-collapse:collapse}\\n"
        "thead th{background:#13131e;color:var(--acc);font-size:.74rem;text-transform:uppercase;"
        "letter-spacing:.05em;padding:11px 9px;text-align:left;white-space:nowrap;"
        "border-bottom:2px solid var(--bd);cursor:pointer;user-select:none}\\n"
        "thead th:hover{color:#fff}\\n"
        "tbody tr{border-bottom:1px solid var(--bd);transition:background .12s}\\n"
        "tbody tr:hover{background:rgba(232,93,4,.06)}\\n"
        "td{padding:9px 8px;font-size:.83rem;vertical-align:middle}\\n"
        ".th{width:60px;height:60px;object-fit:contain;border-radius:4px;background:#1f1f2e}\\n"
        ".nc{min-width:190px;max-width:270px}.nc a{color:#a0c4ff;text-decoration:none;font-weight:500}\\n"
        ".nc a:hover{text-decoration:underline}\\n"
        ".gr{background:#2a2a3a;color:var(--pu);padding:3px 7px;border-radius:4px;"
        "font-size:.75rem;font-weight:600;white-space:nowrap}\\n"
        ".mu{color:var(--mu)}.ph{color:var(--gn);font-weight:700}\\n"
        ".sk{font-family:monospace;font-size:.76rem;color:var(--mu)}\\n"
        ".sl{background:rgba(231,76,60,.15);color:var(--rd);padding:3px 7px;border-radius:4px;"
        "font-size:.78rem;font-weight:600;white-space:nowrap}\\n"
        ".bb{background:var(--acc);color:#fff;padding:4px 10px;border-radius:5px;"
        "text-decoration:none;font-size:.78rem;font-weight:600;white-space:nowrap}\\n"
        ".bb:hover{opacity:.85}\\n"
        ".nt{display:block;min-width:130px;min-height:26px;padding:3px 7px;"
        "background:rgba(255,255,255,.04);border:1px dashed var(--bd);"
        "border-radius:4px;color:var(--txt);font-size:.78rem;outline:none}\\n"
        ".nt:focus{border-color:var(--acc);background:rgba(232,93,4,.07)}\\n"
        ".nt.ok{border-color:var(--gn)!important}\\n"
        "footer{margin-top:18px;color:var(--mu);font-size:.74rem;text-align:center}\\n"
        "</style>\\n"
        "</head>\\n"
        "<body>\\n"
        "<header>\\n"
        "  <div>\\n"
        f'    <div class="ttl">&#9888;&#65039; HLJ Gundam Low-Stock Tracker</div>\\n'
        f'    <div class="meta">Scraped: {ts} &nbsp;&middot;&nbsp; '
        f'Filter: Only 1 to Only {LOW_STOCK_THRESHOLD} left</div>\\n'
        "  </div>\\n"
        f'  <span class="bdg">{count} item{"s" if count!=1 else ""} found</span>\\n'
        "</header>\\n"
        '<div class="bar">\\n'
        '  <button class="bcsv" onclick="exportCSV()">&#11015; Export CSV</button>\\n'
        '  <button class="bref" onclick="location.reload()">&#128260; Refresh Page</button>\\n'
        '  <button class="bclr" onclick="clearNotes()">&#128465; Clear Notes</button>\\n'
        '  <input class="fi" id="fi" type="text" '
        'placeholder="Search name, SKU, grade&hellip;" oninput="ft()">\\n'
        '  <label style="font-size:.8rem;color:var(--mu)">'
        '<input type="checkbox" id="cn" onchange="ft()"> Has notes</label>\\n'
        "</div>\\n"
        '<div class="wrap">\\n'
        '  <table id="t">\\n'
        "    <thead><tr>\\n"
        "      <th>IMG</th>\\n"
        '      <th onclick="st(1)">Name &#8597;</th>\\n'
        '      <th onclick="st(2)">Grade &#8597;</th>\\n'
        '      <th onclick="st(3)">JPY &#8597;</th>\\n'
        '      <th onclick="st(4)">PHP &#8597;</th>\\n'
        '      <th onclick="st(5)">SGD &#8597;</th>\\n'
        '      <th onclick="st(6)">USD &#8597;</th>\\n'
        '      <th onclick="st(7)">MYR &#8597;</th>\\n'
        '      <th onclick="st(8)">THB &#8597;</th>\\n'
        '      <th onclick="st(9)">IDR &#8597;</th>\\n'
        '      <th onclick="st(10)">Stock &#8597;</th>\\n'
        "      <th>SKU</th><th>Link</th><th>Notes (click to edit)</th>\\n"
        "    </tr></thead>\\n"
        f'    <tbody id="tb">{rows}</tbody>\\n'
        "  </table>\\n"
        "</div>\\n"
        "<footer>HLJ Low-Stock Tracker &nbsp;&middot;&nbsp; "
        "Notes auto-saved to localStorage &nbsp;&middot;&nbsp; "
        "Re-run script to refresh live data</footer>\\n"
        "<script>\\n"
        'const SK="hlj_ls_notes";\\n'
        f"const DATA={data_json_str};\\n"
        "function restoreNotes(){\\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\\n"
        "  document.querySelectorAll('.nt').forEach(e=>{\\n"
        "    if(s[e.dataset.idx]!==undefined)e.textContent=s[e.dataset.idx];\\n"
        "  });\\n"
        "}\\n"
        "function sn(e){\\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\\n"
        "  s[e.dataset.idx]=e.textContent.trim();\\n"
        "  localStorage.setItem(SK,JSON.stringify(s));\\n"
        "  e.classList.add('ok');setTimeout(()=>e.classList.remove('ok'),700);\\n"
        "}\\n"
        "function clearNotes(){\\n"
        "  if(!confirm('Clear all notes?'))return;\\n"
        "  localStorage.removeItem(SK);\\n"
        "  document.querySelectorAll('.nt').forEach(e=>e.textContent='');\\n"
        "}\\n"
        "function ft(){\\n"
        "  const q=document.getElementById('fi').value.toLowerCase();\\n"
        "  const cn=document.getElementById('cn').checked;\\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\\n"
        "  document.querySelectorAll('#tb tr').forEach(r=>{\\n"
        "    const has=s[r.dataset.idx]&&s[r.dataset.idx].trim();\\n"
        "    r.style.display=(!q||r.textContent.toLowerCase().includes(q))&&(!cn||has)?'':'none';\\n"
        "  });\\n"
        "}\\n"
        "function st(c){\\n"
        "  const tb=document.getElementById('tb');\\n"
        "  const rows=[...tb.querySelectorAll('tr[data-idx]')];\\n"
        "  const asc=tb.dataset.sc==c&&tb.dataset.sd=='a';\\n"
        "  tb.dataset.sc=c;tb.dataset.sd=asc?'d':'a';\\n"
        "  rows.sort((a,b)=>{\\n"
        "    const at=a.cells[c]?.textContent.trim()||'',bt=b.cells[c]?.textContent.trim()||'';\\n"
        "    const an=parseFloat(at.replace(/[^\\\\d.]/g,'')),bn=parseFloat(bt.replace(/[^\\\\d.]/g,''));\\n"
        "    if(!isNaN(an)&&!isNaN(bn))return asc?bn-an:an-bn;\\n"
        "    return asc?bt.localeCompare(at):at.localeCompare(bt);\\n"
        "  });\\n"
        "  rows.forEach(r=>tb.appendChild(r));\\n"
        "}\\n"
        "function exportCSV(){\\n"
        '  const s=JSON.parse(localStorage.getItem(SK)||"{}");\\n'     
        '  const f=["name","grade_scale","price_jpy","price_php","price_sgd","price_usd","price_myr","price_thb","price_idr","stock",'
        '"sku","image_url","image_urls","affiliate_url","scraped_at","notes"];\\n'                       
        '  const lines=[f.join(",")];\\n'
        "  DATA.forEach((it,i)=>{\\n"
        "    it.notes=s[i]||it.notes||'';\\n"        
        '    lines.push(f.map(k => "\\"" + String(Array.isArray(it[k]) ? JSON.stringify(it[k]) : (it[k] ?? "")).replace(/"/g, \'""\') + "\\"").join(","));\\n'
        "  });\\n"
        "  const a=document.createElement('a');\\n"
        "  a.href=URL.createObjectURL(new Blob([lines.join('\\\\n')],"
        "{type:'text/csv;charset=utf-8;'}));\\n"
        "  a.download='low_stock_export.csv';a.click();\\n"
        "}\\n"
        "restoreNotes();\\n"
        "</script>\\n"
        "</body></html>\\n"
    )

    out.write_text(html_out, encoding="utf-8")
    print(f"  [HTML]  -> {out}")
    return out


# ── Save All ──────────────────────────────────────────────────────────────────
def save_outputs(items: list) -> None:
    print(f"\nSaving {len(items)} items to 3 files...")
    save_json(items)
    save_csv(items)
    save_html(items)
    print("\nDone! Open low_stock.html in your browser.")


# ── Entry Point ───────────────────────────────────────────────────────────────
async def main():
    items = await scrape_low_stock()
    save_outputs(items)
    return items


if __name__ == "__main__":
    asyncio.run(main())
