import asyncio
from fastapi import FastAPI, Query
from typing import List
from hlj_lowstock_tracker import scrape_low_stock

app = FastAPI()

@app.get("/low-stock")
async def low_stock(
    stock: List[str] = Query(default=["only 1", "only 2"])
):
    items = await scrape_low_stock(stock_filter=stock)
    return {"items": items}

@app.get("/health")
async def health():
    return {"status": "ok"}
