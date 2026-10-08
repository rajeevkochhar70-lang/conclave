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


def _safe(name, fn, cfg):
    try:
        out = fn()
        log.info("%s done", name)
        return out
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", name)
        slack(cfg.slack_webhook, f":x: CONCLAVE {name} failed: {e}")


def start(cfg: Config, provider):
    book = PaperBook(cfg.db_path, cfg.starting_equity)
    llm = LLM(cfg)
    sched = BlockingScheduler(timezone=TZ)
    sched.add_job(lambda: _safe("daily", lambda: run_daily(provider, cfg, book), cfg),
                  CronTrigger(day_of_week="mon-fri", hour=13, minute=30, timezone=TZ), id="daily")
    sched.add_job(lambda: _safe("scan", lambda: run_scan(provider, cfg, book, llm), cfg),
                  CronTrigger(day_of_week="tue,sat", hour=19, minute=30, timezone=TZ), id="scan")
    log.info("scheduler started: daily Mon-Fri 13:30 PT, scan Tue/Sat 19:30 PT")
    slack(cfg.slack_webhook, "CONCLAVE scheduler online (paper mode)")
    sched.start()
