import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Query
from hlj_preorder_tracker import scrape_preorders  # Local import
from hlj_lowstock_tracker import scrape_low_stock  # Local import

app = FastAPI()

@app.get("/preorders")
async def preorders(max_pages: int = Query(20)):
    items = await scrape_preorders(max_pages)
    return {"items": items, "count": len(items)}

@app.get("/health")
async def health():
    return {"status": "ok"}