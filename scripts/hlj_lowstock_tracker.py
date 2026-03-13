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
from datetime import datetime
from pathlib import Path

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

# ── Config ────────────────────────────────────────────────────────────────────
HLJ_BASE      = "https://www.hlj.com"
SCRAPE_URL    = f"{HLJ_BASE}/search/?GenreCode2=Gundam&StockLevel=In+Stock"
AFFILIATE_TAG = "utm_source=speedartug&utm_medium=affiliate"
JPY_TO_PHP    = 0.37
SCRAPE_DELAY  = 3        # seconds – respectful crawling
LIMIT         = 50
LOW_STOCK_KW  = ["only 1", "only 2"]
OUTPUT_DIR    = Path(__file__).resolve().parent

FIELDS = ["name","grade_scale","price_jpy","price_php",
          "stock","sku","image_url","affiliate_url","scraped_at","notes"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_price(text: str):
    """Mirrors base_scraper.py parse_price()."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def fmt_jpy(price) -> str:
    return f"\u00a5{price:,.0f}" if price else "N/A"


def build_affiliate_url(product_url: str) -> str:
    base = product_url.split("?")[0]
    return f"{base}?{AFFILIATE_TAG}"


def extract_grade_scale(name: str) -> str:
    """Best-effort grade/scale parsed from product name."""
    checks = [
        (r"\bMGEX\b",  "MGEX"),
        (r"\bMGSD\b",  "MGSD"),
        (r"\bPG\b",    "PG 1/60"),
        (r"\bMG\b",    "MG 1/100"),
        (r"\bRG\b",    "RG 1/144"),
        (r"\bHGUC\b",  "HGUC 1/144"),
        (r"\bHGCE\b",  "HGCE 1/144"),
        (r"\bHGIBO\b", "HGIBO 1/144"),
        (r"\bHGAC\b",  "HGAC 1/144"),
        (r"\bHG\b",    "HG 1/144"),
        (r"\bEG\b",    "EG 1/144"),
        (r"\bSD\b",    "SD"),
    ]
    for pat, label in checks:
        if re.search(pat, name, re.I):
            scale = re.search(r"1/(\d+)", name)
            if scale:
                grade = label.split()[0]
                return f"{grade} 1/{scale.group(1)}"
            return label
    scale = re.search(r"1/(\d+)", name)
    return f"1/{scale.group(1)}" if scale else "Unknown"


# ── Core Scraper ──────────────────────────────────────────────────────────────
async def scrape_low_stock() -> list:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*64}")
    print(f"  HLJ LOW-STOCK TRACKER  |  {ts}")
    print(f"{'='*64}")
    print(f"  URL    : {SCRAPE_URL}")
    print(f"  Limit  : {LIMIT}  |  Filter : {LOW_STOCK_KW}")
    print(f"  Delay  : {SCRAPE_DELAY}s  |  JPY->PHP: {JPY_TO_PHP}")
    print(f"{'='*64}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()

        print(">> Loading HLJ Gundam in-stock page...")
        await page.goto(SCRAPE_URL, wait_until="networkidle")

        print(">> Waiting for price elements...")
        try:
            await page.wait_for_selector(HLJSelectors.PRICE_LOADED, timeout=20000)
        except Exception:
            print("   WARN: Timeout waiting for prices, continuing anyway")
        await asyncio.sleep(2)

        html  = await page.content()
        soup  = BeautifulSoup(html, "html.parser")
        cards = soup.select(HLJSelectors.PRODUCT_CARD)
        total = len(cards)
        proc  = min(total, LIMIT)

        print(f"\n[+] {total} products found -> checking top {proc}\n")

        low_stock = []

        for idx, card in enumerate(cards[:proc], 1):
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

                # Stock detection — exact logic from hobby_link_japan.py
                # Step 1: ORDER_STOP check
                order_stop = card.find(string=re.compile(r"Order Stop|Notify Me", re.I))
                if order_stop:
                    stock = "ORDER_STOP"
                    print(f"  BLOCKED SKU:{sku}")
                else:
                    stock = "Unknown"
                    # Step 2: Granular div #{sku}_stockStatusDetail
                    if sku != "Unknown":
                        detail_div = card.select_one(f"div#{sku}_stockStatusDetail")
                        if detail_div:
                            stock = detail_div.get_text(strip=True)
                    # Step 3: Fallback to generic selector
                    if stock == "Unknown":
                        fb = card.select_one(HLJSelectors.STOCK_STATUS)
                        stock = fb.text.strip() if fb else "Unknown"

                # Image
                img_el  = card.select_one(HLJSelectors.PRODUCT_IMAGE)
                img_src = img_el.get("src", "") if img_el else ""
                img_url = f"https:{img_src}" if img_src.startswith("//") else img_src

                print(f"  [{idx:02d}/{proc}] {name[:44]:<44} | {sku:<14} | {stock}")

                # LOW-STOCK FILTER
                if not any(kw in stock.lower() for kw in LOW_STOCK_KW):
                    continue

                print(f"  !!! LOW STOCK -> {name[:60]}")

                # Price conversion
                price_jpy = parse_price(price_txt)
                price_php = round(price_jpy * JPY_TO_PHP, 2) if price_jpy else None

                low_stock.append({
                    "name":          name,
                    "grade_scale":   extract_grade_scale(name),
                    "price_jpy":     fmt_jpy(price_jpy),
                    "price_php":     price_php,
                    "stock":         stock,
                    "sku":           sku,
                    "image_url":     img_url,
                    "affiliate_url": build_affiliate_url(prod_url),
                    "scraped_at":    datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "notes":         ""
                })

                await asyncio.sleep(SCRAPE_DELAY)   # 3s respectful delay

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
    with open(out, "w", newline="", encoding="utf-8-sig") as f:   # BOM for Excel
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

    # Embed full data as JSON for in-page CSV export
    data_json_str = json.dumps(items, ensure_ascii=False)

    # Table rows
    rows = ""
    if not items:
        rows = ('<tr><td colspan="9" style="text-align:center;padding:40px;color:#888">'
                "No low-stock items found. Re-run script to refresh.</td></tr>")
    else:
        for i, it in enumerate(items):
            php_str = (f"&#8369;{it['price_php']:,.2f}"
                       if it["price_php"] else "N/A")
            img_tag = (f'<img src="{it["image_url"]}" alt="" class="th">'
                       if it["image_url"] else "&mdash;")
            rows += (
                f'<tr data-idx="{i}">'
                f'<td>{img_tag}</td>'
                f'<td class="nc"><a href="{it["affiliate_url"]}" target="_blank">{it["name"]}</a></td>'
                f'<td><span class="gr">{it["grade_scale"]}</span></td>'
                f'<td class="mu">{it["price_jpy"]}</td>'
                f'<td class="ph">{php_str}</td>'
                f'<td><span class="sl">&#9888; {it["stock"]}</span></td>'
                f'<td class="sk">{it["sku"]}</td>'
                f'<td><a href="{it["affiliate_url"]}" target="_blank" class="bb">&#128722; Buy</a></td>'
                f'<td><span class="nt" contenteditable="true" data-idx="{i}"'
                f' onblur="sn(this)">{it["notes"]}</span></td>'
                f'</tr>'
            )

    # NOTE: JS curly braces inside the f-string are doubled {{ }} to escape them.
    html_out = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>HLJ Low-Stock Tracker</title>\n"
        "<style>\n"
        ":root{--bg:#0f0f13;--card:#1a1a24;--acc:#e85d04;--txt:#e0e0e0;"
        "--mu:#888;--bd:#2a2a3a;--gn:#2ecc71;--rd:#e74c3c;--pu:#9b8dff}\n"
        "*{box-sizing:border-box;margin:0;padding:0}\n"
        "body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',sans-serif;padding:20px}\n"
        "header{display:flex;align-items:center;justify-content:space-between;"
        "margin-bottom:20px;flex-wrap:wrap;gap:10px}\n"
        ".ttl{font-size:1.35rem;font-weight:700;color:var(--acc)}\n"
        ".meta{font-size:.78rem;color:var(--mu);margin-top:3px}\n"
        ".bdg{background:var(--acc);color:#fff;padding:4px 14px;border-radius:20px;"
        "font-size:.82rem;font-weight:700}\n"
        ".bar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}\n"
        "button{padding:7px 16px;border:none;border-radius:6px;cursor:pointer;"
        "font-size:.82rem;font-weight:600;transition:opacity .2s}\n"
        "button:hover{opacity:.8}\n"
        ".bcsv{background:#27ae60;color:#fff}.bref{background:#2980b9;color:#fff}"
        ".bclr{background:#555;color:#fff}\n"
        ".fi{background:var(--card);border:1px solid var(--bd);color:var(--txt);"
        "padding:6px 11px;border-radius:6px;font-size:.82rem;width:220px}\n"
        ".wrap{overflow-x:auto;border-radius:8px;border:1px solid var(--bd)}\n"
        "table{width:100%;border-collapse:collapse}\n"
        "thead th{background:#13131e;color:var(--acc);font-size:.74rem;text-transform:uppercase;"
        "letter-spacing:.05em;padding:11px 9px;text-align:left;white-space:nowrap;"
        "border-bottom:2px solid var(--bd);cursor:pointer;user-select:none}\n"
        "thead th:hover{color:#fff}\n"
        "tbody tr{border-bottom:1px solid var(--bd);transition:background .12s}\n"
        "tbody tr:hover{background:rgba(232,93,4,.06)}\n"
        "td{padding:9px 8px;font-size:.83rem;vertical-align:middle}\n"
        ".th{width:60px;height:60px;object-fit:contain;border-radius:4px;background:#1f1f2e}\n"
        ".nc{min-width:190px;max-width:270px}.nc a{color:#a0c4ff;text-decoration:none;font-weight:500}\n"
        ".nc a:hover{text-decoration:underline}\n"
        ".gr{background:#2a2a3a;color:var(--pu);padding:3px 7px;border-radius:4px;"
        "font-size:.75rem;font-weight:600;white-space:nowrap}\n"
        ".mu{color:var(--mu)}.ph{color:var(--gn);font-weight:700}\n"
        ".sk{font-family:monospace;font-size:.76rem;color:var(--mu)}\n"
        ".sl{background:rgba(231,76,60,.15);color:var(--rd);padding:3px 7px;border-radius:4px;"
        "font-size:.78rem;font-weight:600;white-space:nowrap}\n"
        ".bb{background:var(--acc);color:#fff;padding:4px 10px;border-radius:5px;"
        "text-decoration:none;font-size:.78rem;font-weight:600;white-space:nowrap}\n"
        ".bb:hover{opacity:.85}\n"
        ".nt{display:block;min-width:130px;min-height:26px;padding:3px 7px;"
        "background:rgba(255,255,255,.04);border:1px dashed var(--bd);"
        "border-radius:4px;color:var(--txt);font-size:.78rem;outline:none}\n"
        ".nt:focus{border-color:var(--acc);background:rgba(232,93,4,.07)}\n"
        ".nt.ok{border-color:var(--gn)!important}\n"
        "footer{margin-top:18px;color:var(--mu);font-size:.74rem;text-align:center}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<header>\n"
        "  <div>\n"
        f'    <div class="ttl">&#9888;&#65039; HLJ Gundam Low-Stock Tracker</div>\n'
        f'    <div class="meta">Scraped: {ts} &nbsp;&middot;&nbsp; '
        f'Filter: &ldquo;Only 1&rdquo; / &ldquo;Only 2&rdquo; &nbsp;&middot;&nbsp; '
        f'JPY&rarr;PHP @ {JPY_TO_PHP}</div>\n'
        "  </div>\n"
        f'  <span class="bdg">{count} item{"s" if count!=1 else ""} found</span>\n'
        "</header>\n"
        '<div class="bar">\n'
        '  <button class="bcsv" onclick="exportCSV()">&#11015; Export CSV</button>\n'
        '  <button class="bref" onclick="location.reload()">&#128260; Refresh Page</button>\n'
        '  <button class="bclr" onclick="clearNotes()">&#128465; Clear Notes</button>\n'
        '  <input class="fi" id="fi" type="text" '
        'placeholder="Search name, SKU, grade&hellip;" oninput="ft()">\n'
        '  <label style="font-size:.8rem;color:var(--mu)">'
        '<input type="checkbox" id="cn" onchange="ft()"> Has notes</label>\n'
        "</div>\n"
        '<div class="wrap">\n'
        '  <table id="t">\n'
        "    <thead><tr>\n"
        "      <th>IMG</th>\n"
        '      <th onclick="st(1)">Name &#8597;</th>\n'
        '      <th onclick="st(2)">Grade &#8597;</th>\n'
        '      <th onclick="st(3)">JPY &#8597;</th>\n'
        '      <th onclick="st(4)">PHP &#8597;</th>\n'
        '      <th onclick="st(5)">Stock &#8597;</th>\n'
        "      <th>SKU</th><th>Link</th><th>Notes (click to edit)</th>\n"
        "    </tr></thead>\n"
        f'    <tbody id="tb">{rows}</tbody>\n'
        "  </table>\n"
        "</div>\n"
        "<footer>HLJ Low-Stock Tracker &nbsp;&middot;&nbsp; "
        "Notes auto-saved to localStorage &nbsp;&middot;&nbsp; "
        "Re-run script to refresh live data</footer>\n"
        "<script>\n"
        'const SK="hlj_ls_notes";\n'
        f"const DATA={data_json_str};\n"
        "function restoreNotes(){\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\n"
        "  document.querySelectorAll('.nt').forEach(e=>{\n"
        "    if(s[e.dataset.idx]!==undefined)e.textContent=s[e.dataset.idx];\n"
        "  });\n"
        "}\n"
        "function sn(e){\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\n"
        "  s[e.dataset.idx]=e.textContent.trim();\n"
        "  localStorage.setItem(SK,JSON.stringify(s));\n"
        "  e.classList.add('ok');setTimeout(()=>e.classList.remove('ok'),700);\n"
        "}\n"
        "function clearNotes(){\n"
        "  if(!confirm('Clear all notes?'))return;\n"
        "  localStorage.removeItem(SK);\n"
        "  document.querySelectorAll('.nt').forEach(e=>e.textContent='');\n"
        "}\n"
        "function ft(){\n"
        "  const q=document.getElementById('fi').value.toLowerCase();\n"
        "  const cn=document.getElementById('cn').checked;\n"
        "  const s=JSON.parse(localStorage.getItem(SK)||'{}');\n"
        "  document.querySelectorAll('#tb tr').forEach(r=>{\n"
        "    const has=s[r.dataset.idx]&&s[r.dataset.idx].trim();\n"
        "    r.style.display=(!q||r.textContent.toLowerCase().includes(q))&&(!cn||has)?'':'none';\n"
        "  });\n"
        "}\n"
        "function st(c){\n"
        "  const tb=document.getElementById('tb');\n"
        "  const rows=[...tb.querySelectorAll('tr[data-idx]')];\n"
        "  const asc=tb.dataset.sc==c&&tb.dataset.sd=='a';\n"
        "  tb.dataset.sc=c;tb.dataset.sd=asc?'d':'a';\n"
        "  rows.sort((a,b)=>{\n"
        "    const at=a.cells[c]?.textContent.trim()||'',bt=b.cells[c]?.textContent.trim()||'';\n"
        "    const an=parseFloat(at.replace(/[^\\d.]/g,'')),bn=parseFloat(bt.replace(/[^\\d.]/g,''));\n"
        "    if(!isNaN(an)&&!isNaN(bn))return asc?bn-an:an-bn;\n"
        "    return asc?bt.localeCompare(at):at.localeCompare(bt);\n"
        "  });\n"
        "  rows.forEach(r=>tb.appendChild(r));\n"
        "}\n"
        "function exportCSV(){\n"
        '  const s=JSON.parse(localStorage.getItem(SK)||"{}");\n'
        '  const f=["name","grade_scale","price_jpy","price_php","stock",'
        '"sku","image_url","affiliate_url","scraped_at","notes"];\n'
        '  const lines=[f.join(",")];\n'
        "  DATA.forEach((it,i)=>{\n"
        "    it.notes=s[i]||it.notes||'';\n"
        '    lines.push(f.map(k=>\'"\'+String(it[k]??\'\').replace(/"/g,\'""\')+\'"\').join(","));\n'
        "  });\n"
        "  const a=document.createElement('a');\n"
        "  a.href=URL.createObjectURL(new Blob([lines.join('\\n')],"
        "{type:'text/csv;charset=utf-8;'}));\n"
        "  a.download='low_stock_export.csv';a.click();\n"
        "}\n"
        "restoreNotes();\n"
        "</script>\n"
        "</body></html>\n"
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
