from fastapi import FastAPI, Query
from scripts.hlj_lowstock_tracker import scrape_low_stock
from scripts.hlj_preorder_tracker import scrape_preorders

app = FastAPI()

@app.get("/low-stock")
async def low_stock(threshold: int = Query(5)):
    items = await scrape_low_stock(threshold)
    return {"items": items, "count": len(items)}

@app.get("/preorders")
async def preorders(max_pages: int = Query(20)):
    items = await scrape_preorders(max_pages)
    return {"items": items, "count": len(items)}

@app.get("/health")
async def health():
    return {"status": "ok"}
