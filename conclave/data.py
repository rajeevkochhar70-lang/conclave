from __future__ import annotations

import logging
from typing import Protocol

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

COLS = ["open", "high", "low", "close", "volume"]


class DataProvider(Protocol):
    def history(self, symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]: ...


class YFinanceProvider:
    def history(self, symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        import yfinance as yf

        raw = yf.download(symbols, period=period, group_by="ticker", auto_adjust=True,
                          threads=True, progress=False)
        out: dict[str, pd.DataFrame] = {}
        for s in symbols:
            try:
                df = raw[s] if len(symbols) > 1 else raw
                df = df.rename(columns=str.lower)[COLS].dropna()
                if len(df) >= 120:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    out[s] = df
                else:
                    log.warning("%s: only %d bars, skipped", s, len(df))
            except Exception as e:  # noqa: BLE001
                log.warning("%s: fetch failed: %s", s, e)
        return out


class SyntheticProvider:
    """Deterministic OHLCV for tests and offline dry runs. Trend per symbol via seed."""

    def __init__(self, seed: int = 7, bars: int = 260, trends: dict[str, float] | None = None,
                 end: str | None = None):
        self.seed, self.bars, self.trends, self.end = seed, bars, trends or {}, end

    def history(self, symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        out = {}
        idx = pd.bdate_range(end=self.end or pd.Timestamp.today().normalize(), periods=self.bars)
        for i, s in enumerate(symbols):
            rng = np.random.default_rng(self.seed + i)
            drift = self.trends.get(s, rng.choice([-0.0008, 0.0002, 0.0012]))
            rets = rng.normal(drift, 0.015, self.bars)
            close = 100 * np.exp(np.cumsum(rets))
            spread = np.abs(rng.normal(0.01, 0.004, self.bars)) * close
            open_ = close * (1 + rng.normal(0, 0.004, self.bars))
            high = np.maximum(open_, close) + spread
            low = np.minimum(open_, close) - spread
            vol = rng.integers(1_000_000, 5_000_000, self.bars).astype(float)
            vol[-3:] *= 1.8
            out[s] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                                   "volume": vol}, index=idx)
        return out
