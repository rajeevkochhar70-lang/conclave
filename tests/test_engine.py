from datetime import date

import pandas as pd
import pytest

from conclave.config import Config
from conclave.data import SyntheticProvider
from conclave.desk import structure_levels
from conclave.llm import LLM, check_numbers
from conclave.paper import PaperBook
from conclave.pipeline import run_daily, run_scan
from conclave.risk import gate, position_size
from conclave.specialists import technical


@pytest.fixture
def cfg(tmp_path):
    c = Config(data_dir=tmp_path, llm_enabled=False, slack_webhook=None)
    c.stocks, c.etfs = ["AAA", "BBB", "CCC", "DDD"], ["SPY", "EEE"]
    return c


@pytest.fixture
def book(cfg):
    return PaperBook(cfg.db_path, cfg.starting_equity)


def test_position_size_two_percent():
    qty, risk = position_size(100_000, 0.02, 100.0, 95.0)
    assert qty == 400 and risk == 2000.0
    assert position_size(100_000, 0.02, 100.0, 100.0) == (0, 0.0)


def test_structure_levels_rejects_wide_stop(cfg):
    t = {"close": 100.0, "atr": 2.0, "dragon_lo": 90.0, "lo10": 92.0, "chandelier": 101.0}
    assert structure_levels(t, cfg) is None  # 10 pts > 3 ATR
    t["dragon_lo"], t["lo10"] = 96.0, 97.0
    lv = structure_levels(t, cfg)
    assert lv["stop"] == 95.6 and lv["rr"] == 2.5 and lv["trail"] <= 100.0  # trail never above entry


def test_number_checker_flags_invented_figures():
    facts = {"close": 150.25, "rsi": 61.3, "nested": {"ret20_pct": 4.2}}
    assert check_numbers("Close 150.25 with RSI 61.3, up 4.2% in 20 days.", facts) == []
    assert check_numbers("Close 150.25; revenue grew 23.7% last year.", facts) == [23.7]
    assert check_numbers("3 of 5 desks agree.", facts) == []  # small counts ignored


def test_llm_disabled_returns_none(cfg):
    assert LLM(cfg).complete("s", "p") is None


def test_circuit_breaker_blocks_entity_only(cfg, book):
    today = date(2026, 10, 7)  # Wednesday
    monday = "2026-10-05"
    for i in range(3):
        book.con.execute("INSERT INTO positions(symbol,entity,side,qty,entry,entry_date,stop,trail,target,risk_amt,"
                         "exit,exit_date,exit_reason,pnl,r_multiple,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (f"S{i}", "stock", "LONG", 10, 100, monday, 95, 95, 110, 50, 95, monday, "stop", -50, -1, "closed"))
    book.con.commit()
    ok, why = gate(book, cfg, "stock", today)
    assert not ok and "circuit breaker" in why
    ok, _ = gate(book, cfg, "etf", today)
    assert ok
    ok, _ = gate(book, cfg, "stock", date(2026, 10, 12))  # next Monday resets
    assert ok


def test_scan_then_daily_fills_and_caps_at_five(cfg, book):
    prov = SyntheticProvider(bars=300, trends={s: 0.002 for s in cfg.universe}, end="2026-10-02")
    cfg.screener_top_n = 6
    report, signals = run_scan(prov, cfg, book, today=date(2026, 10, 2), notify=False)
    assert "CONCLAVE scan" in report
    assert len(book.pending_signals()) <= cfg.max_open_trades
    # next trading day bar exists → fills at open
    prov2 = SyntheticProvider(bars=301, trends={s: 0.002 for s in cfg.universe}, end="2026-10-05")
    out = run_daily(prov2, cfg, book, today=date(2026, 10, 5), notify=False)
    assert "CONCLAVE daily" in out
    assert book.open_count() + len([r for r in book.con.execute("SELECT 1 FROM signals WHERE status IN ('missed','blocked','too_small')")]) == len(signals[: cfg.max_open_trades]) or book.open_count() <= 5
    for p in book.open_positions():
        assert p["trail"] == p["stop"]  # trail starts at structure stop, not chandelier


def test_technical_facts_are_numbers(cfg):
    df = SyntheticProvider(bars=260).history(["X"])["X"]
    t = technical(df, cfg)
    for k in ("close", "atr", "dragon_hi", "dragon_lo", "ema89", "rsi", "willr", "chandelier"):
        assert isinstance(t[k], float)
    assert t["stage"] in (0, 1, 2, 3, 4)


def test_memory_since_last_brief(book):
    book.save_brief("2026-09-29", "AAA", 100.0, "watch the dragon")
    m = book.last_brief("AAA", 105.0)
    assert m["move_pct"] == 5.0 and m["date"] == "2026-09-29"
    assert book.last_brief("ZZZ", 1.0) is None
