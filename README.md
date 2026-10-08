# CONCLAVE — research desk that paper-trades its own briefs

Standalone, paper-only. Inspired by the Cloud9 "23-agent desk", rebuilt around the rules that actually
trade: Sonic R structure, Weinstein stage, ATR trailing, 2% risk, max 5 open, weekly circuit breaker.

**Golden rule:** Python computes every number. An LLM (optional) only writes sentences about numbers
it is handed, and a checker rejects any brief containing a figure that is not in the facts.

## Desk

| Agent | Does | Implementation |
|---|---|---|
| Screener | Momentum / RS vs SPY / stage / volume / RSI composite → top 15 of 60 | `specialists.screener_score` |
| Technical specialist | Dragon (EMA34 hi/lo), EMA21/89/200, 30-wk SMA stage, ATR, RSI, %R, Z, BB, VCP, breakout & pullback triggers | `specialists.technical` |
| Activity specialist | Up/down volume, dollar volume, big-volume days | `specialists.activity` |
| Bull analyst | Scores the long case, cites each fact | `desk.bull_case` |
| Bear analyst | Scores the short case, cites each fact | `desk.bear_case` |
| Independent review | Net score, evidence gaps, conviction HIGH/MEDIUM/LOW | `desk.review` |
| Chief | Entry/stop/trail/target from structure, writes brief, remembers last brief + Python-computed move since | `desk.chief` |
| Risk manager | 2% sizing on entry−stop, max 5 open incl. pending, per-entity weekly breaker (3 losers Mon–Sun) | `risk.py` |
| Paper book | SQLite: signals → next-open fill → stop / target / chandelier trail / stale exit | `paper.py`, `pipeline.run_daily` |

Trade rules encoded:
- Long only (v1). Needs Stage 2 + a trigger: dragon pullback-and-bounce, or 20-day breakout on ≥1.5× volume.
- Stop = min(dragon low, 10-bar low) − 0.2 ATR; rejected if wider than 3 ATR. Target = 2.5R.
- Trail = chandelier (22-bar high − 2 ATR), **armed only after +1R**, never lowered.
- Fill at next open; skipped if open gaps >3% above entry, or through stop/target.
- Stale exit after 30 bars if still under water.
- Every agent message logged to `messages` (agent, to, model, latency, content) — replayable.

## Install (Windows, trade-station)

```powershell
cd C:\Users\Owner\Trading\conclave
PowerShell -ExecutionPolicy Bypass -File setup-conclave.ps1     # venv, deps, .env, tests, 120-day real-data walk-forward
PowerShell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1  # registers CONCLAVE-Scheduler at logon (main.py)
```
Use `.venv\Scripts\python.exe -m conclave <cmd>` for manual runs. Log: `logs\conclave.log`.

## Run

```bash
python -m conclave scan            # desk run: builds signals, queues up to 5 (Tue/Sat 19:30 PT)
python -m conclave daily           # fills pending at next open, checks stops/targets/trails (Mon–Fri after close)
python -m conclave status          # equity, open positions, pending, breaker, stats
python -m conclave simulate --days 120   # walk-forward on real history with the same engine, LLM off
python -m conclave schedule        # APScheduler: daily 13:30 PT Mon–Fri, scan Tue/Sat 19:30 PT
```

Add `--synthetic` to any command for an offline demo on generated data. Add `--no-slack` to suppress posts.

## Monday go-live

1. Install, run tests, `python -m conclave simulate --days 120` to see the engine on real history.
2. Sat/Sun: `python -m conclave scan` → Slack table of setups; up to 5 queued.
3. Mon 13:30 PT: `daily` fills them at Monday's open and checks Monday's bar. Leave `schedule` running
   (or add two cron/Task Scheduler entries calling `daily` and `scan`).
4. Tue 19:30 PT: scan again. Unfilled signals from a previous scan are expired at each new scan.
5. `status` any time. Trades/R-multiples live in `data/conclave.sqlite` (`positions` table).

## Config

Edit `conclave/config.py`: universe (`DEFAULT_STOCKS`, `DEFAULT_ETFS`), risk, ATR multiples, target R,
screener depth. Everything secret comes from env vars.

## What's deliberately left out

Options, forex, India, shorts, IBKR/Questrade order routing. This is a paper engine to measure the desk's
expectancy first. Once it prints >1R expectancy over a meaningful sample, route it into Confluence.
