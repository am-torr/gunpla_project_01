#!/usr/bin/env python3
"""
scripts/hlj_preorder_tracker.py
================================
HLJ Preorder Tracker — scrapes All Future Release items.
Badge pattern (confirmed by Comet): "July Release", "Aug Release", etc.
Release date and cancellation deadline are extracted from the detail page Details list.
Depends on: app/hlj_helpers.py

Outputs (to scripts/ folder):
  preorders.json / preorders.csv
"""
import asyncio
import json
import csv
import re
from datetime import datetime

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from playwright_stealth import stealth_async

from scripts.app.hlj_helpers import (
    HLJSelectors, HLJ_BASE, SCRAPE_DELAY, OUTPUT_DIR, PHT,
    fetch_rates, parse_currency_price, fmt_jpy, apply_rates,
    build_affiliate_url, extract_grade_scale, is_gunpla,
    get_detail_images, BROWSER_ARGS, CONTEXT_ARGS,
)

PREORDER_URL    = f"{HLJ_BASE}/search/?Word=gundam&StockLevel=All+Future+Release&Sort=std+desc"
MAX_PAGES       = 20
PREORDER_FIELDS = [
    "name","grade_scale","price_jpy","price_php","price_sgd","price_usd",
    "price_myr","price_thb","price_idr","stock","release_date","cancellation_deadline","sku",
    "image_url","image_urls","affiliate_url","scraped_at","notes"
]

RELEASE_BADGE_RE = re.compile(
    r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\w*\s+release\b",
    re.I
)

async def scrape_preorders(max_pages: int = MAX_PAGES) -> list:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f" HLJ PREORDER TRACKER | {ts}")
    print(f"{'='*64}")
    print(f" URL   : {PREORDER_URL}")
    print(f" Pages : {max_pages}")
    print(f"{'='*64}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(**CONTEXT_ARGS)
        page = await context.new_page()
        await stealth_async(page)
        await asyncio.sleep(2)

        print(">> Fetching live exchange rates...")
        rates = fetch_rates()
        preorders = []
        global_idx = 0

        for page_num in range(1, max_pages + 1):
            page_url = f"{PREORDER_URL}&Page={page_num}"
            print(f"\n>> Page {page_num}/{max_pages}: {page_url}")
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector(HLJSelectors.PRICE_LOADED, timeout=8000)
            except Exception:
                print("  WARN: No prices — continuing with static HTML")
            try:
                await page.wait_for_selector("[id$='_stock']", timeout=5000)
            except Exception:
                await asyncio.sleep(2)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(HLJSelectors.PRODUCT_CARD)
            if not cards:
                print(f"  No cards on page {page_num} — stopping.")
                break
            print(f"\n[+] Page {page_num}: {len(cards)} products found\n")

            for card in cards:
                global_idx += 1
                idx = global_idx
                try:
                    name_el = card.select_one(HLJSelectors.PRODUCT_NAME)
                    name = name_el.text.strip() if name_el else "Unknown"
                    href = name_el.get("href", "") if name_el else ""
                    prod_url = f"{HLJ_BASE}{href}" if href else PREORDER_URL

                    price_el = card.select_one(HLJSelectors.PRODUCT_PRICE)
                    price_txt = price_el.text.strip() if price_el else ""
                    sku = price_el["id"].replace("_price", "") if price_el and price_el.get("id") else "Unknown"

                    badge_text = ""
                    if sku != "Unknown":
                        stock_box = card.select_one(f"#{sku}_stock")
                        badge_text = stock_box.get_text(" ", strip=True) if stock_box else ""
                    if not badge_text:
                        d = card.select_one(f"div#{sku}_stockStatusDetail")
                        badge_text = d.get_text(" ", strip=True) if d else ""

                    print(f"  [{idx:04d}] {name[:44]:<44} | {sku:<14} | '{badge_text}'")

                    if not RELEASE_BADGE_RE.search(badge_text):
                        continue
                    if not is_gunpla(name, sku):
                        print(f"  [{idx:04d}] SKIP non-Gunpla: {name[:40]}")
                        continue

                    print(f"  !!! PREORDER -> {name[:60]} | {badge_text}")

                    img_el = card.select_one(HLJSelectors.PRODUCT_IMAGE)
                    img_src = img_el.get("src", "") if img_el else ""
                    img_url = f"https:{img_src}" if img_src.startswith("//") else img_src

                    images = [img_url] if img_url else []
                    release_date = badge_text
                    cancellation_deadline = ""

                    try:
                        detail_page = await browser.new_page()
                        await detail_page.goto(prod_url, wait_until="domcontentloaded", timeout=12000)

                        try:
                            el = await detail_page.query_selector("//li[starts-with(normalize-space(.), 'Release Date:')]")
                            if el:
                                raw = (await el.inner_text() or "").strip()
                                release_date = raw.replace("Release Date:", "").strip()
                        except Exception as e:
                            print(f"    WARN release_date: {e}")

                        try:
                            el = await detail_page.query_selector("//li[starts-with(normalize-space(.), 'Cancellation Deadline:')]")
                            if el:
                                raw = (await el.inner_text() or "").strip()
                                cancellation_deadline = raw.replace("Cancellation Deadline:", "").strip()
                        except Exception as e:
                            print(f"    WARN cancellation_deadline: {e}")

                        needs_detail = not price_txt or ("¥" not in price_txt and "円" not in price_txt)
                        if needs_detail:
                            try:
                                el2 = await detail_page.wait_for_selector(f"#{sku}_price:not(:empty)", timeout=3000)
                                fetched = await el2.text_content()
                                price_txt = fetched.strip() if fetched else price_txt
                            except Exception:
                                pass

                        images = await get_detail_images(detail_page, img_url)
                        await detail_page.close()
                        print(f"    Release: {release_date} | Images: {len(images)}")

                    except Exception as e:
                        print(f"    WARN detail page: {e} — using defaults")

                    value, curr = parse_currency_price(price_txt)
                    prices = apply_rates(value, curr, rates)

                    preorders.append({
                        "name": name,
                        "grade_scale": extract_grade_scale(name),
                        "price_jpy": fmt_jpy(prices["price_jpy"]),
                        "price_php": prices["price_php"],
                        "price_sgd": prices["price_sgd"],
                        "price_usd": prices["price_usd"],
                        "price_myr": prices["price_myr"],
                        "price_thb": prices["price_thb"],
                        "price_idr": prices["price_idr"],
                        "stock": badge_text,
                        "release_date": release_date,
                        "cancellation_deadline": cancellation_deadline,
                        "sku": sku,
                        "image_url": images[0] if images else img_url,
                        "image_urls": images if images else ([img_url] if img_url else []),
                        "affiliate_url": build_affiliate_url(prod_url),
                        "scraped_at": datetime.now(PHT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                        "notes": ""
                    })
                    await asyncio.sleep(SCRAPE_DELAY)

                except Exception as e:
                    print(f"  WARN [{idx}]: {e}")
                    continue

        await browser.close()
    print(f"\n{'='*64}")
    print(f" RESULT: {len(preorders)} preorder items found")
    print(f"{'='*64}\n")
    return preorders


def save_json(items: list) -> Path:
    out = OUTPUT_DIR / "preorders.json"
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [JSON] -> {out}")
    return out


def save_csv(items: list) -> Path:
    out = OUTPUT_DIR / "preorders.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=PREORDER_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    print(f"  [CSV]  -> {out}")
    return out


if __name__ == "__main__":
    items = asyncio.run(scrape_preorders())
    save_json(items)
    save_csv(items)
    print("Done.")
