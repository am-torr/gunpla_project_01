import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Query
from hlj_preorder_tracker import scrape_preorders  # ← FIXED func name

app = FastAPI()

@app.get("/preorders")
async def preorders(maxpages: int = Query(1)):
    items = await scrape_preorders(maxpages)  # ← FIXED call
    return {"items": items[:3], "count": len(items)}

@app.get("/health")
def health():
    return {"status": "trackers loaded"}

@app.get("/test")
def test():
    return {"alive": True}