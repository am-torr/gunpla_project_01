#!/usr/bin/env python3
"""
scripts/hlj-lowstock/hlj_lowstock_tracker.py
============================================
HLJ Low-Stock Tracker — scrapes In Stock items with "Only X left" stock status.
Depends on: scripts/app/hlj_helpers.py (shared with hlj-preorder).

Outputs (to this script's folder):
  low_stock.json / low_stock.csv
"""
import asyncio
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Make scripts/ importable so `app.hlj_helpers` resolves to scripts/app/hlj_helpers.py
_HERE = Path(__file__).resolve().parent
_SCRIPTS_ROOT = _HERE.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

from app.hlj_helpers import (
    BROWSER_ARGS, CONTEXT_ARGS, HLJ_BASE, HLJSelectors, PHT, SCRAPE_DELAY,
    apply_rates, build_affiliate_url, extract_grade_scale, fetch_rates,
    fmt_jpy, get_detail_images, is_gunpla, parse_currency_price,
)

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPE_URL          = f"{HLJ_BASE}/search/?Word=gundam&StockLevel=In%C2%A0Stock"
LOW_STOCK_THRESHOLD = 5
MAX_PAGES           = 14
PAGE_CONCURRENCY    = 3       # listing pages walked in parallel; tune for HLJ politeness
OUTPUT_DIR          = _HERE
FIELDS = [
    "name","grade_scale","price_jpy","price_php","price_sgd","price_usd",
    "price_myr","price_thb","price_idr","stock","sku",
    "image_url","image_urls","affiliate_url","scraped_at","notes"
]


async def _scrape_card(card, detail_page, rates, thresh, idx):
    """Extract one product card; return item dict or None if filtered out."""
    name_el   = card.select_one(HLJSelectors.PRODUCT_NAME)
    name      = name_el.text.strip() if name_el else "Unknown"
    href      = name_el.get("href", "") if name_el else ""
    prod_url  = f"{HLJ_BASE}{href}" if href else SCRAPE_URL

    price_el  = card.select_one(HLJSelectors.PRODUCT_PRICE)
    price_txt = price_el.text.strip() if price_el else ""
    sku       = price_el["id"].replace("_price","") if price_el and price_el.get("id") else "Unknown"

    order_stop = card.find(string=re.compile(r"Order Stop|Notify Me", re.I))
    if order_stop:
        stock = "ORDER_STOP"
    else:
        stock = "Unknown"
        if sku != "Unknown":
            d = card.select_one(f"div#{sku}_stockStatusDetail")
            if d:
                stock = d.get_text(strip=True)
        if stock == "Unknown":
            fb = card.select_one(HLJSelectors.STOCK_STATUS)
            stock = fb.text.strip() if fb else "Unknown"

    img_el  = card.select_one(HLJSelectors.PRODUCT_IMAGE)
    img_src = img_el.get("src","") if img_el else ""
    img_url = f"https:{img_src}" if img_src.startswith("//") else img_src

    if not is_gunpla(name, sku):
        print(f"  [{idx:04d}] SKIP non-Gunpla: {name[:40]}")
        return None

    print(f"  [{idx:04d}] {name[:44]:<44} | {sku:<14} | {stock}")

    qty_match = re.search(r"only (\d+) left", stock.lower())
    if not qty_match or int(qty_match.group(1)) > thresh:
        return None

    print(f"  !!! LOW STOCK -> {name[:60]}")

    needs_detail = not price_txt or ("¥" not in price_txt and "円" not in price_txt)
    images = [img_url] if img_url else []
    try:
        await detail_page.goto(prod_url, wait_until="domcontentloaded", timeout=10000)
        if needs_detail:
            el = await detail_page.wait_for_selector(f"#{sku}_price:not(:empty)", timeout=3000)
            fetched = await el.text_content()
            price_txt = fetched.strip() if fetched else price_txt
        images = await get_detail_images(detail_page, img_url)
        print(f"  Product price: {price_txt} | Images: {len(images)}")
    except Exception as e:
        print(f"  WARN product page: {e} — using list data")
        images = [img_url] if img_url else []

    value, curr = parse_currency_price(price_txt)
    prices = apply_rates(value, curr, rates)

    return {
        "name":          name,
        "grade_scale":   extract_grade_scale(name),
        "price_jpy":     fmt_jpy(prices["price_jpy"]),
        "price_php":     prices["price_php"],
        "price_sgd":     prices["price_sgd"],
        "price_usd":     prices["price_usd"],
        "price_myr":     prices["price_myr"],
        "price_thb":     prices["price_thb"],
        "price_idr":     prices["price_idr"],
        "stock":         stock,
        "sku":           sku,
        "image_url":     images[0] if images else img_url,
        "image_urls":    images if images else ([img_url] if img_url else []),
        "affiliate_url": build_affiliate_url(prod_url),
        "scraped_at":    datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "notes":         ""
    }


async def _scrape_page(context, page_num, rates, thresh, sem, counter):
    """Walk one listing page concurrently. Owns its own listing+detail Pages."""
    async with sem:
        page         = await context.new_page()
        detail_page  = await context.new_page()
        await stealth_async(page)
        try:
            page_url = f"{SCRAPE_URL}&Page={page_num}"
            print(f"\n>> Page {page_num}/{MAX_PAGES}: {page_url}")
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector(HLJSelectors.PRICE_LOADED, timeout=8000)
            except Exception:
                print(f"  WARN page {page_num}: No prices — continuing with static HTML")
            try:
                await page.wait_for_selector(HLJSelectors.STOCK_STATUS, timeout=5000)
            except Exception:
                await asyncio.sleep(2)

            html  = await page.content()
            soup  = BeautifulSoup(html, "html.parser")
            cards = soup.select(HLJSelectors.PRODUCT_CARD)
            if not cards:
                print(f"  Page {page_num}: no cards.")
                return page_num, []

            print(f"\n[+] Page {page_num}: {len(cards)} products found\n")
            items = []
            for card in cards:
                counter[0] += 1
                idx = counter[0]
                try:
                    item = await _scrape_card(card, detail_page, rates, thresh, idx)
                    if item:
                        items.append(item)
                    await asyncio.sleep(SCRAPE_DELAY)
                except Exception as e:
                    print(f"  WARN [{idx}]: {e}")
                    continue
            return page_num, items
        finally:
            await detail_page.close()
            await page.close()


# ── Core scraper ──────────────────────────────────────────────────────────────
async def scrape_low_stock(threshold: int = None) -> list:
    thresh = threshold if threshold is not None else LOW_STOCK_THRESHOLD
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f" HLJ LOW-STOCK TRACKER | {ts}")
    print(f"{'='*64}")
    print(f" URL         : {SCRAPE_URL}")
    print(f" Threshold   : only <={thresh} left | Pages: {MAX_PAGES}")
    print(f" Concurrency : {PAGE_CONCURRENCY} listing pages in parallel")
    print(f"{'='*64}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(**CONTEXT_ARGS)

        print(">> Fetching live exchange rates...")
        rates = fetch_rates()

        sem     = asyncio.Semaphore(PAGE_CONCURRENCY)
        counter = [0]  # mutable shared index for log readability
        tasks   = [_scrape_page(context, p, rates, thresh, sem, counter)
                   for p in range(1, MAX_PAGES + 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        await browser.close()

    # Drop exceptions, merge in page order for deterministic output.
    page_buckets = []
    for r in results:
        if isinstance(r, Exception):
            print(f"  WARN page task failed: {r}")
            continue
        page_buckets.append(r)
    page_buckets.sort(key=lambda r: r[0])
    low_stock = [item for _, items in page_buckets for item in items]

    print(f"\n{'='*64}")
    print(f" RESULT: {len(low_stock)} low-stock items found")
    print(f"{'='*64}\n")
    return low_stock


# ── Save helpers ──────────────────────────────────────────────────────────────
def save_json(items: list) -> Path:
    out = OUTPUT_DIR / "low_stock.json"
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [JSON] -> {out}")
    return out


def save_csv(items: list) -> Path:
    out = OUTPUT_DIR / "low_stock.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    print(f"  [CSV]  -> {out}")
    return out


# ── CLI entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    items = asyncio.run(scrape_low_stock())
    save_json(items)
    save_csv(items)
    print("Done.")
