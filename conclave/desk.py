"""The desk: Bull, Bear, Independent Review, Chief. Scores are Python; LLM only writes prose.

Chief output per symbol: a Signal (or no trade) with entry/stop/trail/target computed from structure.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from .config import Config
from .llm import LLM, check_numbers

log = logging.getLogger(__name__)

SYSTEM = ("You are an analyst on a research desk. Write 2-3 plain sentences. Use ONLY the numbers "
          "given in the facts; never compute or invent new figures. No advice, no hedging boilerplate.")


@dataclass
class Signal:
    symbol: str
    entity: str
    side: str
    entry: float
    stop: float
    trail: float
    target: float
    rr: float
    conviction: str
    score: int
    setup: str
    trade_type: str
    bull: list[str] = field(default_factory=list)
    bear: list[str] = field(default_factory=list)
    review: str = ""
    brief: str = ""
    model: str | None = None
    flagged_numbers: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def bull_case(t: dict, act: dict, rs: dict) -> tuple[int, list[str]]:
    pts, why = 0, []
    if t["stage"] == 2:
        pts += 20; why.append(f"Weinstein Stage 2: close {t['close']} above rising 30-wk SMA {t['sma150']}")
    if t["above_dragon"] and t["ema89_rising"]:
        pts += 15; why.append(f"Sonic R: price above dragon ({t['dragon_lo']}-{t['dragon_hi']}), EMA89 {t['ema89']} rising")
    if t["pullback_setup"]:
        pts += 15; why.append("Pullback to dragon with bounce — preferred Sonic R entry")
    if t["breakout"]:
        pts += 12; why.append(f"Breakout above 20-day high {t['hi20']} on {t['vol_ratio']}x volume")
    if (rs.get("rs_60") or 0) > 0:
        pts += 10; why.append(f"Outperforming SPY by {rs['rs_60']}% over 60 days")
    if (act["up_down_vol_ratio"] or 0) > 1.2:
        pts += 8; why.append(f"Accumulation: up/down volume ratio {act['up_down_vol_ratio']}")
    if (t["vcp"] or 0) > 0.3:
        pts += 10; why.append(f"VCP contraction score {t['vcp']}")
    if t["rsi"] and 50 <= t["rsi"] <= 70:
        pts += 5; why.append(f"RSI {t['rsi']} in trend zone")
    if t["willr"] is not None and -50 <= t["willr"] <= -10:
        pts += 5; why.append(f"Williams %R {t['willr']} confirms strength without exhaustion")
    return pts, why


def bear_case(t: dict, act: dict, rs: dict) -> tuple[int, list[str]]:
    pts, why = 0, []
    if t["stage"] in (3, 4):
        pts += 25; why.append(f"Weinstein Stage {t['stage']} — not a buy stage")
    if not t["above_ema200"]:
        pts += 15; why.append(f"Below EMA200 {t['ema200']}")
    if t["rsi"] and t["rsi"] > 75:
        pts += 12; why.append(f"RSI {t['rsi']} overbought")
    if t["willr"] is not None and t["willr"] > -10:
        pts += 8; why.append(f"Williams %R {t['willr']} — extended")
    if (t["zscore"] or 0) > 2:
        pts += 10; why.append(f"Z-score {t['zscore']} — stretched vs 20-day mean")
    if (t["pct_from_52w_high"] or 0) < -25:
        pts += 10; why.append(f"{t['pct_from_52w_high']}% below 52-week high")
    if (act["up_down_vol_ratio"] or 1) < 0.8:
        pts += 10; why.append(f"Distribution: up/down volume ratio {act['up_down_vol_ratio']}")
    if (t["atr_pct"] or 0) > 5:
        pts += 8; why.append(f"ATR {t['atr_pct']}% of price — wide stops, poor sizing")
    if (rs.get("rs_60") or 0) < -5:
        pts += 8; why.append(f"Lagging SPY by {abs(rs['rs_60'])}% over 60 days")
    return pts, why


def structure_levels(t: dict, cfg: Config) -> dict | None:
    """Entry at close, stop below dragon low / 10-bar low, chandelier trail, target in R."""
    entry = t["close"]
    struct = min(x for x in (t["dragon_lo"], t["lo10"]) if x is not None)
    stop = round(struct - 0.2 * t["atr"], 2)
    risk = entry - stop
    if risk <= 0 or risk > cfg.max_stop_atr * t["atr"]:
        return None
    target = round(entry + cfg.target_r * risk, 2)
    trail = round(max(stop, min(t["chandelier"], entry - t["atr"])), 2)  # initial trail never above entry
    return {"entry": entry, "stop": stop, "trail": trail, "target": target,
            "rr": round((target - entry) / risk, 2), "risk_atr": round(risk / t["atr"], 2)}


def review(bull_pts: int, bear_pts: int, levels: dict | None, t: dict) -> tuple[int, str, str]:
    """Independent review: net score, conviction, and what evidence is missing."""
    net = bull_pts - bear_pts
    gaps = []
    if not (t["pullback_setup"] or t["breakout"]):
        gaps.append("no trigger (neither dragon pullback nor volume breakout)")
    if levels is None:
        gaps.append("stop would exceed max ATR distance")
    elif levels["rr"] < 2:
        gaps.append(f"R:R {levels['rr']} below 2")
    if t["stage"] != 2:
        gaps.append("not Stage 2")
    triggered = t["pullback_setup"] or t["breakout"]
    conv = ("HIGH" if net >= 55 and not gaps else
            "MEDIUM" if net >= 35 and triggered and len(gaps) <= 1 else "LOW")
    note = "; ".join(gaps) if gaps else "no evidence gaps"
    return net, conv, note


def chief(symbol: str, entity: str, t: dict, act: dict, rs: dict, cfg: Config, llm: LLM,
          last_brief: dict | None = None) -> Signal | None:
    b_pts, b_why = bull_case(t, act, rs)
    r_pts, r_why = bear_case(t, act, rs)
    levels = structure_levels(t, cfg)
    net, conv, note = review(b_pts, r_pts, levels, t)
    if conv == "LOW" or levels is None:
        return None
    setup = "Sonic R pullback" if t["pullback_setup"] else "Volume breakout" if t["breakout"] else "Trend"
    trade_type = "Wealth" if entity == "etf" else "Swing"
    facts = {"symbol": symbol, "technical": t, "activity": act, "rs": rs, "levels": levels,
             "bull": b_why, "bear": r_why, "review": note, "score": net}
    memo = ""
    if last_brief:
        memo = (f" Since last brief on {last_brief['date']} (close {last_brief['close']}): "
                f"price moved {last_brief['move_pct']}%.")
        facts["since_last"] = last_brief
    brief = (f"{symbol} {setup}, {conv} conviction (net {net}). Entry {levels['entry']}, stop {levels['stop']} "
             f"({levels['risk_atr']} ATR), target {levels['target']} ({levels['rr']}R). "
             f"Bull: {b_why[0] if b_why else '-'}. Bear: {r_why[0] if r_why else '-'}. Review: {note}.{memo}")
    model, flagged = None, []
    text = llm.complete(SYSTEM, f"Facts:\n{facts}\n\nWrite the chief's brief for {symbol}.")
    if text:
        flagged = check_numbers(text, facts)
        model = llm.last_model
        if flagged:
            log.warning("%s: LLM used numbers not in facts %s — keeping template brief", symbol, flagged)
        else:
            brief = text + memo
    return Signal(symbol, entity, "LONG", levels["entry"], levels["stop"], levels["trail"], levels["target"],
                  levels["rr"], conv, net, setup, trade_type, b_why, r_why, note, brief, model, flagged)
