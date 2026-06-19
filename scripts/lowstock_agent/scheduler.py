"""Scheduled runner — turns the on-demand CLI into a long-running service.

Fires the pipeline every RUN_INTERVAL_HOURS against the hlj-lowstock service.
Mirrors the project's existing scheduler.py (APScheduler) pattern. Runs as the
`lowstock-agent` container in docker-compose.

Still respects the hard boundary: writes only to agent_drafts + price_history.
"""
import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .hlj_client import fetch_from_api
from .orchestrator import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lowstock-agent")

_running = False  # simple guard so overlapping ticks don't stack


async def run_once() -> None:
    global _running
    if _running:
        log.warning("previous run still in progress — skipping this tick")
        return
    _running = True
    try:
        log.info("run start (threshold=%s limit=%s)", settings.RUN_THRESHOLD, settings.RUN_LIMIT)
        items = await fetch_from_api(threshold=settings.RUN_THRESHOLD)
        if settings.RUN_LIMIT:
            items = items[: settings.RUN_LIMIT]
        if not items:
            log.info("no items returned; nothing to do")
            return
        stats = await run(items, dry_run=False)
        log.info("run done: %s drafts written, %s qualified", stats.written, stats.qualified)
    except Exception:
        log.exception("scheduled run failed")
    finally:
        _running = False


async def main() -> None:
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(
        run_once,
        "interval",
        hours=settings.RUN_INTERVAL_HOURS,
        next_run_time=datetime.now(timezone.utc) if settings.RUN_ON_START else None,
        id="lowstock-run",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    log.info("scheduler started — every %.1f h (run_on_start=%s)",
             settings.RUN_INTERVAL_HOURS, settings.RUN_ON_START)
    # Keep the event loop alive.
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
