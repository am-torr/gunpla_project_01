"""CLI entry point.

    python -m scripts.lowstock_agent --threshold 5 --limit 20
    python -m scripts.lowstock_agent --dry-run --input scripts/lowstock_agent/fixtures/sample_low_stock.json
"""
import argparse
import asyncio
import sys

from .config import settings
from .hlj_client import fetch_from_api, load_from_file
from .orchestrator import run


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="scripts.lowstock_agent")
    p.add_argument("--threshold", type=int, default=5, help="low-stock threshold for /low-stock")
    p.add_argument("--limit", type=int, default=None, help="process at most N items")
    p.add_argument("--input", type=str, default=None, help="read items from a JSON file instead of the API")
    p.add_argument("--dry-run", action="store_true", help="run everything but write nothing to Supabase")
    p.add_argument("--source-type", type=str, default=None, help="override dedup source_type (default 'hlj')")
    return p.parse_args(argv)


async def _main_async(args) -> int:
    if args.source_type:
        settings.DEDUP_SOURCE_TYPE = args.source_type

    if args.input:
        items = load_from_file(args.input)
        print(f"Loaded {len(items)} item(s) from {args.input}")
    else:
        items = await fetch_from_api(threshold=args.threshold)
        print(f"Fetched {len(items)} item(s) from {settings.HLJ_LOWSTOCK_URL}")

    if args.limit is not None:
        items = items[: args.limit]

    if not items:
        print("No items to process.")
        return 0

    await run(items, dry_run=args.dry_run)
    return 0


def main(argv=None) -> int:
    # Windows consoles default to cp1252; force UTF-8 so captions/symbols print.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
