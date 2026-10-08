"""Walk-forward simulation using the exact scan/daily engine on sliced history. LLM off, Slack off."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from .config import Config
from .data import DataProvider
from .llm import LLM
from .paper import PaperBook
from .pipeline import run_daily, run_scan

log = logging.getLogger(__name__)


class SlicedProvider:
    def __init__(self, full: dict[str, pd.DataFrame], upto: pd.Timestamp):
        self.full, self.upto = full, upto

    def history(self, symbols, period="1y"):
        return {s: self.full[s][self.full[s].index <= self.upto] for s in symbols if s in self.full
                and len(self.full[s][self.full[s].index <= self.upto]) >= 200}


def simulate(provider: DataProvider, cfg: Config, book: PaperBook, days: int = 120,
             scan_weekdays: tuple[int, ...] = (1, 4)) -> dict:
    """Scan on Tue/Fri closes (mirrors Tue/Sat schedule), run the book every bar."""
    cfg.llm_enabled = False
    full = provider.history(cfg.universe, "2y")
    idx = sorted(set().union(*(df.index for df in full.values())))
    idx = [t for t in idx if t >= pd.Timestamp(date.today()) - pd.Timedelta(days=days * 1.5)][-days:]
    llm = LLM(cfg)
    for ts in idx:
        p = SlicedProvider(full, ts)
        run_daily(p, cfg, book, ts.date(), notify=False)
        if ts.weekday() in scan_weekdays:
            run_scan(p, cfg, book, llm, ts.date(), notify=False)
    return book.stats()
