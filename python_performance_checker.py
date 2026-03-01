# Profile single HLJ
python -c "
import cProfile, pstats
pr = cProfile.Profile()
pr.enable()
from app.scrapers.hobby_link_japan import HobbyLinkJapanScraper
import asyncio
async def test(): s = HobbyLinkJapanScraper(); await s.scrape(1)
asyncio.run(test())
pr.disable()
stats = pstats.Stats(pr)
stats.sort_stats('cumtime')
stats.print_stats(10)
"
