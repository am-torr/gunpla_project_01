#!/usr/bin/env python3
"""
scripts/hlj_lowstock_tracker.py
================================
HLJ Low-Stock Tracker — scrapes In Stock items with "Only X left" stock status.
Depends on: app/hlj_helpers.py

Outputs (to scripts/ folder):
  low_stock.json / low_stock.csv
"""
import asyncio
import json
import csv
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from playwright_stealth import stealth_async

from app.hlj_helpers import (
    HLJSelectors, HLJ_BASE, SCRAPE_DELAY, OUTPUT_DIR, PHT,
    fetch_rates, parse_currency_price, fmt_jpy, apply_rates,
    build_affiliate_url, extract_grade_scale, is_gunpla,
    get_detail_images, BROWSER_ARGS, CONTEXT_ARGS,
)

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPE_URL          = f"{HLJ_BASE}/search/?Word=gundam&StockLevel=In%C2%A0Stock"
LOW_STOCK_THRESHOLD = 5
MAX_PAGES           = 14
FIELDS = [
    "name","grade_scale","price_jpy","price_php","price_sgd","price_usd",
    "price_myr","price_thb","price_idr","stock","sku",
    "image_url","image_urls","affiliate_url","scraped_at","notes"
]

# ── Core scraper ──────────────────────────────────────────────────────────────
async def scrape_low_stock(threshold: int = None) -> list:
    thresh = threshold if threshold is not None else LOW_STOCK_THRESHOLD
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f" HLJ LOW-STOCK TRACKER | {ts}")
    print(f"{'='*64}")
    print(f" URL       : {SCRAPE_URL}")
    print(f" Threshold : only ≤{thresh} left | Pages: {MAX_PAGES}")
    print(f"{'='*64}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(**CONTEXT_ARGS)
        page    = await context.new_page()
        await stealth_async(page)
        await asyncio.sleep(2)

        print(">> Fetching live exchange rates...")
        rates      = fetch_rates()
        low_stock  = []
        global_idx = 0

        for page_num in range(1, MAX_PAGES + 1):
            page_url = f"{SCRAPE_URL}&Page={page_num}"
            print(f"\n>> Page {page_num}/{MAX_PAGES}: {page_url}")
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector(HLJSelectors.PRICE_LOADED, timeout=8000)
            except Exception:
                print("  WARN: No prices — continuing with static HTML")
            try:
                await page.wait_for_selector(HLJSelectors.STOCK_STATUS, timeout=5000)
            except Exception:
                await asyncio.sleep(2)

            html  = await page.content()
            soup  = BeautifulSoup(html, "html.parser")
            cards = soup.select(HLJSelectors.PRODUCT_CARD)
            if not cards:
                print(f"  No cards on page {page_num} — stopping.")
                break
            print(f"\n[+] Page {page_num}: {len(cards)} products found\n")

            for card in cards:
                global_idx += 1
                idx = global_idx
                try:
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
                            if d: stock = d.get_text(strip=True)
                        if stock == "Unknown":
                            fb = card.select_one(HLJSelectors.STOCK_STATUS)
                            stock = fb.text.strip() if fb else "Unknown"

                    img_el  = card.select_one(HLJSelectors.PRODUCT_IMAGE)
                    img_src = img_el.get("src","") if img_el else ""
                    img_url = f"https:{img_src}" if img_src.startswith("//") else img_src

                    if not is_gunpla(name, sku):
                        print(f"  [{idx:04d}] SKIP non-Gunpla: {name[:40]}")
                        continue

                    print(f"  [{idx:04d}] {name[:44]:<44} | {sku:<14} | {stock}")

                    qty_match = re.search(r"only (\d+) left", stock.lower())
                    if not qty_match or int(qty_match.group(1)) > thresh:
                        continue

                    print(f"  !!! LOW STOCK -> {name[:60]}")

                    needs_detail = not price_txt or ("¥" not in price_txt and "円" not in price_txt)
                    images = [img_url] if img_url else []
                    try:
                        detail_page = await browser.new_page()
                        await detail_page.goto(prod_url, wait_until="domcontentloaded", timeout=10000)
                        if needs_detail:
                            el = await detail_page.wait_for_selector(f"#{sku}_price:not(:empty)", timeout=3000)
                            fetched = await el.text_content()
                            price_txt = fetched.strip() if fetched else price_txt
                        images = await get_detail_images(detail_page, img_url)
                        await detail_page.close()
                        print(f"  Product price: {price_txt} | Images: {len(images)}")
                    except Exception as e:
                        print(f"  WARN product page: {e} — using list data")
                        images = [img_url] if img_url else []

                    value, curr = parse_currency_price(price_txt)
                    prices = apply_rates(value, curr, rates)

                    low_stock.append({
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
                    })
                    await asyncio.sleep(SCRAPE_DELAY)

                except Exception as e:
                    print(f"  WARN [{idx}]: {e}")
                    continue

        await browser.close()
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
        w.writeheader(); w.writerows(items)
    print(f"  [CSV]  -> {out}")
    return out

# ── CLI entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    items = asyncio.run(scrape_low_stock())
    save_json(items)
    save_csv(items)
    print("Done.")
