"""Tests for jarvis/actions/notify.py — duration parsing, time parsing,
scheduling lifecycle, action functions, and OS-banner escaping."""

import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import jarvis.actions.notify as notify
from jarvis.actions.notify import (
    parse_duration,
    parse_time,
    _human_duration,
    _osa_escape,
    _ps_escape,
    NotificationScheduler,
    post_banner,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset():
    """Reset module-level state between tests."""
    notify._cfg = {"enabled": True, "sound": False, "max_timer_hours": 24,
                   "default_snooze_minutes": 5}
    notify._synthesizer = None
    notify._on_fire_cb = None
    notify._scheduler = NotificationScheduler()


# ── parse_duration ────────────────────────────────────────────────────────────

class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("5 minutes") == 300
        assert parse_duration("1 minute") == 60
        assert parse_duration("30 min") == 1800
        assert parse_duration("10m") == 600

    def test_seconds(self):
        assert parse_duration("30 seconds") == 30
        assert parse_duration("1 sec") == 1
        assert parse_duration("45s") == 45

    def test_hours(self):
        assert parse_duration("2 hours") == 7200
        assert parse_duration("1 hour") == 3600
        assert parse_duration("1hr") == 3600

    def test_combined(self):
        assert parse_duration("1 hour 30 minutes") == 5400
        assert parse_duration("2 hours 15 minutes 10 seconds") == 8110

    def test_indefinite_articles(self):
        assert parse_duration("a minute") == 60
        assert parse_duration("an hour") == 3600

    def test_unknown_returns_none(self):
        assert parse_duration("tomorrow") is None
        assert parse_duration("") is None
        assert parse_duration("later") is None

    def test_number_only_returns_none(self):
        # bare numbers without a unit should not parse as seconds
        assert parse_duration("5") is None


# ── _human_duration ───────────────────────────────────────────────────────────

class TestHumanDuration:
    def test_seconds(self):
        assert _human_duration(45) == "45 seconds"
        assert _human_duration(1) == "1 second"

    def test_minutes(self):
        assert _human_duration(60) == "1 minute"
        assert _human_duration(300) == "5 minutes"

    def test_hours(self):
        assert _human_duration(3600) == "1 hour"
        assert _human_duration(7200) == "2 hours"

    def test_hours_and_minutes(self):
        assert _human_duration(5400) == "1 hour 30 minutes"

    def test_minutes_no_seconds(self):
        # Seconds are omitted when hours are present
        assert "second" not in _human_duration(3661)


# ── parse_time ────────────────────────────────────────────────────────────────

class TestParseTime:
    def test_hhmm_am(self):
        t = parse_time("7:30 AM")
        assert t is not None
        assert t.hour == 7
        assert t.minute == 30

    def test_hhmm_pm(self):
        t = parse_time("3:45 PM")
        assert t is not None
        assert t.hour == 15
        assert t.minute == 45

    def test_h_am(self):
        t = parse_time("8 AM")
        assert t is not None
        assert t.hour == 8
        assert t.minute == 0

    def test_h_pm(self):
        t = parse_time("9 PM")
        assert t is not None
        assert t.hour == 21

    def test_noon(self):
        t = parse_time("noon")
        assert t is not None
        assert t.hour == 12 and t.minute == 0

    def test_midnight(self):
        t = parse_time("midnight")
        assert t is not None
        assert t.hour == 0 and t.minute == 0

    def test_result_always_in_future(self):
        # Any time parsed must be strictly in the future
        for text in ("7:30 AM", "12:00 PM", "11:59 PM", "noon"):
            t = parse_time(text)
            assert t is None or t > datetime.now(), f"{text!r} → {t}"

    def test_12_pm_is_noon(self):
        t = parse_time("12:00 PM")
        assert t is not None
        assert t.hour == 12

    def test_12_am_is_midnight(self):
        t = parse_time("12:00 AM")
        assert t is not None
        assert t.hour == 0

    def test_unknown_returns_none(self):
        assert parse_time("gibberish xyz") is None


# ── Banner helpers ────────────────────────────────────────────────────────────

class TestEscaping:
    def test_osa_escape_quotes(self):
        assert '\\"' in _osa_escape('say "hello"')

    def test_osa_escape_backslash(self):
        assert '\\\\' in _osa_escape("path\\to\\file")

    def test_ps_escape_single_quote(self):
        assert "''" in _ps_escape("it's here")

    def test_osa_escape_safe_string(self):
        s = "hello world"
        assert _osa_escape(s) == s


# ── post_banner (mocked subprocess) ──────────────────────────────────────────

class TestPostBanner:
    @patch("jarvis.actions.notify.subprocess.run")
    @patch("jarvis.actions.notify.SYSTEM", "Darwin")
    def test_calls_osascript_on_darwin(self, mock_run):
        notify._cfg = {"sound": False}
        post_banner("Jarvis", "Timer done", subtitle="5 minutes")
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
        assert "Timer done" in args[2]
        assert "Jarvis" in args[2]

    @patch("jarvis.actions.notify.subprocess.run")
    @patch("jarvis.actions.notify.SYSTEM", "Darwin")
    def test_sound_clause_included_when_enabled(self, mock_run):
        notify._cfg = {"sound": True}
        post_banner("T", "M")
        script = mock_run.call_args[0][0][2]
        assert "sound name" in script

    @patch("jarvis.actions.notify.subprocess.run")
    @patch("jarvis.actions.notify.SYSTEM", "Darwin")
    def test_sound_clause_omitted_when_disabled(self, mock_run):
        notify._cfg = {"sound": False}
        post_banner("T", "M")
        script = mock_run.call_args[0][0][2]
        assert "sound name" not in script

    @patch("jarvis.actions.notify.subprocess.run")
    @patch("jarvis.actions.notify.SYSTEM", "Darwin")
    def test_quotes_in_message_escaped(self, mock_run):
        notify._cfg = {"sound": False}
        post_banner("T", 'She said "hello"')
        script = mock_run.call_args[0][0][2]
        # The literal `"` must not appear unescaped inside the AppleScript string
        assert '\\"' in script

    @patch("jarvis.actions.notify.subprocess.run")
    @patch("jarvis.actions.notify.SYSTEM", "Windows")
    def test_calls_powershell_on_windows(self, mock_run):
        notify._cfg = {"sound": False}
        post_banner("Jarvis", "Timer done")
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "powershell" in args[0].lower()


# ── NotificationScheduler ─────────────────────────────────────────────────────

class TestNotificationScheduler:
    def setup_method(self):
        self.sched = NotificationScheduler()

    def _fire_soon(self, type_="timer", label="test", speak_text="done"):
        fire_at = datetime.now() + timedelta(milliseconds=50)
        return self.sched.schedule(type_, label, fire_at, speak_text)

    @patch("jarvis.actions.notify.post_banner")
    def test_fires_after_delay(self, mock_banner):
        fired = threading.Event()
        orig_fire = self.sched._fire

        def intercepted(item_id):
            orig_fire(item_id)
            fired.set()

        self.sched._fire = intercepted
        item_id = self._fire_soon()
        assert fired.wait(timeout=2), "Item did not fire within 2 s"

    @patch("jarvis.actions.notify.post_banner")
    def test_cancel_prevents_fire(self, mock_banner):
        item_id = self._fire_soon()
        cancelled = self.sched.cancel(item_id)
        time.sleep(0.15)  # wait past fire time
        assert cancelled
        mock_banner.assert_not_called()

    def test_cancel_nonexistent_returns_false(self):
        assert self.sched.cancel("99999") is False

    @patch("jarvis.actions.notify.post_banner")
    def test_cancel_latest_by_type(self, _):
        self.sched.schedule("timer", "A", datetime.now() + timedelta(hours=1), "x")
        self.sched.schedule("alarm", "B", datetime.now() + timedelta(hours=1), "x")
        result = self.sched.cancel_latest(type_="timer")
        assert result is not None
        assert result.type == "timer"
        assert len(self.sched.list_items()) == 1  # alarm still there

    @patch("jarvis.actions.notify.post_banner")
    def test_cancel_latest_no_filter(self, _):
        self.sched.schedule("timer", "A", datetime.now() + timedelta(hours=1), "x")
        self.sched.schedule("alarm", "B", datetime.now() + timedelta(hours=2), "x")
        result = self.sched.cancel_latest()
        assert result.label == "B"  # most recently added

    def test_list_items_sorted_by_fire_time(self):
        t1 = datetime.now() + timedelta(minutes=10)
        t2 = datetime.now() + timedelta(minutes=5)
        self.sched.schedule("timer", "later", t1, "x")
        self.sched.schedule("alarm", "sooner", t2, "x")
        items = self.sched.list_items()
        assert items[0].label == "sooner"
        assert items[1].label == "later"

    @patch("jarvis.actions.notify.post_banner")
    def test_fire_calls_synthesizer(self, _):
        mock_synth = MagicMock()
        notify._synthesizer = mock_synth
        fired = threading.Event()
        orig = self.sched._fire

        def wrapper(item_id):
            orig(item_id)
            fired.set()

        self.sched._fire = wrapper
        self._fire_soon(speak_text="hello boss")
        fired.wait(timeout=2)
        mock_synth.speak.assert_called_once_with("hello boss")
        notify._synthesizer = None

    @patch("jarvis.actions.notify.post_banner")
    def test_fire_stores_last_fired_for_snooze(self, _):
        fired = threading.Event()
        orig = self.sched._fire

        def wrapper(item_id):
            orig(item_id)
            fired.set()

        self.sched._fire = wrapper
        self._fire_soon(type_="alarm", label="morning", speak_text="wake up")
        fired.wait(timeout=2)
        assert self.sched._last_fired is not None
        assert self.sched._last_fired["label"] == "morning"

    @patch("jarvis.actions.notify.post_banner")
    def test_clear(self, _):
        for i in range(3):
            self.sched.schedule("timer", f"t{i}", datetime.now() + timedelta(hours=1), "x")
        n = self.sched.clear()
        assert n == 3
        assert self.sched.list_items() == []


# ── Action functions ──────────────────────────────────────────────────────────

class TestSetTimer:
    def setup_method(self):
        _reset()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_valid_duration(self, mock_sched):
        mock_sched.return_value = "1"
        result = notify.set_timer("5 minutes")
        assert "5 minute" in result.lower()
        mock_sched.assert_called_once()
        _, label, fire_at, _ = mock_sched.call_args[0]
        assert abs((fire_at - datetime.now()).total_seconds() - 300) < 2

    def test_unknown_duration(self):
        result = notify.set_timer("whenever")
        assert "didn't understand" in result.lower()

    def test_zero_duration(self):
        result = notify.set_timer("0 seconds")
        assert "greater than zero" in result.lower()

    def test_too_long(self):
        notify._cfg["max_timer_hours"] = 1
        result = notify.set_timer("2 hours")
        assert "shorter" in result.lower() or "too far" in result.lower() or "over" in result.lower()

    def test_disabled(self):
        notify._cfg["enabled"] = False
        result = notify.set_timer("5 minutes")
        assert "disabled" in result.lower()


class TestSetAlarm:
    def setup_method(self):
        _reset()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_valid_time(self, mock_sched):
        mock_sched.return_value = "1"
        result = notify.set_alarm("7:30 AM")
        assert "alarm set" in result.lower()
        mock_sched.assert_called_once()

    def test_unparseable_time(self):
        result = notify.set_alarm("blah blah")
        assert "couldn't parse" in result.lower()

    def test_disabled(self):
        notify._cfg["enabled"] = False
        result = notify.set_alarm("8 AM")
        assert "disabled" in result.lower()


class TestSetReminderDuration:
    def setup_method(self):
        _reset()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_schedules_reminder(self, mock_sched):
        mock_sched.return_value = "1"
        result = notify.set_reminder_duration("call mom", "10 minutes")
        assert "reminder set" in result.lower()
        assert "call mom" in result

    def test_unknown_duration(self):
        result = notify.set_reminder_duration("call mom", "soon")
        assert "didn't understand" in result.lower()


class TestSetReminderTime:
    def setup_method(self):
        _reset()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_schedules_reminder(self, mock_sched):
        mock_sched.return_value = "1"
        result = notify.set_reminder_time("take pills", "9 PM")
        assert "reminder set" in result.lower()
        assert "take pills" in result


class TestListScheduled:
    def setup_method(self):
        _reset()

    def test_empty(self):
        result = notify.list_scheduled()
        assert "no active" in result.lower()

    def test_shows_items(self):
        notify._scheduler.schedule(
            "timer", "coffee",
            datetime.now() + timedelta(minutes=5), "done"
        )
        result = notify.list_scheduled()
        assert "1 pending" in result.lower()
        assert "coffee" in result


class TestCancelItem:
    def setup_method(self):
        _reset()

    def test_cancel_no_items(self):
        result = notify.cancel_item()
        assert "no active" in result.lower()

    def test_cancel_latest_timer(self):
        notify._scheduler.schedule(
            "timer", "coffee",
            datetime.now() + timedelta(hours=1), "done"
        )
        result = notify.cancel_item("timer")
        assert "cancelled" in result.lower()
        assert "coffee" in result.lower()

    def test_cancel_by_type_filter(self):
        notify._scheduler.schedule("timer", "A", datetime.now() + timedelta(hours=1), "x")
        notify._scheduler.schedule("alarm", "B", datetime.now() + timedelta(hours=2), "x")
        notify.cancel_item("alarm")
        items = notify._scheduler.list_items()
        assert len(items) == 1
        assert items[0].type == "timer"


class TestSnooze:
    def setup_method(self):
        _reset()

    def test_no_last_fired(self):
        result = notify.snooze()
        assert "nothing" in result.lower()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_snooze_with_default_duration(self, mock_sched):
        mock_sched.return_value = "2"
        notify._scheduler._last_fired = {
            "type": "alarm", "label": "morning", "speak_text": "wake up"
        }
        result = notify.snooze()
        assert "snoozed" in result.lower()
        assert "5 minute" in result.lower()

    @patch("jarvis.actions.notify.NotificationScheduler.schedule")
    def test_snooze_with_custom_duration(self, mock_sched):
        mock_sched.return_value = "3"
        notify._scheduler._last_fired = {
            "type": "alarm", "label": "morning", "speak_text": "wake up"
        }
        result = notify.snooze("10 minutes")
        assert "10 minute" in result.lower()
