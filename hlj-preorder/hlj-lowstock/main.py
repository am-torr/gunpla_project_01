from fastapi import FastAPI, Query
from hlj_lowstock_tracker import scrape_low_stock

app = FastAPI()

@app.get("/low-stock")
async def low_stock(threshold: int = Query(5)):
    items = await scrape_low_stock(threshold)
    return {"items": items, "count": len(items)} # Flat array

@app.get("/health")
async def health():
    return {"status": "ok"}
    
    
    
    