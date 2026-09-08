"""Scheduled runner for the gunpla news pipeline (AC6).

Mirrors ``scripts/lowstock_agent/scheduler.py``'s existing APScheduler pattern
(``AsyncIOScheduler``, an interval-based tick, an overlap guard, structured
logging) exactly -- same shape, new job. This is the *entire* answer to "no
Hermes-side changes": the schedule that used to live in Hermes' cron store now
lives here, native to ``gunpla-tracker-verified``, calling the pipeline and the
n8n pusher directly. Hermes' own cron config and its Discord-delivery code path
are never touched by this file or anything it imports.

Each tick: ``pipeline.run()`` / ``pipeline.run_fixtures()`` -> the three output
files under ``output/`` -> :func:`n8n_push.push_report`. A push failure can
never fail the tick (:mod:`n8n_push` is fail-soft by contract); a pipeline
failure is caught here and logged, exactly like lowstock's ``run_once()``.

Run it::

    python -m gunpla_official_news.scheduler
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import n8n_push, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gunpla-official-news.scheduler")

# ---------------------------------------------------------------------------
# Config -- plain os.environ reads, matching this package's existing style
# (config.py is a pre-existing/untouched file from the reference project --
# see CONTRACT-NOTES.md -- so new config lives here rather than being added
# to it). Pulled into a pure function of an explicit mapping so tests can
# exercise every combination without mutating real process env vars or
# reload()-ing this module.
# ---------------------------------------------------------------------------

_TRUE_STRINGS = ("1", "true", "yes")


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_STRINGS


@dataclass(frozen=True)
class SchedulerConfig:
    interval_hours: float
    run_on_start: bool
    output_dir: Path
    use_fixtures: bool


def load_config(env: Optional[Mapping[str, str]] = None) -> SchedulerConfig:
    """Resolve scheduler config from ``env`` (defaults to the real process env)."""
    env = os.environ if env is None else env
    return SchedulerConfig(
        interval_hours=float(env.get("GUNPLA_NEWS_RUN_INTERVAL_HOURS", "24")),
        run_on_start=_env_bool(env, "GUNPLA_NEWS_RUN_ON_START", False),
        output_dir=Path(env.get("GUNPLA_NEWS_OUTPUT_DIR", "output")),
        use_fixtures=_env_bool(env, "GUNPLA_NEWS_USE_FIXTURES", False),
    )


CONFIG = load_config()
#: How often the scheduled runner fires. Mirrors lowstock's RUN_INTERVAL_HOURS.
RUN_INTERVAL_HOURS = CONFIG.interval_hours
#: Also run once immediately on start. Mirrors lowstock's RUN_ON_START.
RUN_ON_START = CONFIG.run_on_start
#: Where pipeline outputs land.
OUTPUT_DIR = CONFIG.output_dir
#: Use the bundled fixture source set instead of live HTTP (safe local default).
USE_FIXTURES = CONFIG.use_fixtures

_running = False  # simple guard so overlapping ticks don't stack (mirrors lowstock's scheduler.py)


def _new_job_id() -> str:
    return "gunpla-news-%s" % uuid.uuid4().hex[:12]


async def run_once() -> None:
    """One scheduled tick: run the pipeline, then push its output to n8n."""
    global _running
    if _running:
        log.warning("previous run still in progress -- skipping this tick")
        return
    _running = True
    try:
        date = datetime.now(timezone.utc).date().isoformat()
        log.info("run start (date=%s fixtures=%s)", date, USE_FIXTURES)
        run_fn = pipeline.run_fixtures if USE_FIXTURES else pipeline.run
        report = await asyncio.to_thread(run_fn, output_dir=OUTPUT_DIR, date=date)
        log.info(
            "run done: %s article(s), %s row(s), outputs=%s",
            report.articles,
            report.rows,
            list(report.outputs.keys()),
        )

        run_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            n8n_push.push_report, report, job_id=_new_job_id(), run_at=run_at
        )
    except Exception:
        log.exception("scheduled run failed")
    finally:
        _running = False


async def main() -> None:
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(
        run_once,
        "interval",
        hours=RUN_INTERVAL_HOURS,
        next_run_time=datetime.now(timezone.utc) if RUN_ON_START else None,
        id="gunpla-news-run",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    log.info(
        "scheduler started -- every %.1f h (run_on_start=%s, fixtures=%s)",
        RUN_INTERVAL_HOURS,
        RUN_ON_START,
        USE_FIXTURES,
    )
    # Keep the event loop alive.
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
