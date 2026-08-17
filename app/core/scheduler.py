"""
Background scheduler for periodic jobs: price alert checks, update
checks, and due-reminder checks today — the one place any future
"check X every N minutes" requirement (system health checks, etc.)
should register a job, rather than each feature spinning up its own
timer/thread.

Uses APScheduler's AsyncIOScheduler so jobs run on the same event loop
as everything else — no separate thread to coordinate shutdown for.
The event loop is passed in explicitly rather than relying on
asyncio.get_running_loop(), because main.py constructs and starts this
scheduler before qasync's loop.run_forever() begins — at that point
there IS a loop (qasync already created it), it's just not "running"
yet in asyncio's sense, and get_running_loop() would raise.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.event_bus import Event, EventBus, EventType
from app.core.update_checker import check_for_update
from app.finance import alert_service
from app.productivity import productivity_service
from app.utils.logger import get_logger

log = get_logger(__name__)


class BackgroundScheduler:
    def __init__(self, bus: EventBus, event_loop: asyncio.AbstractEventLoop) -> None:
        self._bus = bus
        self._scheduler = AsyncIOScheduler(event_loop=event_loop)
        settings = get_settings()
        self._alert_check_interval_s: int = settings.get("finance.alert_check_interval_seconds", 60)
        self._update_check_interval_h: int = settings.get("update.check_interval_hours", 24)
        self._reminder_check_interval_s: int = settings.get("productivity.reminder_check_interval_seconds", 30)

    def start(self) -> None:
        # NOTE: next_run_time=None does NOT mean "skip the immediate run,
        # start after one interval" — per APScheduler's own docs it means
        # "add the job as paused," i.e. it would never run at all until
        # someone explicitly calls resume_job(). To actually delay the
        # first run by one interval, we compute a real datetime instead.
        first_alert_check = datetime.now() + timedelta(seconds=self._alert_check_interval_s)
        self._scheduler.add_job(
            self._check_price_alerts,
            "interval",
            seconds=self._alert_check_interval_s,
            id="price_alert_check",
            next_run_time=first_alert_check,
        )

        # Update check: run once shortly after startup (so a user who
        # rarely closes the app still gets checked promptly), then daily.
        first_update_check = datetime.now() + timedelta(minutes=1)
        self._scheduler.add_job(
            self._check_for_update,
            "interval",
            hours=self._update_check_interval_h,
            id="update_check",
            next_run_time=first_update_check,
        )

        first_reminder_check = datetime.now() + timedelta(seconds=self._reminder_check_interval_s)
        self._scheduler.add_job(
            self._check_due_reminders,
            "interval",
            seconds=self._reminder_check_interval_s,
            id="reminder_check",
            next_run_time=first_reminder_check,
        )

        self._scheduler.start()
        log.info(
            "Background scheduler started (price alerts every {}s, update check every {}h, " "reminders every {}s).",
            self._alert_check_interval_s,
            self._update_check_interval_h,
            self._reminder_check_interval_s,
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("Background scheduler stopped.")

    async def _check_price_alerts(self) -> None:
        # check_alerts() does blocking network I/O (yfinance) — run it off
        # the event loop so a slow/hanging quote fetch doesn't freeze the
        # GUI or voice pipeline.
        triggered = await asyncio.to_thread(alert_service.check_alerts)
        for alert in triggered:
            await self._bus.publish(Event(EventType.PRICE_ALERT_TRIGGERED, payload=alert))

    async def _check_for_update(self) -> None:
        result = await check_for_update()
        if result.checked and result.update_available:
            await self._bus.publish(
                Event(
                    EventType.UPDATE_AVAILABLE,
                    payload={
                        "current_version": result.current_version,
                        "latest_version": result.latest_version,
                        "release_url": result.release_url,
                    },
                )
            )

    async def _check_due_reminders(self) -> None:
        # get_due_reminders() does blocking DB I/O -- same reasoning as
        # the alert check above, keep it off the event loop.
        due = await asyncio.to_thread(productivity_service.get_due_reminders)
        for reminder in due:
            await self._bus.publish(Event(EventType.REMINDER_DUE, payload=reminder))
