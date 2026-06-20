"""GUNDAM Official (gundam.net) — corporate news room."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..models import new_item
from ..template import BaseScraper

log = logging.getLogger(__name__)


class Scraper(BaseScraper):
    source_name = "GUNDAM Official"
    region = "GLOBAL"
    language = "en"
    # TODO: confirm news landing path; gundam.net has multiple language editions.
    listing_url = "https://gundam.net/news"

    def collect(self):
        soup = self.get_soup(self.listing_url)
        if not soup:
            return []

        items = []
        for card in soup.select("article, .news-item, .post-card"):
            a = card.find("a", href=True)
            if not a:
                continue
            url = urljoin(self.listing_url, a["href"])
            h_el = card.select_one("h1, h2, h3, .title")
            headline = (h_el.get_text(strip=True) if h_el
                        else a.get_text(strip=True))
            if not headline:
                continue
            items.append(new_item(
                source_name=self.source_name,
                source_url=url,
                source_type="news_article",
                region=self.region,
                language=self.language,
                headline=headline,
                sources=[url],
            ))

        return self.drop_unofficial(items)
