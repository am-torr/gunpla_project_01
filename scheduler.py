import asyncio
import os
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.scrapers.hobby_link_japan import HobbyLinkJapanScraper

# Configuration
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL', 'http://n8n:5678/webhook/gunpla-scraper')
SCRAPE_INTERVAL = int(os.getenv('SCRAPE_INTERVAL', 3600))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def scrape_and_post():
    try:
        logger.info('Starting scheduled scrape...')
        
        scraper = HobbyLinkJapanScraper()
        products = await scraper.scrape(limit=5)
        
        logger.info(f'Scraped {len(products)} products from {scraper.store_name}')
        
        payload = {
            'store': scraper.store_name,
            'scraped_at': datetime.now().isoformat(),
            'products': products
        }
        
        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=120
        )
        
        if response.status_code == 200:
            logger.info(f'Posted to n8n successfully!')
        else:
            logger.error(f'n8n returned {response.status_code}: {response.text}')
    
    except Exception as e:
        logger.error(f'Scraping failed: {str(e)}', exc_info=True)

def run_scraper_sync():
    asyncio.run(scrape_and_post())

async def main():
    scheduler = AsyncIOScheduler()
    
    scheduler.add_job(
        run_scraper_sync,
        'interval',
        seconds=SCRAPE_INTERVAL,
        id='scraper_job',
        name='Gunpla Price Scraper',
        replace_existing=True
    )
    
    logger.info(f'Scheduler started - running every {SCRAPE_INTERVAL} seconds ({SCRAPE_INTERVAL/3600:.1f} hours)')
    
    await scrape_and_post()
    
    scheduler.start()
    
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info('Shutting down scheduler...')
        scheduler.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
