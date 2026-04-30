from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import asyncio
import uuid
from bandai_manual_scraper import scrape_single_kit, scrape_list_page_kits

app = FastAPI(title="Bandai Manual Scraper", version="1.0.0")

jobs: dict = {}

@app.get("/health")
def health():
    return {"status": "ok", "service": "bandai-scraper", "time": datetime.utcnow().isoformat()}

@app.post("/scrape/kit/{manual_id}")
async def scrape_kit(manual_id: int):
    """Scrape a single kit. POC: use manual_id=4954 (Alyzeus). Takes 20-40s."""
    result = await scrape_single_kit(manual_id)
    return {"success": True, "manual_id": manual_id, "data": result}

class BulkRequest(BaseModel):
    year: int = 2026
    brand_category: int = 1
    max_pages: int = 50

@app.post("/scrape/bulk")
async def scrape_bulk(req: BulkRequest, background_tasks: BackgroundTasks):
    """Phase 2/3: scrape all HG kits for a given year. Runs in background."""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "year": req.year,
        "pages_done": 0,
        "kits_total": 0,
        "started_at": datetime.utcnow().isoformat()
    }
    background_tasks.add_task(_run_bulk, job_id, req.year, req.brand_category, req.max_pages)
    return {"job_id": job_id, "status": "queued", "year": req.year}

async def _run_bulk(job_id: str, year: int, category: int, max_pages: int):
    jobs[job_id]["status"] = "running"
    year_cutoff = f"{year}-01-01"
    total = 0
    try:
        for page_num in range(1, max_pages + 1):
            kits = await scrape_list_page_kits(page_num, year_cutoff, category)
            if not kits:
                print(f"  [bulk] No more kits after page {page_num} - stopping")
                break
            for kit in kits:
                try:
                    await scrape_single_kit(kit["manual_id"])
                    total += 1
                    jobs[job_id]["kits_total"] = total
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"  [bulk] ERROR on manual_id={kit['manual_id']}: {e}")
            jobs[job_id]["pages_done"] = page_num
        jobs[job_id]["status"] = "done"
        jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

@app.get("/scrape/status/{job_id}")
def job_status(job_id: str):
    """Poll bulk job progress."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/scrape/jobs")
def list_jobs():
    """List all jobs in this session."""
    return jobs
