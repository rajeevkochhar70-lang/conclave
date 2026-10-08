"""SQLite paper book: pending signals fill at next open; stops/targets/trails checked on each daily bar."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY, scan_date TEXT, symbol TEXT, entity TEXT, side TEXT,
  entry REAL, stop REAL, trail REAL, target REAL, rr REAL, conviction TEXT, score INT,
  setup TEXT, trade_type TEXT, brief TEXT, payload TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY, signal_id INT, symbol TEXT, entity TEXT, side TEXT, qty INT,
  entry REAL, entry_date TEXT, stop REAL, trail REAL, target REAL, risk_amt REAL,
  exit REAL, exit_date TEXT, exit_reason TEXT, pnl REAL, r_multiple REAL, status TEXT DEFAULT 'open',
  last_bar TEXT, bars_held INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS briefs (
  id INTEGER PRIMARY KEY, scan_date TEXT, symbol TEXT, close REAL, brief TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, ts TEXT, scan_date TEXT, agent TEXT, to_agent TEXT, symbol TEXT,
  model TEXT, latency_ms INT, content TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, entity TEXT, detail TEXT);
"""


class PaperBook:
    def __init__(self, path: Path, starting_equity: float):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.starting_equity = starting_equity

    # ---- logging ----
    def log(self, agent: str, to_agent: str, content: str, symbol: str = "", model: str | None = None,
            latency_ms: int = 0, scan_date: str = ""):
        self.con.execute("INSERT INTO messages(ts,scan_date,agent,to_agent,symbol,model,latency_ms,content) "
                         "VALUES(?,?,?,?,?,?,?,?)",
                         (datetime.now().isoformat(timespec="seconds"), scan_date, agent, to_agent, symbol,
                          model, latency_ms, content))
        self.con.commit()

    def event(self, kind: str, entity: str, detail: str):
        self.con.execute("INSERT INTO events(ts,kind,entity,detail) VALUES(?,?,?,?)",
                         (datetime.now().isoformat(timespec="seconds"), kind, entity, detail))
        self.con.commit()

    # ---- equity / exposure ----
    def equity(self) -> float:
        r = self.con.execute("SELECT COALESCE(SUM(pnl),0) p FROM positions WHERE status='closed'").fetchone()
        return self.starting_equity + float(r["p"])

    def open_positions(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM positions WHERE status='open' ORDER BY entry_date").fetchall()

    def open_count(self) -> int:
        return len(self.open_positions())

    def pending_signals(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM signals WHERE status='pending' ORDER BY score DESC").fetchall()

    def has_exposure(self, symbol: str) -> bool:
        r = self.con.execute("SELECT 1 FROM positions WHERE symbol=? AND status='open' UNION "
                             "SELECT 1 FROM signals WHERE symbol=? AND status='pending'", (symbol, symbol))
        return r.fetchone() is not None

    # ---- circuit breaker ----
    def week_losers(self, entity: str, today: date) -> int:
        monday = today - timedelta(days=today.weekday())
        r = self.con.execute("SELECT COUNT(*) c FROM positions WHERE status='closed' AND entity=? AND pnl<0 "
                             "AND exit_date>=?", (entity, monday.isoformat())).fetchone()
        return int(r["c"])

    def breaker_tripped(self, entity: str, today: date, max_losers: int) -> bool:
        return self.week_losers(entity, today) >= max_losers

    # ---- signals ----
    def add_signal(self, sig: dict, scan_date: str) -> int:
        cur = self.con.execute(
            "INSERT INTO signals(scan_date,symbol,entity,side,entry,stop,trail,target,rr,conviction,score,setup,"
            "trade_type,brief,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scan_date, sig["symbol"], sig["entity"], sig["side"], sig["entry"], sig["stop"], sig["trail"],
             sig["target"], sig["rr"], sig["conviction"], sig["score"], sig["setup"], sig["trade_type"],
             sig["brief"], json.dumps(sig)))
        self.con.commit()
        return int(cur.lastrowid)

    def expire_signals(self, older_than: str):
        self.con.execute("UPDATE signals SET status='expired' WHERE status='pending' AND scan_date<?", (older_than,))
        self.con.commit()

    def set_signal_status(self, sid: int, status: str):
        self.con.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))
        self.con.commit()

    # ---- positions ----
    def open_position(self, sig: sqlite3.Row, qty: int, fill: float, fill_date: str, risk_amt: float) -> int:
        cur = self.con.execute(
            "INSERT INTO positions(signal_id,symbol,entity,side,qty,entry,entry_date,stop,trail,target,risk_amt,"
            "last_bar) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sig["id"], sig["symbol"], sig["entity"], sig["side"], qty, fill, fill_date, sig["stop"],
             sig["stop"], sig["target"], risk_amt, fill_date))  # trail starts at structure stop
        self.set_signal_status(sig["id"], "filled")
        return int(cur.lastrowid)

    def mark_bar(self, pid: int, trail: float, bar: str, bars_held: int):
        self.con.execute("UPDATE positions SET trail=?, last_bar=?, bars_held=? WHERE id=?",
                         (trail, bar, bars_held, pid))
        self.con.commit()

    def close_position(self, pos: sqlite3.Row, px: float, on: str, reason: str):
        pnl = round((px - pos["entry"]) * pos["qty"], 2)
        r = round(pnl / pos["risk_amt"], 2) if pos["risk_amt"] else 0.0
        self.con.execute("UPDATE positions SET exit=?,exit_date=?,exit_reason=?,pnl=?,r_multiple=?,status='closed' "
                         "WHERE id=?", (px, on, reason, pnl, r, pos["id"]))
        self.con.commit()
        return pnl, r

    # ---- memory ----
    def save_brief(self, scan_date: str, symbol: str, close: float, brief: str):
        self.con.execute("INSERT INTO briefs(scan_date,symbol,close,brief) VALUES(?,?,?,?)",
                         (scan_date, symbol, close, brief))
        self.con.commit()

    def last_brief(self, symbol: str, now_close: float) -> dict | None:
        r = self.con.execute("SELECT scan_date,close,brief FROM briefs WHERE symbol=? ORDER BY id DESC LIMIT 1",
                             (symbol,)).fetchone()
        if not r:
            return None
        return {"date": r["scan_date"], "close": r["close"], "brief": r["brief"],
                "move_pct": round((now_close / r["close"] - 1) * 100, 2)}

    # ---- stats ----
    def closed(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM positions WHERE status='closed' ORDER BY exit_date", self.con)

    def stats(self) -> dict:
        c = self.closed()
        if c.empty:
            return {"trades": 0, "win_rate": None, "expectancy_r": None, "total_pnl": 0.0, "equity": self.equity()}
        wins = c[c.pnl > 0]
        losses = c[c.pnl <= 0]
        return {"trades": int(len(c)), "win_rate": round(len(wins) / len(c) * 100, 1),
                "expectancy_r": round(float(c.r_multiple.mean()), 2),
                "avg_win_r": round(float(wins.r_multiple.mean()), 2) if len(wins) else 0.0,
                "avg_loss_r": round(float(losses.r_multiple.mean()), 2) if len(losses) else 0.0,
                "total_pnl": round(float(c.pnl.sum()), 2), "equity": round(self.equity(), 2)}
