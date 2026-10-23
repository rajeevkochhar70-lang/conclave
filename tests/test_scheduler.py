import threading
from datetime import datetime, timedelta, timezone

from conclave.scheduler import build_scheduler


def test_jobs_tolerate_a_late_start():
    sch = build_scheduler(cfg=None, provider=None, book=None, llm=None)
    jobs = {j.id: j for j in sch.get_jobs()}
    assert set(jobs) == {"daily", "scan"}
    for j in jobs.values():
        assert j.misfire_grace_time == 3600 and j.coalesce is True


def test_scheduler_wait_is_capped_so_machine_sleep_cannot_delay_jobs():
    # Windows wait timeouts exclude time spent suspended, so one long wait toward the next job comes back
    # late by however long the machine slept (2026-10-20: slept 4h26m, scan fired 4h26m late, dropped).
    sch = build_scheduler(cfg=None, provider=None, book=None, llm=None)
    sch.remove_all_jobs()  # never let the test execute a real job
    sch.add_job(lambda: None, "date", run_date=datetime.now(timezone.utc) + timedelta(hours=6))
    loop = threading.Thread(target=sch.start, kwargs={"paused": True}, daemon=True)  # start() blocks
    loop.start()
    try:
        while not sch.running:
            loop.join(0.01)
        sch.resume()
        assert 0 < sch._process_jobs() <= 60
    finally:
        sch.shutdown(wait=False)
        loop.join(5)
