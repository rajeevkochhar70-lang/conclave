"""Entry point for Task Scheduler: starts the APScheduler loop (paper mode only)."""
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.FileHandler(Path(__file__).with_name("logs") / "conclave.log"),
                              logging.StreamHandler(sys.stdout)])

from conclave.config import Config          # noqa: E402
from conclave.data import YFinanceProvider  # noqa: E402
from conclave.scheduler import start        # noqa: E402

start(Config(), YFinanceProvider())
