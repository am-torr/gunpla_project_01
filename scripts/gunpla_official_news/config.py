"""Configuration: HTTP, official domains, source registry."""
from __future__ import annotations

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 "
    "GunplaNewsCurator/0.1 (+contact: ops@example.com)"
)
DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.7",
}

# Hostnames considered official. Reject everything else at verification time.
OFFICIAL_DOMAINS = (
    "gundam.info",
    "en.gundam.info",
    "bandai-hobby.net",
    "p-bandai.com",
    "p-bandai.jp",
    "bandai.com",
    "gundam.net",
    "gundam-base.net",
)

# Source registry. Each scraper module exposes a `Scraper` class that the runner
# instantiates. Keep this list ordered by trust priority.
SOURCES = [
    "gunpla_official_news.sources.gundam_info",
    "gunpla_official_news.sources.bandai_hobby",
    "gunpla_official_news.sources.p_bandai",
    "gunpla_official_news.sources.bandai_news",
    "gunpla_official_news.sources.gundam_official",
]
