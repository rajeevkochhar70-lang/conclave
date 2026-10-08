from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .config import Config
from .data import SyntheticProvider, YFinanceProvider
from .llm import LLM
from .paper import PaperBook
from .pipeline import run_daily, run_scan
from .risk import breaker_status


def main(argv=None):
    ap = argparse.ArgumentParser("conclave", description="Research desk that paper-trades its briefs")
    ap.add_argument("cmd", choices=["scan", "daily", "status", "simulate", "schedule"])
    ap.add_argument("--synthetic", action="store_true", help="offline demo data")
    ap.add_argument("--no-slack", action="store_true")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # same file main.py loads; shell vars win
    cfg = Config()
    if a.no_slack:
        cfg.slack_webhook = None
    provider = SyntheticProvider(bars=420) if a.synthetic else YFinanceProvider()
    book = PaperBook(cfg.db_path, cfg.starting_equity)
    if a.cmd == "scan":
        report, _ = run_scan(provider, cfg, book, LLM(cfg))
        print(report)
    elif a.cmd == "daily":
        print(run_daily(provider, cfg, book))
    elif a.cmd == "status":
        print(f"Equity ${book.equity():,.2f} | open {book.open_count()}/{cfg.max_open_trades} | "
              f"pending {len(book.pending_signals())}")
        print("Breaker:", breaker_status(book, cfg, date.today()))
        for r in book.open_positions():
            print(f"  {r['symbol']:6} {r['qty']:>5} @ {r['entry']:.2f}  stop {r['stop']:.2f}  trail {r['trail']:.2f}  "
                  f"target {r['target']:.2f}  since {r['entry_date']}")
        for r in book.pending_signals():
            print(f"  pending {r['symbol']} entry {r['entry']} stop {r['stop']} ({r['conviction']})")
        print("Stats:", book.stats())
    elif a.cmd == "simulate":
        from .simulate import simulate
        print(simulate(provider, cfg, book, a.days))
        c = book.closed()
        if not c.empty:
            print(c[["symbol", "entry_date", "entry", "exit_date", "exit", "exit_reason", "r_multiple", "pnl"]].to_string(index=False))
    elif a.cmd == "schedule":
        from .scheduler import start
        start(cfg, provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
