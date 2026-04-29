# POC — just Alyzeus
docker compose run --rm bandai-scraper python scraper.py poc

# All HG 2026 kits (all 9 list pages, HG-filtered)
docker compose run --rm bandai-scraper python scraper.py hg_2026

# Everything (all brands, all pages)
docker compose run --rm bandai-scraper python scraper.py all