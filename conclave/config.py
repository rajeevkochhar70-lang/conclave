from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "AMD", "NFLX",
    "CRM", "ORCL", "ADBE", "NOW", "PANW", "CRWD", "ANET", "KLAC", "LRCX", "AMAT",
    "COST", "WMT", "HD", "LLY", "UNH", "JPM", "GS", "V", "MA", "AXP",
    "CAT", "DE", "GE", "RTX", "LMT", "XOM", "CVX", "LIN", "APP", "PLTR",
    "UBER", "SHOP", "MELI", "TTD", "VRT", "SMCI", "MU", "TSM", "ASML", "ARM",
]
DEFAULT_ETFS = ["SPY", "QQQ", "IWM", "XLK", "XLE", "XLF", "XLV", "SMH", "GLD", "XLI"]


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    return v if v not in (None, "") else default


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(_env("CONCLAVE_DATA_DIR", "data")))
    stocks: list[str] = field(default_factory=lambda: list(DEFAULT_STOCKS))
    etfs: list[str] = field(default_factory=lambda: list(DEFAULT_ETFS))
    starting_equity: float = float(_env("CONCLAVE_EQUITY", "100000"))
    risk_per_trade: float = 0.02
    max_open_trades: int = 5
    max_losers_per_week: int = 3
    atr_period: int = 14
    chandelier_lookback: int = 22
    chandelier_mult: float = 2.0
    max_stop_atr: float = 3.0
    target_r: float = 2.5
    stale_bars: int = 30
    history_period: str = "1y"
    screener_top_n: int = 15
    slack_webhook: str | None = field(default_factory=lambda: _env("SLACK_WEBHOOK_URL"))
    anthropic_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openrouter_key: str | None = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    llm_enabled: bool = field(default_factory=lambda: _env("CONCLAVE_LLM", "1") != "0")
    llm_models: list[str] = field(
        default_factory=lambda: [
            m.strip()
            for m in _env(
                "CONCLAVE_MODELS",
                "anthropic:claude-haiku-5-5,openrouter:nvidia/nemotron-nano-9b-v2:free,"
                "openrouter:qwen/qwen3-coder:free",
            ).split(",")
            if m.strip()
        ]
    )

    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "conclave.sqlite"

    @property
    def universe(self) -> list[str]:
        return self.stocks + self.etfs

    def entity_of(self, symbol: str) -> str:
        return "etf" if symbol in self.etfs else "stock"
