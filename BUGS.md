## 🐛 Bug Register

### BUG-01 — Limit = 0: No Input Validation
**Severity:** Medium  
**Layer:** Backend · `api_server.py`  
**Symptom:** `limit=0` accepted, HTTP 200 returned with empty products array  
**Fix:**

python
# api_server.py
from fastapi import Query
limit: int = Query(default=15, ge=1, le=50)



**Date:** February 20, 2026  
**Build:** POC v2.1  
**Source:** System Test (ST-01 to ST-30)  
**Total Bugs Found:** 5  

---

## Bug Index

| ID | Severity | Layer | Title | Status |
|---|---|---|---|---|
| [BUG-01](#bug-01--limit--0-no-input-validation) | 🟡 Medium | Backend + Frontend | `limit=0` accepted — no validation | 🔴 Open |
| [BUG-02](#bug-02--limit---1-negative-value-bypasses-limiter) | 🔴 High | Backend | `limit=-1` bypasses limiter, returns full catalog | 🔴 Open |
| [BUG-03](#bug-03--grade-detection-miss-for-3rd-party-brands) | 🟡 Medium | Scraper | Grade/scale returns `"Unknown"` for 3rd-party brands | 🔴 Open |
| [BUG-04](#bug-04--hlj-stock-status-inaccurate-backordered--order-now) | 🔴 High | Scraper | HLJ backordered items shown as `"Order now!"` | 🔴 Open |
| [BUG-05](#bug-05--invalid-grade-param-silent-404-masked-as-success) | 🟡 Medium | Backend | Invalid `grade` param returns `success:true` with embedded 404 error | 🔴 Open |

---

## BUG-01 — Limit = 0: No Input Validation

| Field | Detail |
|---|---|
| **ID** | BUG-01 |
| **Severity** | 🟡 Medium |
| **Layer** | Backend · `api_server.py` + Frontend · `index.html` + JS handler |
| **Discovered In** | ST-17 |
| **HTTP Status Returned** | `200 OK` *(should be `422 Unprocessable Entity`)* |

### Description
The `limit` query parameter accepts `0` without any validation. When `limit=0` is passed, the API executes the full scrape, hits the live website, and returns an empty products array with `success:true` — wasting server resources and returning misleading data.

