"""Two entry points: run_scan (Tue/Sat desk run → queued signals) and run_daily (fills, stops, trails)."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd

from .config import Config
from .data import DataProvider
from .desk import Signal, chief
from .indicators import enrich, weinstein_stage
from .llm import LLM
from .notify import slack
from .paper import PaperBook
from .report import daily_report, scan_report
from .risk import breaker_status, gate, position_size
from .specialists import activity, relative_strength, screener_score, technical

log = logging.getLogger(__name__)


def market_context(hist: dict[str, pd.DataFrame], cfg: Config) -> dict:
    spy = hist.get("SPY")
    out = {}
    if spy is not None:
        d = enrich(spy)
        out["spy_ret20"] = round(float(d["ret20"].iloc[-1] * 100), 1)
        out["spy_stage"] = weinstein_stage(d)
    above = [float(enrich(df)["close"].iloc[-1] > enrich(df)["ema89"].iloc[-1]) for df in hist.values()]
    out["pct_above_ema89"] = round(sum(above) / len(above) * 100, 0) if above else None
    return out


def run_scan(provider: DataProvider, cfg: Config, book: PaperBook, llm: LLM | None = None,
             today: date | None = None, notify: bool = True) -> tuple[str, list[Signal]]:
    today = today or date.today()
    scan_date = today.isoformat()
    llm = llm or LLM(cfg)
    t0 = time.time()
    hist = provider.history(cfg.universe, cfg.history_period)
    bench = hist.get("SPY")
    book.log("data", "desk", f"fetched {len(hist)} symbols in {time.time() - t0:.1f}s", scan_date=scan_date)

    # Screener + specialists (all Python)
    cands = []
    for sym, df in hist.items():
        try:
            t, act = technical(df, cfg), activity(df)
            rs = relative_strength(df, bench if sym != "SPY" else None)
            cands.append((sym, screener_score(t, act, rs), t, act, rs))
        except Exception as e:  # noqa: BLE001
            log.warning("%s: specialist failed: %s", sym, e)
    cands.sort(key=lambda x: -x[1])
    top = cands[: cfg.screener_top_n]
    book.log("screener", "chief", "top: " + ", ".join(f"{s}({sc})" for s, sc, *_ in top), scan_date=scan_date)

    # Desk: bull / bear / review / chief per candidate
    signals: list[Signal] = []
    for sym, sc, t, act, rs in top:
        memo = book.last_brief(sym, t["close"])
        t1 = time.time()
        sig = chief(sym, cfg.entity_of(sym), t, act, rs, cfg, llm, memo)
        if sig:
            signals.append(sig)
            book.log("chief", "risk", sig.brief, sym, sig.model, int((time.time() - t1) * 1000), scan_date)
            book.save_brief(scan_date, sym, t["close"], sig.brief)
        else:
            book.log("review", "chief", f"{sym}: no trade (screener {sc}, stage {t['stage']})", sym,
                     scan_date=scan_date)
    signals.sort(key=lambda s: (-{"HIGH": 2, "MEDIUM": 1}[s.conviction], -s.score))

    # Risk manager: queue what fits
    book.expire_signals(scan_date)  # only the newest scan's pending signals survive
    queued, skipped, n_queued = [], {}, 0
    for s in signals:
        if book.has_exposure(s.symbol):
            skipped[s.symbol] = "already open"
            continue
        ok, why = gate(book, cfg, s.entity, today)  # pending count already includes what we just queued
        if not ok:
            skipped[s.symbol] = why
            continue
        book.add_signal(s.as_dict(), scan_date)
        queued.append(s.symbol)
        n_queued += 1
    br = breaker_status(book, cfg, today)
    for e, v in br.items():
        if v["tripped"]:
            book.event("circuit_breaker", e, f"{v['losers_this_week']} losers this week")
    report = scan_report(scan_date, signals, queued, skipped, br, book.open_count(), cfg.max_open_trades,
                         book.equity(), book.stats(), market_context(hist, cfg))
    book.log("report", "slack", report, scan_date=scan_date)
    if notify:
        slack(cfg.slack_webhook, report)
    return report, signals


def run_daily(provider: DataProvider, cfg: Config, book: PaperBook, today: date | None = None,
              notify: bool = True, hist: dict[str, pd.DataFrame] | None = None) -> str:
    """Process every unseen daily bar: fill pending at next open, then stops / targets / trails."""
    today = today or date.today()
    day = today.isoformat()
    syms = sorted({r["symbol"] for r in book.pending_signals()} | {r["symbol"] for r in book.open_positions()})
    fills, exits, trails = [], [], []
    if syms:
        hist = hist or provider.history(syms, "6mo")
        # expire signals older than 3 bars
        book.expire_signals((today - timedelta(days=5)).isoformat())

        for sig in book.pending_signals():
            df = hist.get(sig["symbol"])
            if df is None:
                continue
            bars = df[df.index > pd.Timestamp(sig["scan_date"])]
            if bars.empty:
                continue
            bar = bars.iloc[0]
            bdate = str(bars.index[0].date())
            o = float(bar["open"])
            ok, why = gate(book, cfg, sig["entity"], today, extra_pending=-1)  # itself is pending
            if not ok:
                book.set_signal_status(sig["id"], "blocked"); book.log("risk", "book", f"{sig['symbol']} blocked: {why}", sig["symbol"]); continue
            if o <= sig["stop"] or o >= sig["target"] or o > sig["entry"] * 1.03:
                book.set_signal_status(sig["id"], "missed"); book.log("book", "chief", f"{sig['symbol']} missed: open {o:.2f} outside entry window", sig["symbol"]); continue
            qty, risk_amt = position_size(book.equity(), cfg.risk_per_trade, o, sig["stop"])
            if qty < 1:
                book.set_signal_status(sig["id"], "too_small"); continue
            pid = book.open_position(sig, qty, o, bdate, risk_amt)
            fills.append(f"{sig['symbol']} {qty}@{o:.2f}")
            book.log("book", "slack", f"filled {sig['symbol']} {qty}@{o:.2f} risk ${risk_amt:.0f}", sig["symbol"])

        for pos in book.open_positions():
            df = hist.get(pos["symbol"])
            if df is None:
                continue
            d = enrich(df, cfg.atr_period, cfg.chandelier_lookback, cfg.chandelier_mult)
            new_bars = d[d.index > pd.Timestamp(pos["last_bar"])]
            trail, held, closed = float(pos["trail"]), int(pos["bars_held"]), False
            # Same-bar check on the fill bar: a fill at open can be stopped intraday.
            if held == 0:
                fill_bar = d[d.index == pd.Timestamp(pos["entry_date"])]
                new_bars = pd.concat([fill_bar, new_bars]) if not fill_bar.empty else new_bars
            for ts, b in new_bars.iterrows():
                bdate = str(ts.date())
                held += 1
                if float(b["open"]) <= trail:
                    px, reason = float(b["open"]), "gap below stop"
                elif float(b["low"]) <= trail:
                    px, reason = trail, "stop/trail"
                elif float(b["high"]) >= pos["target"]:
                    px, reason = float(pos["target"]), "target"
                elif held >= cfg.stale_bars and float(b["close"]) < pos["entry"]:
                    px, reason = float(b["close"]), "stale"
                else:
                    # Chandelier trail engages only once price is +1R in our favour; never moves down.
                    one_r = float(pos["entry"]) - float(pos["stop"])
                    armed = float(b["close"]) >= float(pos["entry"]) + one_r
                    new_trail = max(trail, float(b["chandelier"])) if armed else trail
                    if new_trail > trail + 1e-9:
                        trails.append(f"{pos['symbol']} → {new_trail:.2f}")
                    trail = new_trail
                    book.mark_bar(pos["id"], round(trail, 2), bdate, held)
                    continue
                pnl, r = book.close_position(pos, round(px, 2), bdate, reason)
                exits.append(f"{pos['symbol']} {reason} @ {px:.2f} ({r:+.2f}R, ${pnl:,.0f})")
                book.log("book", "slack", exits[-1], pos["symbol"])
                closed = True
                break
    br = breaker_status(book, cfg, today)
    for e, v in br.items():
        if v["tripped"] and exits:
            book.event("circuit_breaker", e, f"{v['losers_this_week']} losers this week")
    report = daily_report(day, fills, exits, trails, br, book.open_positions(), book.equity())
    if notify and (fills or exits or any(v["tripped"] for v in br.values())):
        slack(cfg.slack_webhook, report)
    return report
