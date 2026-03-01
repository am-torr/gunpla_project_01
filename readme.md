# Gunpla Price Tracker

> **Production-grade web scraper** that tracks Gunpla model kit prices across
> multiple Philippine hobby stores in real time — with a live FastAPI dashboard,
> Docker orchestration, n8n automation, and AI-powered deal alerts.

**Version:** POC v2.1 — Live demo ready 
**Built:** January 2026
**Status:** ✅ Live API · ✅ Scrapers 100% · ✅ Docker Ready · ✅ Portfolio Active

---

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
