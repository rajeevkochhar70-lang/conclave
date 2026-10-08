"""Specialist agents: each returns a dict of Python-computed facts for one symbol. No LLM here."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .indicators import enrich, vcp_score, weinstein_stage


def _f(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def technical(df: pd.DataFrame, cfg) -> dict:
    d = enrich(df, cfg.atr_period, cfg.chandelier_lookback, cfg.chandelier_mult)
    last, prev = d.iloc[-1], d.iloc[-2]
    close, a = float(last["close"]), float(last["atr"])
    above_dragon = close > last["dragon_hi"]
    in_dragon = last["dragon_lo"] <= close <= last["dragon_hi"]
    ema89_rising = last["ema89"] > d["ema89"].iloc[-6]
    breakout = close > last["hi20"] and last["vol_ratio"] >= 1.5
    pullback = in_dragon or (above_dragon and (close - last["dragon_hi"]) <= 1.0 * a and prev["close"] < close)
    stage = weinstein_stage(d)
    return {
        "close": _f(close), "atr": _f(a), "atr_pct": _f(a / close * 100, 1),
        "dragon_hi": _f(last["dragon_hi"]), "dragon_lo": _f(last["dragon_lo"]),
        "ema21": _f(last["ema21"]), "ema89": _f(last["ema89"]), "ema200": _f(last["ema200"]),
        "sma150": _f(last["sma150"]), "stage": stage,
        "rsi": _f(last["rsi"], 1), "willr": _f(last["willr"], 1), "zscore": _f(last["zscore"]),
        "bb_hi": _f(last["bb_hi"]), "bb_lo": _f(last["bb_lo"]),
        "vol_ratio": _f(last["vol_ratio"]), "hi20": _f(last["hi20"]), "lo10": _f(last["lo10"]),
        "hi52": _f(last["hi52"]), "pct_from_52w_high": _f((close / last["hi52"] - 1) * 100, 1),
        "chandelier": _f(last["chandelier"]), "vcp": _f(vcp_score(d)),
        "ret20_pct": _f(last["ret20"] * 100, 1), "ret60_pct": _f(last["ret60"] * 100, 1),
        "ret120_pct": _f(last["ret120"] * 100, 1),
        "above_dragon": bool(above_dragon), "in_dragon": bool(in_dragon),
        "ema89_rising": bool(ema89_rising), "above_ema200": bool(close > last["ema200"]),
        "breakout": bool(breakout), "pullback_setup": bool(pullback),
        "bar_date": str(d.index[-1].date()),
    }


def activity(df: pd.DataFrame) -> dict:
    v = df["volume"]
    up_days = df["close"].diff().tail(20) > 0
    up_vol = float(v.tail(20)[up_days].sum())
    dn_vol = float(v.tail(20)[~up_days].sum())
    return {
        "vol_avg20": _f(v.tail(20).mean(), 0), "vol_avg50": _f(v.tail(50).mean(), 0),
        "up_down_vol_ratio": _f(up_vol / dn_vol if dn_vol else 9.99),
        "dollar_vol_m": _f((df["close"] * v).tail(20).mean() / 1e6, 1),
        "big_vol_days_20": int((v.tail(20) > 1.5 * v.tail(50).mean()).sum()),
    }


def relative_strength(df: pd.DataFrame, bench: pd.DataFrame | None) -> dict:
    if bench is None:
        return {"rs_20": None, "rs_60": None, "rs_rank_hint": None}
    j = df["close"].to_frame("s").join(bench["close"].rename("b"), how="inner")
    out = {}
    for n in (20, 60):
        if len(j) > n:
            out[f"rs_{n}"] = _f(((j["s"].iloc[-1] / j["s"].iloc[-1 - n]) / (j["b"].iloc[-1] / j["b"].iloc[-1 - n]) - 1) * 100, 1)
        else:
            out[f"rs_{n}"] = None
    return out


def screener_score(t: dict, act: dict, rs: dict) -> float:
    """Momentum / volume / RSI composite used to cut the universe to the top N."""
    s = 0.0
    s += np.clip((t["ret60_pct"] or 0) / 2, -10, 15)
    s += np.clip((rs.get("rs_60") or 0) / 2, -10, 10)
    s += 10 if t["stage"] == 2 else -10 if t["stage"] == 4 else 0
    s += 5 if t["above_dragon"] else 0
    s += 5 if t["ema89_rising"] else -5
    s += np.clip((act["up_down_vol_ratio"] or 1) * 3 - 3, -5, 6)
    r = t["rsi"] or 50
    s += 5 if 50 <= r <= 70 else -5 if r > 80 or r < 35 else 0
    s += 4 * (t["vcp"] or 0)
    return round(float(s), 2)
