#!/usr/bin/env python3
"""
app/hlj_helpers.py
==================
Shared helpers for all HLJ scrapers.
Imported by:
  - scripts/hlj_lowstock_tracker.py
  - scripts/hlj_preorder_tracker.py
"""
import re
import os
import sys
import json
import requests
from pathlib import Path
from urllib.parse import urljoin
from datetime import timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Selectors ─────────────────────────────────────────────────────────────────
try:
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

# ── Constants ─────────────────────────────────────────────────────────────────
HLJ_BASE      = "https://www.hlj.com"
AFFILIATE_TAG = "utm_source=speedartug&utm_medium=affiliate"
SCRAPE_DELAY  = 1
OUTPUT_DIR    = Path(__file__).resolve().parent.parent / "scripts"
PHT           = timezone(timedelta(hours=8))

# ── Supabase exchange rates ───────────────────────────────────────────────────
SUPABASE_URL      = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
RATES_URL         = f"{SUPABASE_URL}/rest/v1/exchange_rates?base=eq.JPY&select=*&limit=1"

RATES_FALLBACK = {
    "php": 0.37, "sgd": 0.0095, "usd": 0.0067,
    "myr": 0.032, "thb": 0.24,  "idr": 108,
    "updated_at": "fallback"
}

def fetch_rates() -> dict:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("  WARN: No SUPABASE_URL/KEY — using hardcoded fallback")
        return RATES_FALLBACK
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
    try:
        resp = requests.get(RATES_URL, headers=headers, timeout=5)
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            row = {k: float(rows[0][k]) for k in ["php","sgd","usd","myr","thb","idr"]}
            row["updated_at"] = str(rows[0].get("updated_at","unknown"))[:16]
            print(f"  Rates: ₱{row['php']:.4f} S${row['sgd']:.4f} ${row['usd']:.4f} "
                  f"RM{row['myr']:.4f} ฿{row['thb']:.4f} IDR{row['idr']:.0f} ({row['updated_at']})")
            return row
        print("  WARN: No rates in Supabase — using fallback")
        return RATES_FALLBACK
    except Exception as e:
        print(f"  ERROR: Supabase rates fetch failed ({e}) — using fallback")
        return RATES_FALLBACK

# ── Price helpers ─────────────────────────────────────────────────────────────
def parse_currency_price(text: str):
    """Returns (value, currency_str) or (None, None)."""
    if not text:
        return None, None
    if "₱" in text:
        curr = "PHP"
    elif "¥" in text or "円" in text:
        curr = "JPY"
    elif "$" in text:
        curr = "USD"
    else:
        curr = "UNKNOWN"
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

def apply_rates(value, curr: str, rates: dict) -> dict:
    """Convert any currency to all others via JPY pivot."""
    price_jpy = price_php = price_sgd = price_usd = price_myr = price_thb = price_idr = None
    if value is None:
        return dict(price_jpy=None, price_php=None, price_sgd=None, price_usd=None,
                    price_myr=None, price_thb=None, price_idr=None)
    if curr == "JPY":    price_jpy = value
    elif curr == "PHP":  price_php = value; price_jpy = round(value / rates["php"], 0)
    elif curr == "USD":  price_usd = value; price_jpy = round(value / rates["usd"], 0)
    elif curr == "SGD":  price_sgd = value; price_jpy = round(value / rates["sgd"], 0)
    elif curr == "MYR":  price_myr = value; price_jpy = round(value / rates["myr"], 0)
    elif curr == "THB":  price_thb = value; price_jpy = round(value / rates["thb"], 0)
    elif curr == "IDR":  price_idr = value; price_jpy = round(value / rates["idr"], 0)
    else:                price_jpy = value
    if price_jpy is not None:
        if price_php is None: price_php = round(price_jpy * rates["php"], 2)
        if price_sgd is None: price_sgd = round(price_jpy * rates["sgd"], 2)
        if price_usd is None: price_usd = round(price_jpy * rates["usd"], 2)
        if price_myr is None: price_myr = round(price_jpy * rates["myr"], 2)
        if price_thb is None: price_thb = round(price_jpy * rates["thb"], 2)
        if price_idr is None: price_idr = round(price_jpy * rates["idr"], 0)
    return dict(price_jpy=price_jpy, price_php=price_php, price_sgd=price_sgd,
                price_usd=price_usd, price_myr=price_myr, price_thb=price_thb,
                price_idr=price_idr)

# ── URL helper ────────────────────────────────────────────────────────────────
def build_affiliate_url(product_url: str) -> str:
    base = product_url.split("?")[0]
    return f"{base}?{AFFILIATE_TAG}"

# ── Grade/scale parser ────────────────────────────────────────────────────────
def extract_grade_scale(name: str) -> str:
    FIXED = [
        (r"\bMGEX\b", "MGEX"), (r"\bMGSD\b", "MGSD"),
        (r"\bPG\b",   "PG 1/60"),  (r"\bMG\b",   "MG 1/100"),
        (r"\bRG\b",   "RG 1/144"), (r"\bEG\b",   "1/144 ENTRY GRADE"),
        (r"\bBB\b",   "SD BB"),    (r"\bSD\b",   "SD"),
    ]
    for pat, label in FIXED:
        if re.search(pat, name, re.I):
            scale = re.search(r"1/(\d+)", name)
            grade = label.split()[0]
            return f"{grade} 1/{scale.group(1)}" if scale else label
    hg = re.search(r"\bHG([A-Z]{0,6})\b", name, re.I)
    if hg:
        suffix = hg.group(1).upper()
        grade  = f"HG{suffix}" if suffix else "HG"
        scale  = re.search(r"1/(\d+)", name)
        return f"{grade} 1/{scale.group(1)}" if scale else f"{grade} 1/144"
    scale = re.search(r"1/(\d+)", name)
    return f"1/{scale.group(1)}" if scale else "Unknown"

# ── Gunpla filter ─────────────────────────────────────────────────────────────
NON_GUNPLA_SKU_PREFIXES = ("ABA","KBY","AZM","KPM","AZMP","HBJ","GNZ")
GRADE_PATTERNS = re.compile(r"\b(MGEX|MGSD|PG|MG|RG|EG|SD|BB|HG[A-Z]{0,6})\b", re.I)
SCALE_PATTERNS = re.compile(r"1/(144|100|60|48|35)", re.I)
MS_KEYWORDS = [
    "gundam","gunpla","zaku","rx-78","wing zero","strike freedom","unicorn",
    "nu gundam","sazabi","sinanju","barbatos","astray","exia","00 raiser",
    "freedom","justice","destiny","providence","impulse","infinite justice",
    "gelgoog","gouf","dom ","rick dom","gm ","ball ","jegan","rezel",
    "kshatriya","hyaku shiki",
]

def is_gunpla(name: str, sku: str) -> bool:
    if sku.upper().startswith(NON_GUNPLA_SKU_PREFIXES):
        return False
    name_lower = name.lower()
    return bool(
        GRADE_PATTERNS.search(name)
        or SCALE_PATTERNS.search(name)
        or any(kw in name_lower for kw in MS_KEYWORDS)
    )

# ── Detail page images ────────────────────────────────────────────────────────
async def get_detail_images(detail_page, img_url: str) -> list:
    def fix_url(u: str) -> str:
        if not u: return ""
        if u.startswith("//"): return "https:" + u
        return urljoin("https://www.hlj.com", u)
    images = []
    try:
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
        if not images:
            scripts = await detail_page.query_selector_all('script[type="application/ld+json"]')
            for s in scripts:
                txt = await s.text_content()
                if not txt: continue
                try:
                    data = json.loads(txt)
                    if isinstance(data, dict) and data.get("image"):
                        main_img = fix_url(data["image"])
                        if main_img and main_img not in images:
                            images.append(main_img)
                        break
                except Exception:
                    continue
        if not images and img_url and "noImage" not in img_url:
            images = [img_url]
    except Exception as e:
        print(f"  WARN get_detail_images: {e}")
        if img_url and "noImage" not in img_url:
            images = [img_url]
    print(f"  Images found: {len(images)}")
    return images[:3]

# ── Shared Playwright launch args ─────────────────────────────────────────────
BROWSER_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars", "--window-size=1920,1080",
    "--ignore-certificate-errors",
]
CONTEXT_ARGS = dict(
    viewport={"width": 1920, "height": 1080},
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    locale="en-US",
    timezone_id="Asia/Manila",
    ignore_https_errors=True,
    extra_http_headers={
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
)
