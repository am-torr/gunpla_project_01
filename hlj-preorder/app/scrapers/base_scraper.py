from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import time
import logging
from app.config import settings
from app.database import db

logger = logging.getLogger(__name__)

# Distribution type registry — extend as you add new sources
DISTRIBUTION_TYPE_MAP = {
    "hobby planet": "web_ph",
    "hobby link japan": "web_jp",
    "wasabi toys": "shopee_ph",
    "samuel's model kits": "web_ph",
}

class BaseScraper(ABC):
    def __init__(self):
        self.store_name = ""
        self.base_url = ""
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        self.delay = settings.SCRAPE_DELAY_SECONDS

    def get_distribution_type(self) -> str:
        return DISTRIBUTION_TYPE_MAP.get(self.store_name.lower(), "web")

    @abstractmethod
    async def scrape(self) -> List[Dict]:
        pass

    @abstractmethod
    def parse_product(self, element) -> Dict:
        pass

    def fetch_page(self, url: str, retries: int = 3) -> BeautifulSoup:
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
        if not db:
            print("No DB - skipping")
            return None

        bandai_sku = product_data.get("bandai_sku")
        product_name = product_data.get("product_name")
        sku = product_data.get("sku") or bandai_sku or product_name
        if not sku:
            print("No SKU - skipping")
            return None
        product_data["sku"] = sku

        try:
            result = db.table("scraped_products").upsert(product_data).execute()
            print(f"SAVED: {product_data.get('product_name')[:50]} id={result.data[0]['id']}")
            return result.data[0]["id"]
        except Exception as e:
            print(f"PASS: {e}")
            return None

    def save_price(self, product_id: Optional[str], price_data: Dict) -> None:
        if not db or not product_id:
            print("No DB/product_id - skipping")
            return
        try:
            # Get store UUID - FIXED: "name" → "store_name"
            store = db.table("stores").select("id").eq("store_name", self.store_name).execute()
            store_id = store.data[0]["id"] if store.data else None
            
            price_data["product_id"] = product_id
            price_data["store_id"] = store_id
            price_data["store_name"] = self.store_name
            db.table("store_prices").insert(price_data).execute()
            print(f"PRICE OK: {self.store_name} → {store_id}")
        except Exception as e:
            print(f"PRICE ERR: {e}")
