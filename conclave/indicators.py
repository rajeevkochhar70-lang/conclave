from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hh, ll = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return -100 * (hh - df["close"]) / (hh - ll).replace(0, np.nan)


def zscore(s: pd.Series, n: int = 20) -> pd.Series:
    return (s - s.rolling(n).mean()) / s.rolling(n).std().replace(0, np.nan)


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    m, sd = s.rolling(n).mean(), s.rolling(n).std()
    return m - k * sd, m, m + k * sd


def enrich(df: pd.DataFrame, atr_n: int = 14, chand_n: int = 22, chand_k: float = 2.0) -> pd.DataFrame:
    """Sonic R dragon (EMA34 of highs/lows), EMA89 trend, Weinstein 30-week SMA, ATR, oscillators."""
    d = df.copy()
    d["dragon_hi"] = ema(d["high"], 34)
    d["dragon_lo"] = ema(d["low"], 34)
    d["dragon_mid"] = ema(d["close"], 34)
    d["ema21"] = ema(d["close"], 21)
    d["ema89"] = ema(d["close"], 89)
    d["ema200"] = ema(d["close"], 200)
    d["sma150"] = d["close"].rolling(150).mean()  # ~30 weeks
    d["atr"] = atr(d, atr_n)
    d["rsi"] = rsi(d["close"])
    d["willr"] = williams_r(d)
    d["zscore"] = zscore(d["close"])
    d["bb_lo"], d["bb_mid"], d["bb_hi"] = bollinger(d["close"])
    d["vol_avg20"] = d["volume"].rolling(20).mean()
    d["vol_ratio"] = d["volume"] / d["vol_avg20"]
    d["hi20"] = d["high"].rolling(20).max().shift(1)
    d["lo10"] = d["low"].rolling(10).min().shift(1)
    d["hi52"] = d["high"].rolling(252, min_periods=120).max()
    d["chandelier"] = d["high"].rolling(chand_n).max() - chand_k * d["atr"]
    d["ret20"] = d["close"].pct_change(20)
    d["ret60"] = d["close"].pct_change(60)
    d["ret120"] = d["close"].pct_change(120)
    return d


def weinstein_stage(d: pd.DataFrame) -> int:
    """1 basing, 2 advancing, 3 topping, 4 declining — from price vs 30-wk SMA and its slope."""
    last = d.iloc[-1]
    sma, sma_prev = last["sma150"], d["sma150"].iloc[-21]
    if np.isnan(sma) or np.isnan(sma_prev):
        return 0
    rising = sma > sma_prev
    above = last["close"] > sma
    if above and rising:
        return 2
    if above and not rising:
        return 3
    if not above and not rising:
        return 4
    return 1


def vcp_score(d: pd.DataFrame) -> float:
    """0-1: successive 10-bar ranges contracting over the last 30 bars."""
    rng = ((d["high"] - d["low"]) / d["close"]).rolling(10).mean()
    a, b, c = rng.iloc[-21], rng.iloc[-11], rng.iloc[-1]
    if any(np.isnan(x) for x in (a, b, c)) or a <= 0:
        return 0.0
    return float(np.clip(1 - c / a, 0, 1)) if c < b < a else 0.0
