import asyncio
from fastapi import FastAPI
from hlj_lowstock_tracker import scrape_low_stock  # your script

app = FastAPI()

@app.get("/low-stock")
async def low_stock():
    items = await scrape_low_stock()
    return {"items": items}

@app.get("/health")
async def health():
    return {"status": "ok"}
