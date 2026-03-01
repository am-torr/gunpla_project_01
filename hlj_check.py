import asyncio
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Visible for debug
        page = await browser.new_page()
        await page.goto('https://www.hlj.com/search/?Word=gunpla', wait_until='networkidle')
        logger.info(f"Page title: {await page.title()}")
        
        # Flexible price/card selectors
        try:
            await page.wait_for_selector('text=/price/i, [class*="price"], [data-price], .product-price, [id$="_price"]', timeout=20000)
            logger.info("Price selector found")
        except Exception as e:
            logger.error(f"Selector timeout: {e}")
            await page.screenshot(path="hlj_debug.png")
            html = await page.content()
            with open("hlj_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            logger.debug(f"HTML saved, len: {len(html)}")
            return
        
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Cards (update to real)
        cards = soup.select('.product-item, .search-result-item, [data-product], article')
        logger.info(f"Found {len(cards)} potential cards")
        for i, card in enumerate(cards[:3]):
            title = card.get('title') or card.find('h3') or card.find('.title')
            price = card.select_one('[class*="price"], .amount')
            logger.debug(f"Card {i}: title='{title}', price={price}")
        
        # Legacy checks
        test_div = soup.select_one('div#test')
        logger.debug(f'div#test: {test_div is not None}')
        prices = soup.select('[id$="_price"]')
        logger.info(f'Legacy prices: {len(prices)}')
        
        await browser.close()

asyncio.run(check())
