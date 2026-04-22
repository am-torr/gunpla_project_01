# Gunpla Scarcity Content Pipeline

> **Self-hosted n8n + Python + Supabase automation system** that monitors HLJ Gunpla inventory signals, stages qualified low-stock products, generates affiliate-ready Facebook post candidates, batches them for controlled publishing, and synchronizes source-to-publish state across staging, queue, and batch records — end to end, without manual intervention.

**Status:** ✅ Live · ✅ Production-deployed · ✅ Self-hosted on Docker Compose  
**Stack:** n8n · Python · Supabase (PostgreSQL) · Facebook Graph API · Playwright · FastAPI · Docker

---

## The Problem

Manually scouting Gunpla low-stock listings, writing affiliate post copy, uploading images, and scheduling Facebook posts across a product catalog is slow and error-prone at scale. A single missed low-stock window means a lost affiliate conversion opportunity.

---

## The Solution

A four-stage automation pipeline that runs on a schedule:

```
HLJ Inventory Feed
       ↓
[01 - Ingest]  Scrape → Deduplicate by SKU → Filter low-stock → Generate content fingerprint → Stage to DB
       ↓
[02 - Queue]   Load staged items → Build post copy → Shorten affiliate URL (Bitly / TinyURL fallback) → Upload image to Facebook → Insert post_queue record
       ↓
[03 - Batch]   Schedule trigger → Assign post_queue items to publish batches → Loop over batches → Call publish sub-workflow
       ↓
[04 - Publish] Fetch batch items → Post to Facebook (Primary + Retry) → Evaluate response → Update post_queue + post_queue_batch + post_queue_stg
       ↓
    Facebook Post Live
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Workflow Orchestration** | n8n (self-hosted, Docker Compose) |
| **Scraper** | Python 3.11, Playwright (JS-rendered), BeautifulSoup (static HTML) |
| **API Integration** | Facebook Graph API, Bitly API, TinyURL API (fallback) |
| **Database** | Supabase PostgreSQL — staging, queue, batch, and state sync tables |
| **Backend API** | FastAPI + uvicorn |
| **Infrastructure** | Docker Compose, Cloudflare Tunnel, self-hosted |
| **Error Handling** | Per-node failure branches, retry logic, skip/continue loop control, dead-letter staging |

---

## Workflow Architecture

### 01 — Ingest HLJ Low-Stock Items
Scrapes the HLJ product feed, normalizes output, deduplicates by SKU to prevent reprocessing, filters for qualifying low-stock signals, generates a content fingerprint (SHA hash of SKU + price), and inserts staged records into `post_queue_stg`. Explicit failure branch fires on fetch errors without crashing the run.

### 02 — Create Post Queue Candidates
Loads staged items, filters for queue-eligible records, and for each item: prepares shared content inputs, builds Facebook post copy, creates a Bitly short link (with TinyURL as automatic fallback), uploads the product image to the Facebook media endpoint, and inserts a complete record into `post_queue`. Updates both `post_queue` and `post_queue_stg` status on success.

### 03 — Batch and Publish Queue Items
Schedule-triggered dispatcher. Calls a Supabase RPC function (`assign_all_batches`) to group pending queue items into controlled publish batches. Loops over each batch and calls Workflow 04 as an isolated sub-workflow, keeping dispatch logic fully decoupled from publish execution.

### 04 — Publish Facebook Post (Sub-Workflow)
Publishes each batch to the Facebook Graph API. Primary post attempt with automatic retry path on failure. Evaluates the API response, updates `post_queue`, `post_queue_batch`, and `post_queue_stg` in sequence. Returns a structured result object (batch ID, status, posted timestamp) to the caller regardless of execution path. `Handle Primary Post Failure` branch captures unrecoverable errors without stopping the batch loop.

---

## Key Engineering Decisions

- **Modular sub-workflow pattern** — each workflow has one job; Workflow 03 dispatches, Workflow 04 publishes. They are independently testable and replaceable.
- **Staging table separation** — `post_queue_stg` holds raw ingestion state; `post_queue` holds publish-ready records; `post_queue_batch` tracks batch-level execution. No single table does double duty.
- **Content fingerprinting** — SHA hash of SKU + price prevents re-staging duplicate products across runs without requiring a full table scan.
- **URL fallback chain** — Bitly is primary short link; TinyURL fires automatically on Bitly failure. Affiliate URL is never lost.
- **Retry + failure isolation** — Facebook post failures trigger a retry attempt before routing to the failure handler. A single failed post does not abort the batch.
- **Self-hosted n8n** — deployed via Docker Compose with environment-variable-based credential management. No hardcoded API keys in any workflow node.

---

## Database Schema (Key Tables)

| Table | Purpose |
|---|---|
| `post_queue_stg` | Raw staging — holds scraped products before queue assignment |
| `post_queue` | Publish queue — fully-prepared post records with copy, image, URL |
| `post_queue_batch` | Batch execution tracker — links queue items to publish runs |

Key fields: `source_id`, `content_hash`, `stg_status`, `status`, `batch_queue_id`, `fb_post_id`, `posted_at`

---

## Error Handling & Reliability

- Every critical node has an explicit failure branch
- Loop control uses named `Skip Current Item`, `Continue Item Processing`, `Advance to Next Item` paths — not generic labels
- Fetch failures route to `Handle HLJ Fetch Failure` without stopping subsequent items
- Batch assignment failures route to `Handle Batch Assignment Failure` with full run context preserved
- Post publish failures route to `Handle Primary Post Failure` after retry exhaustion
- All cross-table state updates are sequential and confirmed before returning output

---

## Local Setup

```bash
# Clone repo
git clone https://github.com/am-torr/gunpla_project_01.git
cd gunpla_project_01

# Copy environment config
cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_KEY, FB_PAGE_TOKEN, FB_PAGE_ID, BITLY_TOKEN

# Start all services
docker compose up -d

# Verify n8n is running
curl http://localhost:5679/healthz

# Verify scraper API
curl "http://localhost:8000/api/scrape?store=hlj&grade=MG&limit=5"
```

---

## Repository Structure

```
gunpla_project_01/
├── workflows/          # n8n workflow JSON exports (01–04)
├── app/                # FastAPI scraper backend
├── m-hub-db/           # Supabase schema, migrations, RPC functions
├── scripts/            # Utility scripts (health checks, batch tools)
├── n8n nodes/          # Custom node configurations
├── nginx/              # Reverse proxy config
├── docker-compose.yml  # Full stack orchestration
└── requirements.txt    # Python dependencies
```

---

## Demo

> Loom walkthrough (5 min): Ingest → Queue → Batch → Publish — **[COMING SOON]**

The walkthrough covers:
- Live scrape run showing deduplication and low-stock filtering
- Queue candidate creation with Bitly short link generation
- Batch assignment via Supabase RPC
- Facebook publish with retry path and state sync

---

## Built By

**Arvin Torralba** — AI Automation Engineer  
Self-hosted n8n · Python · Supabase · Facebook Graph API · Docker Compose  
[GitHub](https://github.com/am-torr)
