from __future__ import annotations

from .desk import Signal

HEADER = "| Symbol | Market | Type | Entry | Stop Loss | Trailing Stop | Target | R:R | Conviction | Trade Type |"
SEP = "|---|---|---|---|---|---|---|---|---|---|"


def signal_table(signals: list[Signal]) -> str:
    if not signals:
        return "_No qualifying setups._"
    rows = [HEADER, SEP]
    for s in signals:
        rows.append(f"| {s.symbol} | NA | {s.side} | {s.entry} | {s.stop} | {s.trail} | {s.target} | "
                    f"{s.rr} | {s.conviction} | {s.trade_type} ({s.setup}) |")
    return "\n".join(rows)


def scan_report(scan_date: str, signals: list[Signal], queued: list[str], skipped: dict[str, str],
                breaker: dict, open_count: int, max_open: int, equity: float, stats: dict,
                market: dict | None = None) -> str:
    lines = [f"*CONCLAVE scan — {scan_date}*",
             f"Open trades: {open_count}/{max_open} | Equity: ${equity:,.0f} | "
             f"Breaker — stock: {'TRIPPED' if breaker['stock']['tripped'] else breaker['stock']['losers_this_week']} "
             f"| etf: {'TRIPPED' if breaker['etf']['tripped'] else breaker['etf']['losers_this_week']}"]
    if market:
        lines.append(f"Market: SPY {market.get('spy_ret20')}% / 20d, stage {market.get('spy_stage')}, "
                     f"breadth {market.get('pct_above_ema89')}% of universe above EMA89")
    lines += ["", signal_table(signals), ""]
    if queued:
        lines.append(f"Queued for next-open fill: {', '.join(queued)}")
    if skipped:
        lines.append("Not queued: " + "; ".join(f"{k} ({v})" for k, v in skipped.items()))
    for s in signals:
        lines += ["", f"*{s.symbol}* — {s.brief}"]
    if stats["trades"]:
        lines += ["", f"Book: {stats['trades']} closed, win {stats['win_rate']}%, "
                      f"expectancy {stats['expectancy_r']}R, P&L ${stats['total_pnl']:,.0f}"]
    return "\n".join(lines)


def daily_report(day: str, fills: list[str], exits: list[str], trails: list[str], breaker: dict,
                 open_rows: list, equity: float) -> str:
    lines = [f"*CONCLAVE daily — {day}* | Equity ${equity:,.0f}"]
    lines += [f"Filled: {', '.join(fills)}" if fills else "Filled: none"]
    lines += [f"Exits: {'; '.join(exits)}" if exits else "Exits: none"]
    if trails:
        lines.append(f"Trail raised: {', '.join(trails)}")
    for e, v in breaker.items():
        if v["tripped"]:
            lines.append(f":rotating_light: circuit breaker TRIPPED for {e} — no new {e} entries until Monday")
    if open_rows:
        lines.append("Open: " + ", ".join(f"{r['symbol']} {r['qty']}@{r['entry']} trail {r['trail']}" for r in open_rows))
    return "\n".join(lines)
