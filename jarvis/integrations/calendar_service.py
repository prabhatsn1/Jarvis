"""
Unified calendar service for Google Calendar and Outlook (Microsoft Graph).

Usage::

    from jarvis.integrations.calendar_service import CalendarService
    svc = CalendarService(integrations_cfg)
    events = svc.get_todays_schedule()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

log = logging.getLogger("jarvis.integrations.calendar")

# ── Normalised event model ───────────────────────────────────────────────────


@dataclass
class CalendarEvent:
    source: str           # "google" | "outlook"
    calendar_name: str
    title: str
    start_dt: datetime
    end_dt: datetime
    location: str = ""
    is_all_day: bool = False
    attendees_count: int = 0
    raw_id: str = ""

    def __lt__(self, other: "CalendarEvent") -> bool:
        return self.start_dt < other.start_dt


# ── Retry helper ─────────────────────────────────────────────────────────────

_RETRY_BASE = 1.0   # seconds
_RETRY_MAX = 3      # attempts


def _with_retry(fn, *args, **kwargs):
    """Call *fn* with simple exponential back-off.  Returns result or raises."""
    delay = _RETRY_BASE
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRY_MAX):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            log.warning("Attempt %d/%d failed (%s), retrying in %.1fs…",
                        attempt + 1, _RETRY_MAX, exc, delay)
            time.sleep(delay)
            delay *= 2
    raise last_exc  # type: ignore[misc]


# ── Google Calendar adapter ──────────────────────────────────────────────────


class GoogleCalendarAdapter:
    """Fetches events from all Google Calendars for a given account."""

    def __init__(self, account_id: str, creds, max_events: int = 20):
        self._account_id = account_id
        self._creds = creds
        self._max_events = max_events

    def fetch_events(self, start: datetime, end: datetime) -> List[CalendarEvent]:
        try:
            from googleapiclient.discovery import build
        except ImportError:
            log.error("google-api-python-client is not installed.")
            return []

        try:
            service = build("calendar", "v3", credentials=self._creds, cache_discovery=False)
            calendars = _with_retry(
                service.calendarList().list().execute
            )
        except Exception as exc:
            log.error("Google Calendar list error for %s: %s", self._account_id, exc)
            return []

        events: List[CalendarEvent] = []
        time_min = start.isoformat()
        time_max = end.isoformat()

        for cal in calendars.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            try:
                result = _with_retry(
                    service.events().list(
                        calendarId=cal_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=self._max_events,
                        singleEvents=True,
                        orderBy="startTime",
                    ).execute
                )
            except Exception as exc:
                log.warning("Could not fetch events from calendar %s: %s", cal_name, exc)
                continue

            for item in result.get("items", []):
                ev = _parse_google_event(item, cal_name)
                if ev:
                    events.append(ev)

        return events


def _parse_google_event(item: dict, calendar_name: str) -> Optional[CalendarEvent]:
    status = item.get("status", "confirmed")
    if status == "cancelled":
        return None

    title = item.get("summary", "(No title)")
    raw_id = item.get("id", "")
    location = item.get("location", "")
    attendees = item.get("attendees", [])
    attendees_count = len(attendees)

    start_raw = item.get("start", {})
    end_raw = item.get("end", {})

    is_all_day = "date" in start_raw and "dateTime" not in start_raw

    if is_all_day:
        start_dt = datetime.fromisoformat(start_raw["date"]).replace(
            hour=0, minute=0, second=0, tzinfo=timezone.utc
        )
        end_dt = datetime.fromisoformat(end_raw.get("date", start_raw["date"])).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    else:
        try:
            start_dt = datetime.fromisoformat(start_raw["dateTime"])
            end_dt = datetime.fromisoformat(end_raw["dateTime"])
        except (KeyError, ValueError) as exc:
            log.debug("Skipping event with bad datetime: %s", exc)
            return None

    return CalendarEvent(
        source="google",
        calendar_name=calendar_name,
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        location=location,
        is_all_day=is_all_day,
        attendees_count=attendees_count,
        raw_id=raw_id,
    )


# ── Outlook Calendar adapter ─────────────────────────────────────────────────

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendarAdapter:
    """Fetches events from Microsoft Graph Calendar for a given account."""

    def __init__(self, account_id: str, access_token: str, max_events: int = 20):
        self._account_id = account_id
        self._token = access_token
        self._max_events = max_events

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Prefer": 'outlook.timezone="UTC"',
        }

    def fetch_events(self, start: datetime, end: datetime) -> List[CalendarEvent]:
        try:
            import requests
        except ImportError:
            log.error("requests library is not installed.")
            return []

        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S")
        url = (
            f"{_GRAPH_BASE}/me/calendarView"
            f"?startDateTime={start_str}Z&endDateTime={end_str}Z"
            f"&$top={self._max_events}&$orderby=start/dateTime"
            "&$select=id,subject,start,end,location,attendees,isAllDay,calendar"
        )

        events: List[CalendarEvent] = []
        while url:
            try:
                resp = _with_retry(
                    _graph_get, url, self._headers()
                )
            except Exception as exc:
                log.error("Outlook Calendar fetch error for %s: %s", self._account_id, exc)
                break

            for item in resp.get("value", []):
                ev = _parse_outlook_event(item)
                if ev:
                    events.append(ev)

            url = resp.get("@odata.nextLink")

        return events


def _graph_get(url: str, headers: dict) -> dict:
    import requests

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def _parse_outlook_event(item: dict) -> Optional[CalendarEvent]:
    title = item.get("subject", "(No title)")
    raw_id = item.get("id", "")
    is_all_day = item.get("isAllDay", False)
    location = (item.get("location") or {}).get("displayName", "")
    attendees = item.get("attendees", [])
    attendees_count = len(attendees)

    cal_info = item.get("calendar") or {}
    calendar_name = cal_info.get("name", "Calendar")

    start_raw = (item.get("start") or {}).get("dateTime", "")
    end_raw = (item.get("end") or {}).get("dateTime", "")

    try:
        start_dt = datetime.fromisoformat(start_raw).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end_raw).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError) as exc:
        log.debug("Skipping Outlook event with bad datetime: %s", exc)
        return None

    return CalendarEvent(
        source="outlook",
        calendar_name=calendar_name,
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        location=location,
        is_all_day=is_all_day,
        attendees_count=attendees_count,
        raw_id=raw_id,
    )


# ── Unified CalendarService ──────────────────────────────────────────────────


class CalendarService:
    """
    Provider-agnostic calendar facade.

    Parameters
    ----------
    integrations_cfg:
        The ``integrations`` block from ``config.yaml``.
    connected_accounts:
        List of ``{"provider": str, "account_id": str}`` dicts (from store.py).
    """

    _CACHE_TTL = 60  # seconds

    def __init__(self, integrations_cfg: dict, connected_accounts: List[dict] | None = None):
        self._cfg = integrations_cfg or {}
        self._accounts: List[dict] = connected_accounts or []
        self._cache: dict = {}   # key → (timestamp, value)

    # ── cache helpers ────────────────────────────────────────────

    def _cached(self, key: str):
        entry = self._cache.get(key)
        if entry and time.time() - entry[0] < self._CACHE_TTL:
            return entry[1]
        return None

    def _store(self, key: str, value):
        self._cache[key] = (time.time(), value)
        return value

    # ── timezone helper ──────────────────────────────────────────

    def _local_tz(self):
        cfg_tz = self._cfg.get("timezone", "local")
        if cfg_tz and cfg_tz != "local":
            try:
                from zoneinfo import ZoneInfo
                return ZoneInfo(cfg_tz)
            except Exception:
                pass
        # Fall back to system local timezone
        return datetime.now().astimezone().tzinfo

    def _day_window(self, reference: datetime | None = None) -> tuple[datetime, datetime]:
        """Return UTC-aware (start_of_day, end_of_day) in the configured timezone."""
        tz = self._local_tz()
        now = (reference or datetime.now()).astimezone(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return day_start, day_end

    # ── adapter builders ─────────────────────────────────────────

    def _get_adapters(self) -> list:
        from jarvis.integrations.auth import get_valid_credentials

        adapters = []
        cal_cfg = self._cfg.get("calendar", {})
        max_ev = self._cfg.get("calendar", {}).get("max_events_per_query", 20)

        for account in self._accounts:
            provider = account.get("provider", "").lower()
            account_id = account.get("account_id", "")

            if provider == "google" and cal_cfg.get("google_enabled", True):
                creds = get_valid_credentials("google", account_id, self._cfg)
                if creds:
                    adapters.append(GoogleCalendarAdapter(account_id, creds, max_ev))
                else:
                    log.warning("No valid Google credentials for %s", account_id)

            elif provider in ("microsoft", "outlook") and cal_cfg.get("outlook_enabled", True):
                token = get_valid_credentials("microsoft", account_id, self._cfg)
                if token:
                    adapters.append(OutlookCalendarAdapter(account_id, token, max_ev))
                else:
                    log.warning("No valid Microsoft credentials for %s", account_id)

        return adapters

    # ── public API ───────────────────────────────────────────────

    def list_connected_accounts(self) -> List[dict]:
        """Return the list of connected account metadata dicts."""
        return list(self._accounts)

    def get_todays_schedule(self, user_tz=None) -> List[CalendarEvent]:
        """Return all calendar events for the current local day, sorted by start time."""
        cache_key = f"today:{datetime.now().date()}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        adapters = self._get_adapters()
        if not adapters:
            return self._store(cache_key, [])

        start, end = self._day_window()
        all_events: List[CalendarEvent] = []
        for adapter in adapters:
            try:
                all_events.extend(adapter.fetch_events(start, end))
            except Exception as exc:
                log.error("Adapter %s fetch error: %s", type(adapter).__name__, exc)

        all_events.sort()
        return self._store(cache_key, all_events)

    def get_upcoming_events(self, hours: int = 24, limit: int = 10) -> List[CalendarEvent]:
        """Return the next *limit* events within the next *hours* hours."""
        cache_key = f"upcoming:{hours}:{limit}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        adapters = self._get_adapters()
        if not adapters:
            return self._store(cache_key, [])

        tz = self._local_tz()
        now = datetime.now().astimezone(tz)
        end = now + timedelta(hours=hours)

        all_events: List[CalendarEvent] = []
        for adapter in adapters:
            try:
                all_events.extend(adapter.fetch_events(now, end))
            except Exception as exc:
                log.error("Adapter %s fetch error: %s", type(adapter).__name__, exc)

        # Only events that haven't ended yet, sorted, then limited
        upcoming = [e for e in all_events if e.end_dt >= now]
        upcoming.sort()
        return self._store(cache_key, upcoming[:limit])
