"""Risk Manager: sizing, open-trade cap, weekly per-entity circuit breaker. Pure functions + book."""
from __future__ import annotations

import math
from datetime import date

from .config import Config
from .paper import PaperBook


def position_size(equity: float, risk_pct: float, entry: float, stop: float) -> tuple[int, float]:
    per_share = entry - stop
    if per_share <= 0:
        return 0, 0.0
    qty = math.floor(equity * risk_pct / per_share)
    return qty, round(qty * per_share, 2)


def gate(book: PaperBook, cfg: Config, entity: str, today: date, extra_pending: int = 0) -> tuple[bool, str]:
    """Can we add a new trade in this entity today?"""
    if book.breaker_tripped(entity, today, cfg.max_losers_per_week):
        return False, f"circuit breaker: {entity} has {book.week_losers(entity, today)} losers this week"
    slots = cfg.max_open_trades - book.open_count() - len(book.pending_signals()) - extra_pending
    if slots <= 0:
        return False, f"max open trades ({cfg.max_open_trades}) reached incl. pending"
    return True, f"{slots} slot(s) free"


def breaker_status(book: PaperBook, cfg: Config, today: date) -> dict[str, dict]:
    return {e: {"losers_this_week": book.week_losers(e, today),
                "tripped": book.breaker_tripped(e, today, cfg.max_losers_per_week)} for e in ("stock", "etf")}
