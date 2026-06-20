"""Bandai Hobby Site (bandai-hobby.net) — JP official Gunpla portal."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..models import new_item
from ..template import BaseScraper

log = logging.getLogger(__name__)


class Scraper(BaseScraper):
    source_name = "Bandai Hobby Site"
    region = "JP"
    language = "ja"
    # TODO: confirm exact listing path; root site has multiple sub-feeds.
    listing_url = "https://bandai-hobby.net/site/"

    def collect(self):
        soup = self.get_soup(self.listing_url)
        if not soup:
            return []

        items = []
        # TODO: real selector lives inside the SPA shell; conservative stub for now.
        for a in soup.select("a[href*='/item/'], a[href*='/news/'], .news-list a[href]"):
            url = urljoin(self.listing_url, a.get("href", ""))
            headline = a.get_text(strip=True)
            if not url or not headline:
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
