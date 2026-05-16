"""Voice-triggered reminders, alarms, and timers with macOS banner notifications.

Each item is scheduled on a daemon thread.  When it fires:
  1. An OS banner notification is posted (macOS: osascript, Windows: WinRT toast).
  2. The injected Synthesizer speaks the alert so Jarvis "calls out" even if the
     screen is locked or the banner is missed.
  3. An optional on_fire callback is invoked (used by core.py to broadcast IPC).

Context is injected by core.py once at startup via ``set_notification_context()``.

Config section (config.yaml):
    notifications:
      enabled: true
      default_snooze_minutes: 5
      max_timer_hours: 24      # refuse timers/alarms further than this
      sound: true              # play the default alert sound with the banner
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Callable

log = logging.getLogger("jarvis.actions.notify")

SYSTEM = platform.system()

# ── Runtime context (injected by core.py) ────────────────────────────────────

_cfg: dict = {}
_synthesizer = None     # jarvis.speech.synthesizer.Synthesizer
_on_fire_cb: Callable | None = None   # optional IPC broadcast hook


def set_notification_context(
    cfg: dict,
    synthesizer=None,
    on_fire: Callable | None = None,
) -> None:
    global _cfg, _synthesizer, _on_fire_cb
    _cfg = cfg or {}
    _synthesizer = synthesizer
    _on_fire_cb = on_fire


def _is_enabled() -> bool:
    return _cfg.get("enabled", True)


def _use_sound() -> bool:
    return _cfg.get("sound", True)


def _max_seconds() -> int:
    return int(_cfg.get("max_timer_hours", 24)) * 3600


def _default_snooze_sec() -> int:
    return int(_cfg.get("default_snooze_minutes", 5)) * 60


# ── OS banner ─────────────────────────────────────────────────────────────────

def _osa_escape(s: str) -> str:
    """Escape a string for embedding inside AppleScript double-quoted literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _ps_escape(s: str) -> str:
    """Escape a string for embedding inside PowerShell single-quoted literals."""
    return s.replace("'", "''")


def post_banner(title: str, message: str, subtitle: str = "") -> None:
    """Post an OS notification banner.  Safe to call from any thread."""
    t = _osa_escape(title)
    m = _osa_escape(message)
    s = _osa_escape(subtitle)
    sound_clause = ' sound name "default"' if _use_sound() else ""

    if SYSTEM == "Darwin":
        subtitle_clause = f' subtitle "{s}"' if s else ""
        script = (
            f'display notification "{m}"'
            f' with title "{t}"'
            f'{subtitle_clause}'
            f'{sound_clause}'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                timeout=5,
                capture_output=True,
            )
        except Exception as exc:
            log.warning("osascript banner failed: %s", exc)

    elif SYSTEM == "Windows":
        # WinRT toast via PowerShell (works on Windows 10+)
        t_ps = _ps_escape(title)
        m_ps = _ps_escape(message)
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager,"
            " Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument,"
            " Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null\n"
            "$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02\n"
            "$xml = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent($t)\n"
            f"$xml.GetElementsByTagName('text').Item(0).InnerText = '{t_ps}'\n"
            f"$xml.GetElementsByTagName('text').Item(1).InnerText = '{m_ps}'\n"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)\n"
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('Jarvis').Show($toast)"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                timeout=10,
                capture_output=True,
            )
        except Exception as exc:
            log.warning("PowerShell toast failed: %s", exc)

    else:
        log.info("Banner not supported on %s — skipping.", SYSTEM)


# ── Duration & time parsing ───────────────────────────────────────────────────

_DUR_PATTERNS = [
    (re.compile(r"\b(\d+)\s*h(r|ou?r)?s?\b", re.I), lambda m: int(m.group(1)) * 3600),
    (re.compile(r"\b(\d+)\s*m(in(ute)?)?s?\b", re.I), lambda m: int(m.group(1)) * 60),
    (re.compile(r"\b(\d+)\s*s(ec(ond)?)?s?\b", re.I), lambda m: int(m.group(1))),
    (re.compile(r"\ba\s+minute\b", re.I), lambda m: 60),
    (re.compile(r"\ba\s+second\b", re.I), lambda m: 1),
    (re.compile(r"\ban?\s+hour\b", re.I), lambda m: 3600),
]


def parse_duration(text: str) -> int | None:
    """Return total seconds parsed from a duration string, or None."""
    total = 0
    found = False
    for pattern, calc in _DUR_PATTERNS:
        m = pattern.search(text)
        if m:
            total += calc(m)
            found = True
    return total if found else None


def _human_duration(seconds: int) -> str:
    """Return a human-readable duration string."""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) if parts else f"{seconds} seconds"


def parse_time(text: str) -> datetime | None:
    """Parse a clock-time string and return the next upcoming datetime for it."""
    text = text.strip().lower()
    now = datetime.now()

    # Keywords
    if "noon" in text:
        t = now.replace(hour=12, minute=0, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)
    if "midnight" in text:
        t = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)

    # HH:MM [AM/PM]
    m = re.search(r"\b(\d{1,2})[: ](\d{2})\s*(am|pm)?\b", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        meridiem = m.group(3)
        h = _apply_meridiem(h, meridiem)
        if h is None:
            return None
        t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)

    # H [AM/PM]  (no minutes)
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
    if m:
        h = int(m.group(1))
        h = _apply_meridiem(h, m.group(2))
        if h is None:
            return None
        t = now.replace(hour=h, minute=0, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)

    # Fall back to dateutil if available
    try:
        from dateutil import parser as dp
        t = dp.parse(text, fuzzy=True, default=now)
        return t if t > now else t + timedelta(days=1)
    except Exception:
        return None


def _apply_meridiem(h: int, meridiem: str | None) -> int | None:
    """Adjust hour for AM/PM, return None if hour is out of range."""
    if h < 0 or h > 23:
        return None
    if meridiem is None:
        return h % 24
    meridiem = meridiem.lower()
    if meridiem == "pm" and h != 12:
        h += 12
    elif meridiem == "am" and h == 12:
        h = 0
    return h % 24


# ── Scheduler ─────────────────────────────────────────────────────────────────

class _Item:
    __slots__ = ("id", "type", "label", "fire_time", "speak_text", "timer")

    def __init__(self, id_: str, type_: str, label: str,
                 fire_time: datetime, speak_text: str, timer: threading.Timer):
        self.id = id_
        self.type = type_
        self.label = label
        self.fire_time = fire_time
        self.speak_text = speak_text
        self.timer = timer


class NotificationScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, _Item] = {}
        self._counter = 0
        self._last_fired: dict | None = None  # for snooze

    def _next_id(self) -> str:
        self._counter += 1
        return str(self._counter)

    def schedule(
        self,
        type_: str,
        label: str,
        fire_time: datetime,
        speak_text: str,
    ) -> str:
        """Schedule an item; returns its ID."""
        item_id = self._next_id()
        delay = max(0.0, (fire_time - datetime.now()).total_seconds())

        timer = threading.Timer(
            interval=delay,
            function=self._fire,
            args=(item_id,),
        )
        timer.daemon = True

        item = _Item(
            id_=item_id,
            type_=type_,
            label=label,
            fire_time=fire_time,
            speak_text=speak_text,
            timer=timer,
        )
        with self._lock:
            self._items[item_id] = item

        timer.start()
        log.info("Scheduled %s '%s' in %.0f s (id=%s)", type_, label, delay, item_id)
        return item_id

    def _fire(self, item_id: str) -> None:
        with self._lock:
            item = self._items.pop(item_id, None)
        if item is None:
            return  # already cancelled

        log.info("Firing %s '%s'", item.type, item.label)

        # Remember for snooze
        self._last_fired = {
            "type": item.type,
            "label": item.label,
            "speak_text": item.speak_text,
        }

        # OS banner
        title = f"Jarvis — {item.type.capitalize()}"
        post_banner(title, item.speak_text, subtitle=item.label)

        # Voice alert
        if _synthesizer:
            try:
                _synthesizer.speak(item.speak_text)
            except Exception as exc:
                log.error("Synthesizer error during notification fire: %s", exc)

        # Optional IPC callback
        if _on_fire_cb:
            try:
                _on_fire_cb({
                    "type": "notification",
                    "notif_type": item.type,
                    "label": item.label,
                    "message": item.speak_text,
                })
            except Exception as exc:
                log.warning("on_fire callback error: %s", exc)

    def cancel(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.pop(item_id, None)
        if item:
            item.timer.cancel()
            return True
        return False

    def cancel_latest(self, type_: str | None = None) -> _Item | None:
        """Cancel the most-recently-added item (optionally filtered by type)."""
        with self._lock:
            candidates = [
                item for item in self._items.values()
                if type_ is None or item.type == type_
            ]
        if not candidates:
            return None
        target = max(candidates, key=lambda x: int(x.id))
        self.cancel(target.id)
        return target

    def list_items(self) -> list[_Item]:
        with self._lock:
            return sorted(self._items.values(), key=lambda x: x.fire_time)

    def clear(self) -> int:
        with self._lock:
            items = list(self._items.values())
            self._items.clear()
        for item in items:
            item.timer.cancel()
        return len(items)


# Module-level singleton
_scheduler = NotificationScheduler()


# ── Public action functions ───────────────────────────────────────────────────

def set_timer(duration: str) -> str:
    """Set a countdown timer (e.g., 'five minutes', '30 seconds', '2 hours')."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    secs = parse_duration(duration)
    if secs is None:
        return f"I didn't understand the duration '{duration}', Boss."
    if secs <= 0:
        return "The timer duration must be greater than zero, Boss."
    if secs > _max_seconds():
        return (
            f"That's over {_cfg.get('max_timer_hours', 24)} hours. "
            "Please set a shorter timer, Boss."
        )

    label = _human_duration(secs)
    fire_at = datetime.now() + timedelta(seconds=secs)
    speak_text = f"Boss, your {label} timer is done."
    _scheduler.schedule("timer", label, fire_at, speak_text)
    return f"Timer set for {label}."


def set_alarm(time: str) -> str:
    """Set an alarm at a specific clock time (e.g., '7:30 AM', '8 o'clock')."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    fire_at = parse_time(time)
    if fire_at is None:
        return f"I couldn't parse the time '{time}', Boss. Try something like '7:30 AM'."

    secs_until = (fire_at - datetime.now()).total_seconds()
    if secs_until > _max_seconds():
        return (
            f"That alarm is more than {_cfg.get('max_timer_hours', 24)} hours away. "
            "Please set a closer alarm, Boss."
        )

    label = fire_at.strftime("%-I:%M %p") if SYSTEM == "Darwin" else fire_at.strftime("%I:%M %p").lstrip("0")
    speak_text = f"Boss, your alarm is going off. It is {label}."
    _scheduler.schedule("alarm", label, fire_at, speak_text)
    return f"Alarm set for {label}."


def set_reminder_duration(message: str, duration: str) -> str:
    """Set a reminder to fire after a duration (e.g., 'in 5 minutes to call mom')."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    secs = parse_duration(duration)
    if secs is None:
        return f"I didn't understand the duration '{duration}', Boss."
    if secs <= 0:
        return "The reminder duration must be greater than zero, Boss."
    if secs > _max_seconds():
        return "That reminder is set too far in the future, Boss."

    message = message.strip()
    fire_at = datetime.now() + timedelta(seconds=secs)
    when = _human_duration(secs)
    speak_text = f"Boss, reminder: {message}."
    _scheduler.schedule("reminder", message, fire_at, speak_text)
    return f"Reminder set for {when} from now: {message}."


def set_reminder_time(message: str, time: str) -> str:
    """Set a reminder to fire at a specific clock time."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    fire_at = parse_time(time)
    if fire_at is None:
        return f"I couldn't parse the time '{time}', Boss. Try something like '3 PM'."

    secs_until = (fire_at - datetime.now()).total_seconds()
    if secs_until > _max_seconds():
        return "That reminder is set too far in the future, Boss."

    message = message.strip()
    label_time = fire_at.strftime("%-I:%M %p") if SYSTEM == "Darwin" else fire_at.strftime("%I:%M %p").lstrip("0")
    speak_text = f"Boss, reminder: {message}."
    _scheduler.schedule("reminder", message, fire_at, speak_text)
    return f"Reminder set for {label_time}: {message}."


def list_scheduled() -> str:
    """Return a spoken-friendly summary of all pending timers, alarms, and reminders."""
    items = _scheduler.list_items()
    if not items:
        return "You have no active timers, alarms, or reminders, Boss."

    now = datetime.now()
    lines = [f"You have {len(items)} pending item{'s' if len(items) != 1 else ''}:"]
    for item in items:
        secs_left = max(0, int((item.fire_time - now).total_seconds()))
        when = _human_duration(secs_left)
        lines.append(f"  {item.type.capitalize()}: {item.label} — in {when} (id {item.id})")
    return "\n".join(lines)


def cancel_item(item: str = "") -> str:
    """Cancel the most recently added timer/alarm/reminder."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    item = item.strip().lower()

    # Determine type filter
    type_filter: str | None = None
    if "timer" in item:
        type_filter = "timer"
    elif "alarm" in item:
        type_filter = "alarm"
    elif "reminder" in item:
        type_filter = "reminder"

    cancelled = _scheduler.cancel_latest(type_=type_filter)
    if cancelled is None:
        kind = type_filter or "item"
        return f"No active {kind} to cancel, Boss."
    return f"Cancelled {cancelled.type}: {cancelled.label}."


def snooze(duration: str = "") -> str:
    """Re-schedule the last fired alarm/timer for another duration (default 5 min)."""
    if not _is_enabled():
        return "Notifications are disabled, Boss."

    last = _scheduler._last_fired
    if last is None:
        return "Nothing to snooze, Boss."

    secs = parse_duration(duration) if duration.strip() else _default_snooze_sec()
    if secs is None or secs <= 0:
        secs = _default_snooze_sec()

    fire_at = datetime.now() + timedelta(seconds=secs)
    _scheduler.schedule(last["type"], last["label"], fire_at, last["speak_text"])
    return f"Snoozed for {_human_duration(secs)}."
