"""
Tests for calendar_service.py — normalise + merge events, timezone/day
filtering, and empty-schedule handling.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.integrations.calendar_service import (
    CalendarEvent,
    CalendarService,
    _parse_google_event,
    _parse_outlook_event,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_NOW_UTC = datetime(2025, 5, 13, 14, 0, 0, tzinfo=timezone.utc)   # 2:00 PM UTC


def _google_item(
    title="Standup",
    start="2025-05-13T10:00:00-04:00",
    end="2025-05-13T10:30:00-04:00",
    all_day=False,
    cancelled=False,
):
    if all_day:
        return {
            "id": "g1",
            "summary": title,
            "start": {"date": "2025-05-13"},
            "end": {"date": "2025-05-13"},
            "status": "cancelled" if cancelled else "confirmed",
            "attendees": [],
        }
    return {
        "id": "g1",
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "status": "cancelled" if cancelled else "confirmed",
        "attendees": [{"email": "a@a.com"}, {"email": "b@b.com"}],
        "location": "Zoom",
    }


def _outlook_item(
    title="Design Review",
    start="2025-05-13T13:30:00",
    end="2025-05-13T14:30:00",
    all_day=False,
):
    return {
        "id": "o1",
        "subject": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "isAllDay": all_day,
        "location": {"displayName": "Teams"},
        "attendees": [{"emailAddress": {"address": "c@c.com"}}],
        "calendar": {"name": "Work Calendar"},
    }


# ── _parse_google_event ───────────────────────────────────────────────────────


class TestParseGoogleEvent:
    def test_basic_timed_event(self):
        ev = _parse_google_event(_google_item(), "Personal")
        assert ev is not None
        assert ev.title == "Standup"
        assert ev.source == "google"
        assert ev.calendar_name == "Personal"
        assert ev.is_all_day is False
        assert ev.attendees_count == 2
        assert ev.location == "Zoom"

    def test_all_day_event(self):
        ev = _parse_google_event(_google_item(all_day=True), "Holidays")
        assert ev is not None
        assert ev.is_all_day is True
        assert ev.start_dt.hour == 0

    def test_cancelled_event_returns_none(self):
        ev = _parse_google_event(_google_item(cancelled=True), "Work")
        assert ev is None

    def test_missing_datetime_returns_none(self):
        item = {
            "id": "bad",
            "summary": "Bad",
            "start": {"dateTime": "not-a-date"},
            "end": {"dateTime": "not-a-date"},
            "status": "confirmed",
        }
        ev = _parse_google_event(item, "Work")
        assert ev is None


# ── _parse_outlook_event ─────────────────────────────────────────────────────


class TestParseOutlookEvent:
    def test_basic_timed_event(self):
        ev = _parse_outlook_event(_outlook_item())
        assert ev is not None
        assert ev.title == "Design Review"
        assert ev.source == "outlook"
        assert ev.calendar_name == "Work Calendar"
        assert ev.is_all_day is False
        assert ev.location == "Teams"
        assert ev.attendees_count == 1

    def test_all_day_event(self):
        ev = _parse_outlook_event(_outlook_item(all_day=True))
        assert ev is not None
        assert ev.is_all_day is True

    def test_missing_datetime_returns_none(self):
        item = {
            "id": "bad",
            "subject": "Bad",
            "start": {"dateTime": ""},
            "end": {"dateTime": ""},
            "isAllDay": False,
            "attendees": [],
        }
        ev = _parse_outlook_event(item)
        assert ev is None


# ── CalendarService ───────────────────────────────────────────────────────────


class TestCalendarService:
    """Unit-test the CalendarService with mocked adapters."""

    def _make_events(self):
        ev1 = CalendarEvent(
            source="google",
            calendar_name="Work",
            title="Standup",
            start_dt=datetime(2025, 5, 13, 10, 0, tzinfo=timezone.utc),
            end_dt=datetime(2025, 5, 13, 10, 30, tzinfo=timezone.utc),
        )
        ev2 = CalendarEvent(
            source="outlook",
            calendar_name="Calendar",
            title="Design Review",
            start_dt=datetime(2025, 5, 13, 13, 30, tzinfo=timezone.utc),
            end_dt=datetime(2025, 5, 13, 14, 30, tzinfo=timezone.utc),
        )
        ev3 = CalendarEvent(
            source="google",
            calendar_name="Work",
            title="Sprint Retro",
            start_dt=datetime(2025, 5, 13, 16, 0, tzinfo=timezone.utc),
            end_dt=datetime(2025, 5, 13, 17, 0, tzinfo=timezone.utc),
        )
        return [ev1, ev2, ev3]

    def _cfg(self):
        return {
            "enabled": True,
            "timezone": "UTC",
            "calendar": {"google_enabled": True, "outlook_enabled": True, "max_events_per_query": 20},
            "email": {},
            "oauth": {"redirect_port": 8765},
            "google": {"client_id": "x", "client_secret": "y"},
            "microsoft": {"client_id": "x", "client_secret": "y", "tenant": "common"},
        }

    def test_merges_and_sorts_events(self):
        events = self._make_events()
        svc = CalendarService(self._cfg(), [{"provider": "google", "account_id": "a@g.com"}])

        with patch.object(svc, "_get_adapters") as mock_adapters:
            adapter = MagicMock()
            adapter.fetch_events.return_value = events
            mock_adapters.return_value = [adapter]

            result = svc.get_todays_schedule()

        assert len(result) == 3
        # Must be sorted by start_dt
        starts = [e.start_dt for e in result]
        assert starts == sorted(starts)
        assert result[0].title == "Standup"
        assert result[1].title == "Design Review"
        assert result[2].title == "Sprint Retro"

    def test_empty_schedule(self):
        svc = CalendarService(self._cfg(), [{"provider": "google", "account_id": "a@g.com"}])

        with patch.object(svc, "_get_adapters") as mock_adapters:
            adapter = MagicMock()
            adapter.fetch_events.return_value = []
            mock_adapters.return_value = [adapter]

            result = svc.get_todays_schedule()

        assert result == []

    def test_no_connected_accounts_returns_empty(self):
        svc = CalendarService(self._cfg(), [])
        result = svc.get_todays_schedule()
        assert result == []

    def test_cache_returns_same_result(self):
        events = self._make_events()
        svc = CalendarService(self._cfg(), [{"provider": "google", "account_id": "a@g.com"}])

        call_count = {"n": 0}

        def fake_fetch(start, end):
            call_count["n"] += 1
            return events

        with patch.object(svc, "_get_adapters") as mock_adapters:
            adapter = MagicMock()
            adapter.fetch_events.side_effect = fake_fetch
            mock_adapters.return_value = [adapter]

            r1 = svc.get_todays_schedule()
            r2 = svc.get_todays_schedule()

        assert r1 is r2            # same object from cache
        assert call_count["n"] == 1  # adapter called only once

    def test_adapter_error_returns_partial(self):
        good_ev = CalendarEvent(
            source="google", calendar_name="W", title="OK",
            start_dt=datetime(2025, 5, 13, 9, 0, tzinfo=timezone.utc),
            end_dt=datetime(2025, 5, 13, 9, 30, tzinfo=timezone.utc),
        )
        svc = CalendarService(
            self._cfg(),
            [
                {"provider": "google", "account_id": "a@g.com"},
                {"provider": "outlook", "account_id": "a@o.com"},
            ],
        )

        with patch.object(svc, "_get_adapters") as mock_adapters:
            good_adapter = MagicMock()
            good_adapter.fetch_events.return_value = [good_ev]
            bad_adapter = MagicMock()
            bad_adapter.fetch_events.side_effect = RuntimeError("Network error")
            mock_adapters.return_value = [good_adapter, bad_adapter]

            result = svc.get_todays_schedule()

        # Bad adapter should not crash Jarvis; good events still returned
        assert len(result) == 1
        assert result[0].title == "OK"

    def test_get_upcoming_events_excludes_past(self):
        past_ev = CalendarEvent(
            source="google", calendar_name="W", title="Old Meeting",
            start_dt=_NOW_UTC - timedelta(hours=2),
            end_dt=_NOW_UTC - timedelta(hours=1),
        )
        future_ev = CalendarEvent(
            source="google", calendar_name="W", title="Future Meeting",
            start_dt=_NOW_UTC + timedelta(hours=1),
            end_dt=_NOW_UTC + timedelta(hours=2),
        )

        svc = CalendarService(self._cfg(), [{"provider": "google", "account_id": "a@g.com"}])

        with patch.object(svc, "_get_adapters") as mock_adapters:
            adapter = MagicMock()
            adapter.fetch_events.return_value = [past_ev, future_ev]
            mock_adapters.return_value = [adapter]

            result = svc.get_upcoming_events(hours=24, limit=10)

        # past event's end_dt is before now — should be filtered out
        assert all(e.title != "Old Meeting" for e in result)

    def test_list_connected_accounts(self):
        accounts = [
            {"provider": "google", "account_id": "a@g.com"},
            {"provider": "microsoft", "account_id": "a@outlook.com"},
        ]
        svc = CalendarService(self._cfg(), accounts)
        assert svc.list_connected_accounts() == accounts
