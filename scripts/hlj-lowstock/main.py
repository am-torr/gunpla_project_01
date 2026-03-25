from fastapi import FastAPI, Query
from typing import List
from hlj_lowstock_tracker import scrape_low_stock

app = FastAPI()

@app.get("/low-stock")
async def low_stock(stock: List[str] = Query(["only 5"])):
    items = await scrape_low_stock(stock)
    return {"items": items, "count": len(items)}  # Flat array

@app.get("/health")
async def health():
    return {"status": "ok"}