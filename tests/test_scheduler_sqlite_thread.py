import threading
from types import SimpleNamespace

from conclave import scheduler


def test_jobs_run_on_a_worker_thread_without_sqlite_thread_errors(tmp_path, monkeypatch):
    # APScheduler runs jobs on worker threads. A PaperBook opened in start()'s thread made every
    # scheduled run fail (2026-10-12..10-21): "SQLite objects created in a thread can only be used in
    # that same thread".
    cfg = SimpleNamespace(db_path=tmp_path / "conclave.db", starting_equity=100_000.0, slack_webhook="x")
    failures, seen = [], []
    monkeypatch.setattr(scheduler, "slack", lambda webhook, text: failures.append(text))
    monkeypatch.setattr(scheduler, "LLM", lambda cfg: None)
    monkeypatch.setattr(scheduler.WallClockScheduler, "start", lambda self, *a, **k: seen.append(self))
    monkeypatch.setattr(scheduler, "run_daily",
                        lambda provider, cfg, book: book.pending_signals() + book.open_positions())

    scheduler.start(cfg, provider=None)
    daily = seen[0].get_job("daily")
    worker = threading.Thread(target=daily.func)
    worker.start()
    worker.join(5)

    assert [f for f in failures if "failed" in f] == []
