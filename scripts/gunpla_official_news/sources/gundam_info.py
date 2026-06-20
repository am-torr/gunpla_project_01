"""Gundam.info — official news / Gunpla topic feed."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..models import new_item
from ..template import BaseScraper

log = logging.getLogger(__name__)


class Scraper(BaseScraper):
    source_name = "Gundam.info"
    region = "GLOBAL"
    language = "en"
    # TODO: confirm canonical listing URL; en.gundam.info redirects per-region.
    listing_url = "https://en.gundam.info/topic/gunpla.html"

    def collect(self):
        soup = self.get_soup(self.listing_url)
        if not soup:
            return []

        items = []
        # TODO: tighten selector — current guess targets article cards on the topic page.
        for card in soup.select("article, .topic-list__item, .news-list__item"):
            a = card.find("a", href=True)
            if not a:
                continue
            url = urljoin(self.listing_url, a["href"])
            h_el = card.select_one("h2, h3, .title")
            headline = h_el.get_text(strip=True) if h_el else a.get_text(strip=True)
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
