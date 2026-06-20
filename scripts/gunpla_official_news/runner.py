"""Run all source scrapers, dedupe, emit JSON to stdout."""
from __future__ import annotations

import importlib
import json
import logging
import sys

from .config import SOURCES
from .dedupe import dedupe
from .models import NewsItem

log = logging.getLogger("gunpla_official_news")


def _setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def run() -> list[NewsItem]:
    all_items: list[NewsItem] = []
    for module_path in SOURCES:
        try:
            mod = importlib.import_module(module_path)
            scraper = mod.Scraper()
            log.info("Collecting: %s", scraper.source_name)
            items = scraper.collect()
            log.info("  -> %d items", len(items))
            all_items.extend(items)
        except Exception as e:
            log.error("Source %s failed: %s", module_path, e)
    return dedupe(all_items)


def main() -> int:
    _setup_logging()
    items = run()
    log.info("Total after dedupe: %d", len(items))
    json.dump([i.to_dict() for i in items], sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
