from typing import List, Dict
from bs4 import BeautifulSoup
import re
from .base_scraper import BaseScraper
import asyncio
from playwright.async_api import async_playwright
from ._selectors import HLJSelectors, HLJPatterns  # UPDATED: Import protected module


class HobbyLinkJapanScraper(BaseScraper):
    """Hobby Link Japan Gunpla Scraper with Complete Detail Extraction"""

    def __init__(self):
        super().__init__()
        self.store_name = "Hobby Link Japan"
        self.base_url = "https://www.hlj.com"
        self.gunpla_url = f"{self.base_url}/search/?Word=gunpla"

    async def scrape(self, limit: int = 10) -> List[Dict]:
        """Scrape Gunpla products from HLJ with Playwright - Comet-audited selectors"""
        print(f"🚀 Starting scrape for {self.store_name} (limit: {limit})")

        try:
            async with async_playwright() as p:
                print("▶️ Launching browser...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                print("▶️ Loading search page...")
                await page.goto(self.gunpla_url, wait_until="networkidle")

                print("▶️ Waiting for prices to load...")
                await page.wait_for_selector('[id$="_price"]', timeout=10000)  # Comet: div#{SKU}_price
                await asyncio.sleep(3)  # Extra time for stock

                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Comet fix: Main container → child groups
                test_container = soup.select_one('div#test')
                if not test_container:
                    print("⚠️ No #test container found")
                    await browser.close()
                    return []
                
                # Comet: Group every 6 children into product cards
                children = test_container.find_all(recursive=False)
                products = []
                for i in range(0, len(children), 6):
                    card_html = ''.join(str(child) for child in children[i:i+6])
                    card_soup = BeautifulSoup(card_html, 'html.parser')
                    products.append(card_soup)
                
                products = products[:limit * 2]  # Buffer for valid cards

                if not products:
                    print("⚠️ No products found")
                    await browser.close()
                    return []

                print(f"Found {len(products)} potential cards")
                print("📊 Fetching details for products...")

                results = []
                for idx, product in enumerate(products, 1):
                    try:
                        print(f"\n[{idx}/{len(products)}] Processing card...")
                        
                        product_data = self.parse_product(product)
                        
                        if (product_data and 
                            product_data["product"]["product_name"] != "Unknown" and
                            product_data["product"]["sku"] != "Unknown"):
                            
                            product_url = product_data["price"]["product_url"]
                            print(f"  ➡️ Fetching details from: {product_url}")

                            details = await self.scrape_product_details(page, product_url)
                            product_data["details"] = details

                            # Database save
                            product_id = self.save_product(product_data['product'])
                            if product_id: 
                                self.save_price(product_id, product_data['price'])

                            results.append(product_data)
                            print(f"  ✅ {product_data['product']['sku']}: {product_data['price']['stock_status']}")
                            
                            if len(results) >= limit:
                                break
                                
                            await asyncio.sleep(1)

                    except Exception as e:
                        print(f"  ⚠️ Failed card {idx}: {e}")
                        continue

                await browser.close()

                print(f"\n✅ Scraped {len(results)} products from {self.store_name}")
                return results

        except Exception as e:
            print(f"âŒ Scrape failed for {self.store_name}: {e}")
            import traceback
            traceback.print_exc()
            raise


    async def scrape_product_details(self, page, product_url: str) -> Dict:
        """Scrape detailed product information from detail page"""
        try:
            await page.goto(product_url, wait_until="networkidle")
            await asyncio.sleep(1)

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            details = {
                "code": self.extract_code(soup, product_url),
                "jan_code": self.extract_jan_code(soup),
                "release_date": self.extract_release_date(soup),
                "category": self.extract_category(soup),
                "series": self.extract_series(soup),
                "description": self.extract_description(soup),
                "includes": self.extract_includes(soup),
                "country_of_origin": self.extract_country_of_origin(soup),
                "manufacturer": self.extract_manufacturer(soup),
                "dimensions": self.extract_dimensions(soup),
                "weight": self.extract_weight(soup),
                "item_type": self.extract_item_type(soup),
                "cancellation_deadline": self.extract_cancellation_deadline(soup),
            }

            print(f"  âœ… Code={details['code']}, JAN={details['jan_code']}, Mfr={details['manufacturer']}")

            return details

        except Exception as e:
            print(f"  âš ï¸ Failed to fetch details: {e}")
            return self.get_empty_details()

    def get_empty_details(self) -> Dict:
        """Return empty details structure"""
        return {
            "code": None, "jan_code": None, "release_date": None, "category": None,
            "series": None, "description": None, "includes": None, "country_of_origin": None,
            "manufacturer": None, "dimensions": None, "weight": None, "item_type": None,
            "cancellation_deadline": None,
        }

    def extract_code(self, soup: BeautifulSoup, product_url: str = None) -> str:
        """Extract product code"""
        try:
            code_elem = soup.find(string=re.compile(HLJPatterns.CODE_TEXT, re.IGNORECASE))  # UPDATED
            if code_elem:
                parent = code_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.CODE_TEXT, text)  # UPDATED
                    if match:
                        return match.group(1)

            if product_url:
                url_parts = product_url.rstrip('/').split('/')
                last_segment = url_parts[-1] if url_parts else ""
                match = re.search(HLJPatterns.CODE_URL, last_segment, re.IGNORECASE)  # UPDATED
                if match:
                    return match.group(1).upper()

        except Exception as e:
            print(f"    âš ï¸ Code extraction failed: {e}")
        return None

    def extract_jan_code(self, soup: BeautifulSoup) -> str:
        """Extract JAN code"""
        try:
            jan_elem = soup.find(string=re.compile(HLJPatterns.JAN_CODE, re.IGNORECASE))  # UPDATED
            if jan_elem:
                parent = jan_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.JAN_CODE, text)  # UPDATED
                    if match:
                        return match.group(1)
        except Exception as e:
            print(f"    âš ï¸ JAN extraction failed: {e}")
        return None

    def extract_release_date(self, soup: BeautifulSoup) -> str:
        """Extract release date"""
        try:
            date_elem = soup.find(string=re.compile(HLJPatterns.RELEASE_DATE, re.IGNORECASE))  # UPDATED
            if date_elem:
                parent = date_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.RELEASE_DATE, text)  # UPDATED
                    if match:
                        return match.group(1).strip()
        except Exception as e:
            print(f"    âš ï¸ Release date extraction failed: {e}")
        return None

    def extract_category(self, soup: BeautifulSoup) -> str:
        """Extract category"""
        try:
            cat_elem = soup.find(string=re.compile(HLJPatterns.CATEGORY_LABEL, re.IGNORECASE))  # UPDATED
            if cat_elem:
                parent = cat_elem.find_parent()
                if parent:
                    link = parent.find_next('a')
                    if link:
                        return link.get_text(strip=True)
        except Exception as e:
            print(f"    âš ï¸ Category extraction failed: {e}")
        return None

    def extract_series(self, soup: BeautifulSoup) -> List[str]:
        """Extract series information"""
        try:
            series_elem = soup.find(string=re.compile(HLJPatterns.SERIES_LABEL, re.IGNORECASE))  # UPDATED
            if series_elem:
                parent = series_elem.find_parent()
                if parent:
                    links = parent.find_all('a')
                    if links:
                        return [link.get_text(strip=True) for link in links]
        except Exception as e:
            print(f"    âš ï¸ Series extraction failed: {e}")
        return []

    def extract_description(self, soup: BeautifulSoup) -> str:
        """Extract product description"""
        try:
            desc_header = soup.find('h2', string=re.compile(HLJPatterns.DESCRIPTION_LABEL, re.IGNORECASE))  # UPDATED
            if desc_header:
                desc_elem = desc_header.find_next(['p', 'div'])
                if desc_elem:
                    return desc_elem.get_text(strip=True)
        except Exception as e:
            print(f"    âš ï¸ Description extraction failed: {e}")
        return None

    def extract_includes(self, soup: BeautifulSoup) -> List[str]:
        """Extract includes list"""
        try:
            includes_elem = soup.find(string=re.compile(HLJPatterns.INCLUDES_LABEL, re.IGNORECASE))  # UPDATED
            if includes_elem:
                parent = includes_elem.find_parent()
                if parent:
                    ul = parent.find_next('ul')
                    if ul:
                        items = ul.find_all('li')
                        return [item.get_text(strip=True) for item in items]
        except Exception as e:
            print(f"    âš ï¸ Includes extraction failed: {e}")
        return []

    def extract_country_of_origin(self, soup: BeautifulSoup) -> str:
        """Extract country of origin"""
        try:
            country_elem = soup.find(string=re.compile(HLJPatterns.COUNTRY_LABEL, re.IGNORECASE))  # UPDATED
            if country_elem:
                parent = country_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.COUNTRY_LABEL + r'\s*(.+?)(?:\s|$)', text)
                    if match:
                        return match.group(1).strip()
        except Exception as e:
            print(f"    âš ï¸ Country extraction failed: {e}")
        return None

    def extract_manufacturer(self, soup: BeautifulSoup) -> str:
        """Extract manufacturer"""
        try:
            mfr_elem = soup.find(string=re.compile(HLJPatterns.MANUFACTURER_LABEL, re.IGNORECASE))  # UPDATED
            if mfr_elem:
                parent = mfr_elem.find_parent()
                if parent:
                    link = parent.find_next('a')
                    if link:
                        return link.get_text(strip=True)
        except Exception as e:
            print(f"    âš ï¸ Manufacturer extraction failed: {e}")
        return None

    def extract_dimensions(self, soup: BeautifulSoup) -> str:
        """Extract item dimensions"""
        try:
            size_elem = soup.find(string=re.compile(HLJPatterns.ITEM_SIZE_LABEL, re.IGNORECASE))  # UPDATED
            if size_elem:
                parent = size_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.DIMENSIONS, text)  # UPDATED
                    if match:
                        return match.group(1).strip()
        except Exception as e:
            print(f"    âš ï¸ Dimensions extraction failed: {e}")
        return None

    def extract_weight(self, soup: BeautifulSoup) -> str:
        """Extract item weight"""
        try:
            size_elem = soup.find(string=re.compile(HLJPatterns.ITEM_SIZE_LABEL, re.IGNORECASE))  # UPDATED
            if size_elem:
                parent = size_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.WEIGHT, text)  # UPDATED
                    if match:
                        return match.group(1).strip()
        except Exception as e:
            print(f"    âš ï¸ Weight extraction failed: {e}")
        return None

    def extract_item_type(self, soup: BeautifulSoup) -> str:
        """Extract item type"""
        try:
            type_elem = soup.find(string=re.compile(HLJPatterns.ITEM_TYPE_LABEL, re.IGNORECASE))  # UPDATED
            if type_elem:
                parent = type_elem.find_parent()
                if parent:
                    link = parent.find_next('a')
                    if link:
                        return link.get_text(strip=True)
        except Exception as e:
            print(f"    âš ï¸ Item Type extraction failed: {e}")
        return None

    def extract_cancellation_deadline(self, soup: BeautifulSoup) -> str:
        """Extract cancellation deadline"""
        try:
            cancel_elem = soup.find(string=re.compile(HLJPatterns.CANCELLATION_DEADLINE, re.IGNORECASE))  # UPDATED
            if cancel_elem:
                parent = cancel_elem.find_parent()
                if parent:
                    text = parent.get_text(strip=True)
                    match = re.search(HLJPatterns.CANCELLATION_DEADLINE, text)  # UPDATED
                    if match:
                        return match.group(1).strip()
        except Exception as e:
            print(f"    âš ï¸ Cancellation deadline extraction failed: {e}")
        return None

def parse_product(self, product_element) -> Dict:  # product_element is now from div#test children
    # 1. SKU first (from price ID)
    price_elem = product_element.select_one('div[id$="_price"]')
    sku = price_elem['id'].replace('_price', '') if price_elem and price_elem.get('id') else "Unknown"
    
    # 2. Name: 2nd <a> link per card (below image)
    name_elems = product_element.select('a[href*="hlj.com/"]')
    name_elem = name_elems[1] if len(name_elems) > 1 else name_elems[0] if name_elems else None
    name_text = name_elem.text.strip() if name_elem else "Unknown"
    product_url = self.base_url + name_elem['href'] if name_elem else self.gunpla_url
    
    # 3. Price: inner text of #{SKU}_price
    price_text = price_elem.get_text(strip=True) if price_elem else ""
    
    # 4. Image: first img
    img_elem = product_element.select_one('img')
    image_url = img_elem['src'] if img_elem else None
    
    # 5. Granular stock: #{SKU}_stockStatusDetail children
    stock_detail_elem = product_element.select_one(f'div[id="{sku}_stockStatusDetail"]')
    if stock_detail_elem:
        children = stock_detail_elem.select('> *')
        stock_left = children[0].get_text(strip=True) if len(children) > 0 else ""
        order_now = children[-1].get_text(strip=True) if len(children) > 1 else ""
        raw_status = f"{stock_left} {order_now}".strip()
    else:
        raw_status = ""
    
    granular_status = self.parse_hlj_status(raw_status)
    
    # 6. On-sale: #{SKU}_sell non-empty
    sell_elem = product_element.select_one(f'div[id="{sku}_sell"]')
    is_on_sale = bool(sell_elem and sell_elem.get_text(strip=True))
    
    parsed_price = self.parse_price(price_text)
    
    return {
        "product": {
            "product_name": name_text,
            "sku": sku,
            "brand": "Unknown",
            "grade": "Unknown",
            "scale": "Unknown",
            "image_url": image_url,
            "on_sale": is_on_sale,
        },
        "price": {
            "price": parsed_price,
            "currency": "PHP",
            "stock_status": granular_status,  # "Limited Stock: 3 left"
            "product_url": product_url,
        },
    }

    def parse_price(self, price_text: str) -> float:
        """Extract numeric price from text"""
        if not price_text:
            return None
        cleaned = re.sub(r"[^\d.]", "", price_text)
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None



