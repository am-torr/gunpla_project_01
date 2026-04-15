# N8N Low stock items tracker + AI RAG news gatherer + social media posting

> **Real time scraping** that tracks low stock prices of hobby link japan items and later on expands to other shops.
> 
https://github.com/user-attachments/assets/f884423f-266a-4da0-9971-0fb2de934b0f


> **N8N workflow design** robust, reliable and readable n8n workflow by applying what I've accomplished in Oracle workflow. If this design is unconventional just let me know :)
>

https://github.com/user-attachments/assets/163ef4a8-7450-40da-a406-2cc0c4690bb6


> **N8N workflow improvements** ongoing - workflow real time approval

https://github.com/user-attachments/assets/bdf2ae48-9260-4790-8d6e-07b84588cbd0


> **Database integration** ongoing - workflow real time approval

https://github.com/user-attachments/assets/1869e097-72c8-4c30-b403-2d3273199991

-------------------------------------------------------------------------------
# Gunpla Price Tracker

> **Production-grade web scraper** that tracks Gunpla model kit prices across
> multiple Philippine hobby stores in real time — with a live FastAPI dashboard,
> Docker orchestration, n8n automation, and AI-powered deal alerts.

**Version:** POC v2.1 — Live demo ready 
**Built:** January 2026
**Status:** ✅ Live API · ✅ Scrapers 100% · ✅ Docker Ready · ✅ Portfolio Active

---

<img width="1916" height="876" alt="image" src="https://github.com/user-attachments/assets/cfbcb0af-32aa-473d-8d20-803272f4a516" />


## 🚀 Live Demo

| Resource | URL |
|---|---|
| 📊 Dashboard | `http://localhost:8000/` |
| 📡 API Docs (Swagger) | `http://localhost:8000/docs` |
| 🌐 Cloud (coming soon) | `https://gunpla-tracker.onrender.com` |

> **Quick test:**
> ```bash
> curl "http://localhost:8000/api/scrape?store=hlj&grade=MG&limit=5"
> ```

---

## 🎯 What It Does

Scrapes live Gunpla prices from **Hobby Planet PH** and **Hobby Link Japan** —
two stores with completely different tech stacks (static HTML vs. JS-rendered prices).


## 🔧 Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, uvicorn |
| **Scrapers** | Playwright (dynamic JS), BeautifulSoup (static HTML) |
| **Scheduler** | APScheduler — hourly auto-scrape |
| **Automation** | n8n workflow orchestration |
| **AI** | Perplexity API — product analysis + deal copy |
| **Database** | Supabase PostgreSQL (scaffolded, Phase 2) |
| **Deploy** | Docker Compose → Render / AWS EC2 |
| **Testing** | pytest — 100% pass rate |


## 📋 LOCAL Test

# Single store
curl "http://localhost:8000/api/scrape?store=hlj&grade=MG&limit=10"

# All stores
curl "http://localhost:8000/api/scrape?store=all&limit=15"

# Sort by price
curl "http://localhost:8000/api/scrape?store=hobby-planet&sort=price-low&limit=10"





