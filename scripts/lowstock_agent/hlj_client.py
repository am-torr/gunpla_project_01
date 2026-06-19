"""Fetch low-stock items from the existing hlj-lowstock FastAPI service (:8001).

The service returns {"items": [...], "count": N}. A saved fixture is a flat
array. Both shapes are handled so the agent can run live or offline.
"""
import json
from pathlib import Path
from typing import Optional

import httpx

from .config import settings


def _unwrap(payload):
    if isinstance(payload, dict) and "items" in payload:
        return payload["items"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unexpected low-stock payload shape: {type(payload)}")


async def fetch_from_api(threshold: int = 5, base_url: Optional[str] = None) -> list[dict]:
    url = (base_url or settings.HLJ_LOWSTOCK_URL).rstrip("/") + "/low-stock"
    async with httpx.AsyncClient(timeout=settings.HLJ_FETCH_TIMEOUT) as client:
        resp = await client.get(url, params={"threshold": threshold})
        resp.raise_for_status()
        return _unwrap(resp.json())


def load_from_file(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _unwrap(data)
