"""Premium Bandai (p-bandai) — limited / early product announcements."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..models import new_item
from ..template import BaseScraper

log = logging.getLogger(__name__)


class Scraper(BaseScraper):
    source_name = "Premium Bandai"
    region = "GLOBAL"
    language = "en"
    # TODO: pick correct regional storefront (p-bandai.com vs p-bandai.jp/hk/sg/etc.).
    listing_url = "https://p-bandai.com/intl/categories/g_gundam"

    def collect(self):
        soup = self.get_soup(self.listing_url)
        if not soup:
            return []

        items = []
        # TODO: P-Bandai uses heavy SPA / JSON-LD; selector is a placeholder.
        for card in soup.select(".product-tile, .item-list__item, .product-item"):
            a = card.find("a", href=True)
            if not a:
                continue
            url = urljoin(self.listing_url, a["href"])
            headline_el = card.select_one(".name, .product-name, h2, h3")
            headline = (headline_el.get_text(strip=True) if headline_el
                        else a.get_text(strip=True))
            if not headline:
                continue
            items.append(new_item(
                source_name=self.source_name,
                source_url=url,
                source_type="product_page",
                region=self.region,
                language=self.language,
                headline=headline,
                limited_flag=True,  # P-Bandai default
                sources=[url],
            ))

        return self.drop_unofficial(items)
