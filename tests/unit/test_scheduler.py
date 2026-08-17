"""
Tests for BackgroundScheduler. The key regression this guards against:
APScheduler's add_job(next_run_time=None) means "add the job PAUSED,
never run it" (per its own docstring) — not "skip the immediate run,
wait one interval." An earlier version of this code used None believing
it meant the latter, which would have silently disabled price alerts
forever with no error. These tests assert the actual scheduled job has
a real, non-None next_run_time in the future.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.core.event_bus import EventBus, EventType
from app.core.scheduler import BackgroundScheduler


@pytest.mark.asyncio
async def test_scheduler_requires_event_loop_argument():
    """BackgroundScheduler.__init__ takes (bus, event_loop) — both
    required. This is the exact call shape main.py must use."""
    loop = asyncio.get_running_loop()
    bus = EventBus()
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)
    assert scheduler is not None


@pytest.mark.asyncio
async def test_started_job_has_a_real_future_next_run_time_not_none():
    loop = asyncio.get_running_loop()
    bus = EventBus()
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)

    scheduler.start()
    try:
        job = scheduler._scheduler.get_job("price_alert_check")
        assert job is not None
        assert job.next_run_time is not None, (
            "next_run_time is None, meaning the job was added PAUSED and will "
            "never run — this is the exact bug this test exists to catch."
        )
        assert job.next_run_time.replace(tzinfo=None) > datetime.now()
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_update_check_job_also_has_a_real_future_next_run_time():
    loop = asyncio.get_running_loop()
    bus = EventBus()
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)

    scheduler.start()
    try:
        job = scheduler._scheduler.get_job("update_check")
        assert job is not None
        assert job.next_run_time is not None
        assert job.next_run_time.replace(tzinfo=None) > datetime.now()
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_reminder_check_job_also_has_a_real_future_next_run_time():
    loop = asyncio.get_running_loop()
    bus = EventBus()
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)

    scheduler.start()
    try:
        job = scheduler._scheduler.get_job("reminder_check")
        assert job is not None
        assert job.next_run_time is not None
        assert job.next_run_time.replace(tzinfo=None) > datetime.now()
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_check_due_reminders_publishes_reminder_due_event(monkeypatch):
    """Exercises _check_due_reminders directly (not waiting on the real
    interval) against a real temp DB, confirming a genuinely overdue
    reminder results in a real REMINDER_DUE event on the bus."""
    import tempfile
    from datetime import timedelta
    from pathlib import Path

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_scheduler_reminders.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.core.config as config_module
    import app.data.database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None
    from app.data.models import Base

    Base.metadata.create_all(database_module.get_engine())

    from app.productivity import productivity_service

    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    productivity_service.add_reminder("Take the bread out of the oven", past)

    loop = asyncio.get_running_loop()
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(EventType.REMINDER_DUE, handler)
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)

    await scheduler._check_due_reminders()

    assert len(received) == 1
    assert received[0].payload["text"] == "Take the bread out of the oven"

    database_module._engine = None
    database_module._SessionLocal = None
    config_module.get_settings.cache_clear()
    loop = asyncio.get_running_loop()
    bus = EventBus()
    scheduler = BackgroundScheduler(bus=bus, event_loop=loop)

    scheduler.start()
    try:
        # A paused job's trigger never produces the next fire time via the
        # scheduler's own running jobs list; get_jobs() with default
        # pending filter excludes paused jobs from the active job store view
        # in some versions, so the clearest signal is next_run_time itself
        # (checked above) plus the job actually being present in get_jobs().
        active_jobs = scheduler._scheduler.get_jobs()
        assert any(j.id == "price_alert_check" for j in active_jobs)
    finally:
        scheduler.stop()
