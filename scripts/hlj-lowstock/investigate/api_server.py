from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
import os
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO)
# from app.database import get_db_connection  # Assume from app/database.py
# from app.scrapers.hobby_link_japan import scrape_hlj  # Import
# from app.scrapers.hobby_planet import scrape_hp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#  SCRAPER FUNCTIONS 


def scrape_hobby_planet(grade="", scale="", limit=20, **kwargs):
    try:
        GRADE_SLUGS = {'mg':'master-grade','hg':'high-grade','rg':'real-grade','pg':'perfect-grade','sd':'sd-gundam','re':'re100','fm':'full-mechanics','master grade':'master-grade','high grade':'high-grade','real grade':'real-grade','perfect grade':'perfect-grade'}
        grade_slug = GRADE_SLUGS.get(grade.lower().strip(), grade.lower().replace(' ', '-')) if grade else 'gunpla'
        url = "https://hobbyplanet.info/product-category/gunpla/" + grade_slug + "/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('ul.products li.product')[:limit]:
            try:
                name_elem = item.select_one('h4.product-title a')
                name = name_elem.get_text(strip=True) if name_elem else None
                if not name:
                    continue
                price_elem = item.select_one('span.price span.woocommerce-Price-amount')
                price_text = price_elem.get_text(strip=True) if price_elem else "0"
                price_numbers = re.findall(r'\d+\.?\d*', price_text.replace(',', ''))
                price = float(price_numbers[0]) if price_numbers else 0
                link = name_elem
                product_url = link['href'] if link and link.get('href') else ""
                stock = "In Stock" if 'instock' in item.get('class', []) else "Out of Stock"
                grade_match = re.search(r'\b(MG|HG|RG|PG|SD|RE|FM)\b', name, re.IGNORECASE)
                detected_grade = grade_match.group(1).upper() if grade_match else "Unknown"
                scale_match = re.search(r'1/(\d+)', name)
                detected_scale = f"1/{scale_match.group(1)}" if scale_match else "Unknown"
                if scale and detected_scale != scale:
                    continue
                products.append({
                    'name': name, 'grade': detected_grade, 'scale': detected_scale,
                    'price': price, 'currency': 'PHP', 'stock': stock,
                    'url': product_url, 'on_sale': bool(item.select_one('.onsale')),
                    'scraped_at': datetime.now().isoformat()
                })
            except Exception:
                continue
        return products, url
    except Exception as e:
        return [], f"ERROR: {e}"

# NO IMPORTS - Inline scrape_hobby_planet call + HLJ mock - test

@app.get("/api/kits")
def get_kits(filter: str = "all", limit: int = 20):
    # Use existing scrape_hobby_planet (no import needed, same file)
    hp_raw = scrape_hobby_planet(limit=limit)
    hp_kits = hp_raw[0] if isinstance(hp_raw, (list, tuple)) and len(hp_raw) > 0 else []
    
    # HLJ mock (real impl post-test from hlj_check.py)
    hlj_kits = [
        {"name": "Providence Gundam BL2508", "grade": "MG", "price": "PHP 1350", "stock_status": "In Stock"},
        {"name": "Duel Gundam Daban", "grade": "MG", "price": "PHP 1200", "stock_status": "BACKORDER"}  # Filtered
    ]
    
    all_kits = hp_kits + hlj_kits
       

    logging.info(f"DEBUG: Sample stock: {all_kits[0].get('stock') if all_kits else 'NONE'}")
    print(f"DEBUG STOCK[0]: {all_kits[0].get('stock') if all_kits else 'NONE'}")

    if filter == "available":
        all_kits = [kit for kit in all_kits 
                    if kit.get('stock', '').upper() not in ['ORDERSTOP', 'ORDER_STOP', 'BACKORDER', 'OUT_OF_STOCK', 'ORDER NOW'] and
                    'ORDER_STOP' not in str(kit.get('name', '')).upper()]
            
    # DEBUG LOG
    import logging

    logging.info(f"DEBUG: Raw kits {len(all_kits)}, sample keys: {list(all_kits[0].keys()) if all_kits else 'EMPTY'}")
    logging.info(f"DEBUG: Sample stock: {all_kits[0].get('stock') if all_kits else 'NONE'}")
    print(f"DEBUG KIT[0]: {all_kits[0] if all_kits else 'NO KITS'}")
    print(f"DEBUG STOCK[0]: {all_kits[0].get('stock') if all_kits else 'NONE'}")
    
    return {
        "success": True,
        "store": store or "mixed",
        "products": all_kits[:limit],
        "kits": all_kits[:limit],  # Dual compat
        "total": len(all_kits),
        "count": len(all_kits),
        "filter_applied": filter
    }



def scrape_hlj(grade="", limit=10, **kwargs):
    import asyncio
    from app.scrapers.hobby_link_japan import HobbyLinkJapanScraper
    GRADE_SEARCH = {'MG':'gunpla+MG+1/100','HG':'gunpla+HG+1/144','HGUC':'gunpla+HGUC','RG':'gunpla+RG+1/144','PG':'gunpla+PG+1/60','SD':'gunpla+SD'}
    search_word = GRADE_SEARCH.get(grade.upper(), 'gunpla')
    async def _run():
        scraper = HobbyLinkJapanScraper()
        scraper.gunpla_url = f'https://www.hlj.com/search/?Word={search_word}&perpage=48'
        return await scraper.scrape(limit=limit)
    try:
        results = asyncio.run(_run())
        products = []
        GRADE_MAP = {'mgex':'MG','hguc':'HG','hgce':'HG','hgac':'HG','hgbf':'HG'}
        for r in results:
            p = r.get('product', {})
            pr = r.get('price', {})
            name = p.get('product_name', '')
            grade_match = re.search(r'\b(MGEX|HGUC|HGCE|HGAC|HGBF|MG|HG|RG|PG|SD|RE|FM)\b', name, re.IGNORECASE)
            detected = GRADE_MAP.get(grade_match.group(1).lower(), grade_match.group(1).upper()) if grade_match else 'Unknown'
            scale_match = re.search(r'1/(\d+)', name)
            detected_scale = f"1/{scale_match.group(1)}" if scale_match else p.get('scale', 'Unknown')
            if grade and grade.upper() != detected and grade.upper() not in name.upper():
                continue
            products.append({'name': name, 'grade': detected, 'scale': detected_scale, 'price': pr.get('price', 0), 'currency': pr.get('currency','JPY'), 'stock': pr.get('stock_status','Unknown'), 'url': pr.get('product_url',''), 'scraped_at': datetime.now().isoformat()})
        return products, f'https://www.hlj.com/search/?Word={search_word}&perpage=48'
    except Exception as e:
        return [], f"ERROR: {e}"

STORE_REGISTRY = {
    "hobby-planet": scrape_hobby_planet,
    "hlj":          scrape_hlj,
}

#  ENDPOINTS 

@app.get("/")
@app.get('/')
def root():
    return FileResponse('gunpla-poc-hybrid-v2.html')

@app.get('/api/status')
def status():
    return {
        "status": "running",
        "stores": list(STORE_REGISTRY.keys()),
        "endpoints": ["/api/scrape", "/api/stores"]
    }

@app.get("/api/stores")
def list_stores():
    """List all registered stores"""
    return {"stores": list(STORE_REGISTRY.keys())}

@app.get("/api/scrape")
def scrape_live(
    store: str = "hobby-planet",
    grade: str = "",
    scale: str = "",
    limit: int = 15,
    sort: str = "latest"
):
    """
    Unified scrape endpoint. Pass store= to target a specific store, or store=all for all stores.
    """
    targets = list(STORE_REGISTRY.keys()) if store == "all" else [store]
    unknown = [s for s in targets if s not in STORE_REGISTRY]
    if unknown:
        return {"success": False, "error": f"Unknown store(s): {unknown}. Available: {list(STORE_REGISTRY.keys())}"}

    all_results = []
    for store_key in targets:
        scraper_fn = STORE_REGISTRY[store_key]
        products, scraped_url = scraper_fn(grade=grade, scale=scale, limit=limit)

        if sort == "price-low":
            products.sort(key=lambda x: x['price'])
        elif sort == "price-high":
            products.sort(key=lambda x: x['price'], reverse=True)

        all_results.append({
            "store": store_key,
            "count": len(products),
            "scraped_url": scraped_url,
            "products": products
        })

    # Flatten if single store for backward compatibility
    if len(all_results) == 1:
        r = all_results[0]
        return {
            "success": True,
            "store": r["store"],
            "count": r["count"],
            "products": r["products"],
            "scraped_url": r["scraped_url"],
            "scraped_at": datetime.now().isoformat()
        }

    return {
        "success": True,
        "stores_queried": targets,
        "total_count": sum(r["count"] for r in all_results),
        "results": all_results,
        "scraped_at": datetime.now().isoformat()
    }

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
