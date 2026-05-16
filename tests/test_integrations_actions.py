"""
Tests for jarvis/actions/integrations.py — spoken response formatting,
next-event behaviour, and account-not-connected handling.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import jarvis.actions.integrations as integ
from jarvis.integrations.calendar_service import CalendarEvent


# ── Helpers ───────────────────────────────────────────────────────────────────

_BASE_CFG = {
    "enabled": True,
    "timezone": "UTC",
    "calendar": {"google_enabled": True, "outlook_enabled": True, "max_events_per_query": 20},
    "email": {},
    "oauth": {"redirect_port": 8765},
    "google": {"client_id": "cid", "client_secret": "csec"},
    "microsoft": {"client_id": "cid", "client_secret": "csec", "tenant": "common"},
}


def _setup(accounts=None):
    """Inject context into the integrations action module."""
    mock_store = MagicMock()
    mock_store.list_connected_accounts.return_value = accounts or []
    integ.set_integrations_context(_BASE_CFG, mock_store)
    return mock_store


def _make_event(title, hour, minute=0, all_day=False):
    start = datetime(2025, 5, 13, hour, minute, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    return CalendarEvent(
        source="google",
        calendar_name="Work",
        title=title,
        start_dt=start,
        end_dt=end,
        is_all_day=all_day,
    )


# ── schedule_today ────────────────────────────────────────────────────────────


class TestScheduleToday:
    def test_no_accounts_returns_connect_prompt(self):
        _setup(accounts=[])
        result = integ.schedule_today()
        assert "not connected" in result.lower()
        assert "google" in result.lower() or "outlook" in result.lower()

    def test_empty_schedule(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_todays_schedule.return_value = []
            result = integ.schedule_today()
        assert "clear today" in result.lower() or "no events" in result.lower()

    def test_single_event(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        events = [_make_event("Standup", 10)]
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_todays_schedule.return_value = events
            result = integ.schedule_today()
        assert "1 event" in result.lower()
        assert "Standup" in result

    def test_multiple_events_spoken_format(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        events = [
            _make_event("Standup", 10),
            _make_event("Design Review", 13, 30),
            _make_event("Retro", 16),
        ]
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_todays_schedule.return_value = events
            result = integ.schedule_today()

        assert "3 events" in result.lower()
        assert "Standup" in result
        assert "Design Review" in result
        assert "Retro" in result
        # first / next / finally framing
        assert "First" in result
        assert "Next" in result
        assert "finally" in result.lower()

    def test_all_day_event_says_all_day(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        events = [_make_event("Holiday", 0, all_day=True)]
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_todays_schedule.return_value = events
            result = integ.schedule_today()
        assert "all day" in result.lower()

    def test_calendar_api_error_returns_graceful_message(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_todays_schedule.side_effect = RuntimeError("API down")
            result = integ.schedule_today()
        # Should not crash; should return a user-friendly message
        assert isinstance(result, str)
        assert "trouble" in result.lower() or "failed" in result.lower() or "error" in result.lower()

    def test_integration_disabled_returns_message(self):
        mock_store = MagicMock()
        mock_store.list_connected_accounts.return_value = [
            {"provider": "google", "account_id": "a@g.com"}
        ]
        integ.set_integrations_context({**_BASE_CFG, "enabled": False}, mock_store)
        result = integ.schedule_today()
        assert "disabled" in result.lower()
        # Restore
        integ.set_integrations_context(_BASE_CFG, mock_store)


# ── next_event ────────────────────────────────────────────────────────────────


class TestNextEvent:
    def test_no_accounts(self):
        _setup(accounts=[])
        result = integ.next_event()
        assert "not connected" in result.lower()

    def test_no_upcoming_events(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_upcoming_events.return_value = []
            result = integ.next_event()
        assert "nothing" in result.lower() or "no" in result.lower()

    def test_returns_next_event_title_and_time(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        events = [_make_event("Team Sync", 14)]
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_upcoming_events.return_value = events
            result = integ.next_event()
        assert "Team Sync" in result

    def test_all_day_next_event(self):
        _setup(accounts=[{"provider": "google", "account_id": "a@g.com"}])
        events = [_make_event("Conference Day", 0, all_day=True)]
        with patch("jarvis.actions.integrations.CalendarService") as MockSvc:
            MockSvc.return_value.get_upcoming_events.return_value = events
            result = integ.next_event()
        assert "all-day" in result.lower() or "all day" in result.lower()


# ── connect_google ────────────────────────────────────────────────────────────


class TestConnectGoogle:
    def test_no_credentials_configured(self):
        integ.set_integrations_context(
            {**_BASE_CFG, "google": {"client_id": "", "client_secret": ""}},
            MagicMock(),
        )
        result = integ.connect_google()
        assert "not configured" in result.lower()
        # Restore
        integ.set_integrations_context(_BASE_CFG, MagicMock())

    def test_successful_connection(self):
        mock_store = MagicMock()
        integ.set_integrations_context(_BASE_CFG, mock_store)
        with patch("jarvis.actions.integrations.connect_google_account") as mock_connect:
            mock_connect.return_value = {"ok": True, "email": "test@gmail.com", "message": "ok"}
            result = integ.connect_google()
        assert "connected" in result.lower()
        assert "test@gmail.com" in result
        mock_store.save_connected_account.assert_called_once_with("google", "test@gmail.com")

    def test_failed_connection_returns_error_message(self):
        integ.set_integrations_context(_BASE_CFG, MagicMock())
        with patch("jarvis.actions.integrations.connect_google_account") as mock_connect:
            mock_connect.return_value = {"ok": False, "email": None, "message": "Auth failed"}
            result = integ.connect_google()
        assert "failed" in result.lower() or "Auth failed" in result


# ── connect_outlook ───────────────────────────────────────────────────────────


class TestConnectOutlook:
    def test_no_credentials_configured(self):
        integ.set_integrations_context(
            {**_BASE_CFG, "microsoft": {"client_id": "", "client_secret": "", "tenant": "common"}},
            MagicMock(),
        )
        result = integ.connect_outlook()
        assert "not configured" in result.lower()
        integ.set_integrations_context(_BASE_CFG, MagicMock())

    def test_successful_connection(self):
        mock_store = MagicMock()
        integ.set_integrations_context(_BASE_CFG, mock_store)
        with patch("jarvis.actions.integrations.connect_microsoft_account") as mock_connect:
            mock_connect.return_value = {"ok": True, "email": "test@outlook.com", "message": "ok"}
            result = integ.connect_outlook()
        assert "connected" in result.lower()
        mock_store.save_connected_account.assert_called_once_with("microsoft", "test@outlook.com")


# ── disconnect_account ────────────────────────────────────────────────────────


class TestDisconnectAccount:
    def test_unknown_provider(self):
        _setup()
        result = integ.disconnect_account("twitter")
        assert "do not recognise" in result.lower() or "not recognise" in result.lower()

    def test_no_matching_account(self):
        _setup(accounts=[])
        result = integ.disconnect_account("google")
        assert "no" in result.lower() and "connected" in result.lower()

    def test_successful_disconnect(self):
        mock_store = MagicMock()
        mock_store.list_connected_accounts.return_value = [
            {"provider": "google", "account_id": "a@g.com"}
        ]
        integ.set_integrations_context(_BASE_CFG, mock_store)

        with patch("jarvis.actions.integrations.disconnect_account") as mock_disc:
            # Don't shadow the function under test — call the inner import directly
            pass

        with patch("jarvis.integrations.auth.disconnect_account") as mock_disc:
            mock_disc.return_value = {"ok": True, "message": "done"}
            result = integ.disconnect_account("google")

        assert "disconnected" in result.lower()

    def test_alias_gmail_maps_to_google(self):
        mock_store = MagicMock()
        mock_store.list_connected_accounts.return_value = [
            {"provider": "google", "account_id": "a@g.com"}
        ]
        integ.set_integrations_context(_BASE_CFG, mock_store)

        with patch("jarvis.integrations.auth.disconnect_account") as mock_disc:
            mock_disc.return_value = {"ok": True, "message": "done"}
            result = integ.disconnect_account("gmail")

        assert "disconnected" in result.lower()


# ── list_accounts ─────────────────────────────────────────────────────────────


class TestListAccounts:
    def test_no_accounts(self):
        _setup(accounts=[])
        result = integ.list_accounts()
        assert "not connected" in result.lower()

    def test_google_only(self):
        _setup(accounts=[{"provider": "google", "account_id": "user@gmail.com"}])
        result = integ.list_accounts()
        assert "Google" in result
        assert "user@gmail.com" in result

    def test_both_providers(self):
        _setup(accounts=[
            {"provider": "google", "account_id": "g@gmail.com"},
            {"provider": "microsoft", "account_id": "m@outlook.com"},
        ])
        result = integ.list_accounts()
        assert "Google" in result
        assert "Outlook" in result
        assert "g@gmail.com" in result
        assert "m@outlook.com" in result
