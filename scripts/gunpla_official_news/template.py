"""BaseScraper: shared HTTP/soup helpers + the collect() contract."""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup

from .config import DEFAULT_HEADERS, DEFAULT_TIMEOUT
from .models import NewsItem
from .verification import is_official_url

log = logging.getLogger(__name__)


class BaseScraper:
    """Subclasses override collect(); use get_soup() / get_text() / drop_unofficial()."""

    source_name: str = ""
    region: str = ""
    language: str = ""
    listing_url: str = ""

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    # ── HTTP ──────────────────────────────────────────────────────────────
    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            r = self.session.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.warning("GET %s failed: %s", url, e)
            return None

    def get_soup(self, url: str, parser: str = "html.parser") -> Optional[BeautifulSoup]:
        r = self.get(url)
        if not r:
            return None
        return BeautifulSoup(r.text, parser)

    def get_text(self, url: str) -> Optional[str]:
        r = self.get(url)
        return r.text if r else None

    # ── Verification ──────────────────────────────────────────────────────
    def drop_unofficial(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        kept = []
        for it in items:
            if is_official_url(it.source_url):
                kept.append(it)
            else:
                log.info("DROP non-official: %s", it.source_url)
        return kept

    # ── Contract ──────────────────────────────────────────────────────────
    def collect(self) -> list[NewsItem]:
        raise NotImplementedError
