"""APScheduler: daily book update Mon-Fri 13:30 PT (after close), desk scan Tue + Sat 19:30 PT."""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Config
from .llm import LLM
from .notify import slack
from .paper import PaperBook
from .pipeline import run_daily, run_scan

log = logging.getLogger(__name__)
TZ = "America/Vancouver"
MAX_WAIT_SECONDS = 60


class WallClockScheduler(BlockingScheduler):
    """Re-reads the wall clock at least every MAX_WAIT_SECONDS. Windows wait timeouts don't count time spent
    suspended, so one long wait toward the next job returns late by however long the machine slept —
    SUMMIT-Sleep's 18:30 ET suspend lasted 4h26m on 2026-10-20 and the 19:30 PT scan fired 4h26m late and was
    dropped (also scans 10-06/10-13, daily 10-06..10-22). Capping the wait makes due jobs fire within a minute
    of wake."""

    def _process_jobs(self) -> float:
        wait = super()._process_jobs()
        return MAX_WAIT_SECONDS if wait is None else min(wait, MAX_WAIT_SECONDS)


def _safe(name, fn, cfg):
    try:
        out = fn()
        log.info("%s done", name)
        return out
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", name)
        slack(cfg.slack_webhook, f":x: CONCLAVE {name} failed: {e}")


def _with_book(cfg: Config, fn):
    """Open the paper book in the thread that uses it. APScheduler runs jobs on worker threads and a
    sqlite3 connection can only be used by the thread that created it — a book opened once in start()
    made every scheduled run fail (2026-10-12..10-21)."""
    book = PaperBook(cfg.db_path, cfg.starting_equity)
    try:
        return fn(book)
    finally:
        book.con.close()


def build_scheduler(cfg: Config, provider, llm: LLM) -> BlockingScheduler:
    sched = WallClockScheduler(timezone=TZ)
    sched.add_job(lambda: _safe("daily", lambda: _with_book(cfg, lambda book: run_daily(provider, cfg, book)), cfg),
                  CronTrigger(day_of_week="mon-fri", hour=13, minute=30, timezone=TZ), id="daily",
                  misfire_grace_time=3600, coalesce=True)
    sched.add_job(lambda: _safe("scan", lambda: _with_book(cfg, lambda book: run_scan(provider, cfg, book, llm)),
                                cfg),
                  CronTrigger(day_of_week="tue,sat", hour=19, minute=30, timezone=TZ), id="scan",
                  misfire_grace_time=3600, coalesce=True)
    return sched


def start(cfg: Config, provider):
    llm = LLM(cfg)
    sched = build_scheduler(cfg, provider, llm)
    log.info("scheduler started: daily Mon-Fri 13:30 PT, scan Tue/Sat 19:30 PT")
    slack(cfg.slack_webhook, "CONCLAVE scheduler online (paper mode)")
    sched.start()
