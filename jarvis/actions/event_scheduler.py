"""Proactive calendar event reminders.

A background daemon thread polls the calendar at a configurable interval and
fires voice + banner notifications at configurable lead times before each
event.  Already-notified events are tracked per session so the same alert is
never repeated.

Config section (config.yaml)::

    event_scheduler:
      enabled: true
      poll_interval_minutes: 2        # how often to check calendar
      lead_times_minutes:             # when to alert before each event starts
        - 10
        - 1

Runtime context is injected by ``core.py`` once at startup via
``set_event_scheduler_context()``.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Set

log = logging.getLogger("jarvis.actions.event_scheduler")

# ── Runtime context (injected by core.py) ────────────────────────────────────

_cfg: dict = {}
_integrations_cfg: dict = {}
_memory_store = None        # MemoryStore instance (for connected accounts)
_synthesizer = None         # jarvis.speech.synthesizer.Synthesizer
_on_fire_cb: Callable | None = None


def set_event_scheduler_context(
    cfg: dict,
    integrations_cfg: dict,
    memory_store=None,
    synthesizer=None,
    on_fire: Callable | None = None,
) -> None:
    """Inject all required context from core.py at startup."""
    global _cfg, _integrations_cfg, _memory_store, _synthesizer, _on_fire_cb
    _cfg = cfg or {}
    _integrations_cfg = integrations_cfg or {}
    _memory_store = memory_store
    _synthesizer = synthesizer
    _on_fire_cb = on_fire


# ── Helpers ───────────────────────────────────────────────────────────────────

def _connected_accounts() -> list[dict]:
    if _memory_store is None:
        return []
    try:
        return _memory_store.list_connected_accounts()
    except Exception as exc:
        log.debug("Could not read connected accounts: %s", exc)
        return []


# ── EventScheduler ────────────────────────────────────────────────────────────

class EventScheduler:
    """Background thread that polls the calendar and announces upcoming events."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # tracks "event_key:lead_minutes" pairs already notified this session
        self._notified: Set[str] = set()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not _cfg.get("enabled", False):
            log.info("Event scheduler disabled.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Event scheduler started.")

    def stop(self) -> None:
        self._stop_event.set()

    # ── main loop ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        poll_seconds = int(_cfg.get("poll_interval_minutes", 2)) * 60
        # Run once immediately at startup, then on schedule
        try:
            self._check_events()
        except Exception as exc:
            log.warning("Event scheduler initial check failed: %s", exc)
        while not self._stop_event.wait(poll_seconds):
            try:
                self._check_events()
            except Exception as exc:
                log.warning("Event scheduler error: %s", exc)

    # ── calendar poll ─────────────────────────────────────────────────────────

    def _check_events(self) -> None:
        lead_times: list[int] = [
            int(x) for x in _cfg.get("lead_times_minutes", [10, 1])
        ]
        poll_interval = int(_cfg.get("poll_interval_minutes", 2))
        # Look ahead far enough to catch the earliest lead time
        lookahead_minutes = max(lead_times) + poll_interval + 1

        accounts = _connected_accounts()
        if not accounts:
            log.debug("No connected calendar accounts — skipping event check.")
            return

        try:
            from jarvis.integrations.calendar_service import CalendarService
            svc = CalendarService(_integrations_cfg, connected_accounts=accounts)
            # get_upcoming_events expects hours, so convert
            lookahead_hours = max(1, int(lookahead_minutes / 60) + 1)
            events = svc.get_upcoming_events(hours=lookahead_hours, limit=20)
        except Exception as exc:
            log.warning("Calendar fetch failed in event scheduler: %s", exc)
            return

        now = datetime.now(tz=timezone.utc)

        for event in events:
            if event.is_all_day:
                continue

            start = event.start_dt
            # Normalise to UTC-aware
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)

            minutes_until = (start - now).total_seconds() / 60

            for lead in lead_times:
                key = f"{event.raw_id or event.title}:{lead}"
                if key in self._notified:
                    continue
                # Fire when we're within [lead - poll_interval, lead + 1] window
                if lead - poll_interval <= minutes_until <= lead + 1:
                    self._fire(event, int(minutes_until), lead)
                    self._notified.add(key)

    # ── notification dispatch ─────────────────────────────────────────────────

    def _fire(self, event, actual_minutes: int, lead: int) -> None:
        title = event.title
        if actual_minutes <= 1:
            message = f'Your meeting "{title}" is starting now.'
        else:
            mins_label = (
                f"{actual_minutes} minute{'s' if actual_minutes != 1 else ''}"
            )
            message = f'Your meeting "{title}" is in {mins_label}.'

        log.info("Event reminder firing: %s", message)

        # OS banner
        try:
            from jarvis.actions.notify import post_banner
            post_banner("Upcoming Meeting", message)
        except Exception as exc:
            log.warning("Banner notification failed: %s", exc)

        # Voice announcement
        if _synthesizer:
            try:
                _synthesizer.speak(message)
            except Exception as exc:
                log.warning("Synthesizer error in event reminder: %s", exc)

        # IPC broadcast (for HUD clients)
        if _on_fire_cb:
            try:
                _on_fire_cb({
                    "type": "event_reminder",
                    "title": title,
                    "minutes_until": actual_minutes,
                })
            except Exception as exc:
                log.warning("IPC broadcast failed in event reminder: %s", exc)
