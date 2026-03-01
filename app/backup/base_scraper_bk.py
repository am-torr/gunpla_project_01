from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import time
import logging
from app.config import settings
from app.database import db

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all store scrapers"""

    def __init__(self):
        self.store_name = ""
        self.base_url = ""
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        self.delay = settings.SCRAPE_DELAY_SECONDS

    @abstractmethod
    async def scrape(self) -> List[Dict]:
        """
        Main scrape method - must be implemented by each scraper.
        Returns list of product dictionaries.
        """
        pass

    @abstractmethod
    def parse_product(self, element) -> Dict:
        """
        Parse individual product element.
        """
        pass

    def fetch_page(self, url: str, retries: int = 3) -> BeautifulSoup:
        """
        Fetch page with retry logic.
        """
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                time.sleep(self.delay)
                return BeautifulSoup(response.content, "lxml")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(self.delay * 2)

    def save_product(self, product_data: Dict) -> Optional[str]:
        """
        Save or update product in gunpla_catalog.
        Returns product_id or None if it cannot be identified.
        """
        if not db:
            logger.warning("Database not configured - skipping product save")
            return None

        bandai_sku = product_data.get("bandai_sku")
        product_name = product_data.get("product_name")

        # Derive a non-null sku for gunpla_catalog
        sku = product_data.get("sku") or bandai_sku or product_name
        if not sku:
            logger.warning("No sku/bandai_sku/product_name; skipping product save")
            return None
        product_data["sku"] = sku

        # Require distribution_type as well (NOT NULL in gunpla_catalog)
        distribution_type = product_data.get("distribution_type")
        if not distribution_type:
            logger.warning(
                "Missing distribution_type; skipping product save for "
                f"{product_name or bandai_sku or sku}"
            )
            return None

        try:
            if bandai_sku:
                existing = (
                    db.table("gunpla_catalog")
                    .select("id")
                    .eq("bandai_sku", bandai_sku)
                    .execute()
                )
            else:
                existing = (
                    db.table("gunpla_catalog")
                    .select("id")
                    .eq("product_name", product_name)
                    .execute()
                )

            if existing.data:
                product_id = existing.data[0]["id"]
                db.table("gunpla_catalog").update(
                    {"last_updated": "now()", **product_data}
                ).eq("id", product_id).execute()
                logger.info(f"Updated product: {product_id}")
            else:
                result = db.table("gunpla_catalog").insert(product_data).execute()
                product_id = result.data[0]["id"]
                logger.info(f"Inserted new product: {product_id}")

            return product_id

        except Exception as e:
            logger.error(f"Error saving product: {e}")
            raise

    def save_price(self, product_id: Optional[str], price_data: Dict) -> None:
        """
        Save store price for product into store_prices.
        """
        if not db or not product_id:
            logger.info("No DB or product_id; skipping price save")
            return

        try:
            db.table("store_prices").insert(
                {"product_id": product_id, "store_name": self.store_name, **price_data}
            ).execute()
            logger.info(f"Saved price for product: {product_id}")
        except Exception as e:
            logger.error(f"Error saving price: {e}")
            raise



