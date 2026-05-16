"""
Actions for calendar/email integration voice commands.

Core injects the config and memory store via ``set_integrations_context()``
at startup.  All public functions follow the standard Jarvis action signature:
they accept only slot kwargs and return a spoken-friendly string.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("jarvis.actions.integrations")

# Module-level imports allow test patches to work and avoid repeated lazy imports.
# These are optional at import time — missing deps are caught at call time.
try:
    from jarvis.integrations.calendar_service import CalendarService
except Exception:  # pragma: no cover
    CalendarService = None  # type: ignore[assignment,misc]

try:
    from jarvis.integrations.auth import (
        connect_google_account,
        connect_microsoft_account,
        disconnect_account as _auth_disconnect,
    )
except Exception:  # pragma: no cover
    connect_google_account = None  # type: ignore[assignment]
    connect_microsoft_account = None  # type: ignore[assignment]
    _auth_disconnect = None  # type: ignore[assignment]

# ── Runtime context (set by core.py) ────────────────────────────────────────

_integrations_cfg: dict = {}
_memory_store = None       # MemoryStore instance


def set_integrations_context(cfg: dict, store=None) -> None:
    """Called once by core.py after config is loaded."""
    global _integrations_cfg, _memory_store
    _integrations_cfg = cfg or {}
    _memory_store = store


# ── Internal helpers ─────────────────────────────────────────────────────────

def _connected_accounts() -> list[dict]:
    """Return connected account list from the memory store (or empty list)."""
    if _memory_store is None:
        return []
    try:
        return _memory_store.list_connected_accounts()
    except Exception as exc:
        log.warning("Could not read connected accounts: %s", exc)
        return []


def _not_connected_message() -> str:
    return (
        "I am not connected yet, Boss. "
        "Say connect Google account or connect Outlook account to get started."
    )


def _format_time(dt: datetime) -> str:
    """Return a spoken-friendly time string, e.g. '10:00 AM'."""
    # Convert to local time if UTC-aware
    try:
        local_dt = dt.astimezone()
    except Exception:
        local_dt = dt
    return local_dt.strftime("%I:%M %p").lstrip("0") or local_dt.strftime("%I:%M %p")


# ── schedule_today ───────────────────────────────────────────────────────────

def schedule_today() -> str:
    """Return a spoken summary of today's calendar events."""
    accounts = _connected_accounts()
    if not accounts:
        return _not_connected_message()

    if not _integrations_cfg.get("enabled", True):
        return "Calendar integration is disabled, Boss."

    try:
        if CalendarService is None:
            return "Calendar service is not available. Check integration dependencies."
        svc = CalendarService(_integrations_cfg, accounts)
        events = svc.get_todays_schedule()
    except Exception as exc:
        log.error("schedule_today error: %s", exc)
        return "I had trouble reaching your calendar, Boss. Please try again in a moment."

    if not events:
        return "You are clear today, Boss. No events on your calendar."

    count = len(events)
    parts = [f"Boss, you have {count} event{'s' if count != 1 else ''} today."]

    for i, ev in enumerate(events):
        if ev.is_all_day:
            time_str = "all day"
        else:
            time_str = f"at {_format_time(ev.start_dt)}"

        if i == 0:
            parts.append(f"First is {ev.title} {time_str}.")
        elif i == len(events) - 1:
            parts.append(f"And finally {ev.title} {time_str}.")
        else:
            parts.append(f"Next is {ev.title} {time_str}.")

    return " ".join(parts)


# ── next_event ───────────────────────────────────────────────────────────────

def next_event() -> str:
    """Return a spoken summary of the very next calendar event from now."""
    accounts = _connected_accounts()
    if not accounts:
        return _not_connected_message()

    if not _integrations_cfg.get("enabled", True):
        return "Calendar integration is disabled, Boss."

    try:
        if CalendarService is None:
            return "Calendar service is not available. Check integration dependencies."
        svc = CalendarService(_integrations_cfg, accounts)
        upcoming = svc.get_upcoming_events(hours=24, limit=1)
    except Exception as exc:
        log.error("next_event error: %s", exc)
        return "I had trouble reaching your calendar, Boss. Please try again."

    if not upcoming:
        return "You have nothing coming up in the next 24 hours, Boss."

    ev = upcoming[0]
    if ev.is_all_day:
        return f"Your next event is {ev.title}, and it is an all-day event."
    time_str = _format_time(ev.start_dt)
    return f"Your next event is {ev.title} at {time_str}."


# ── connect_google ────────────────────────────────────────────────────────────

def connect_google() -> str:
    """Initiate the Google OAuth flow and persist the token."""
    google_cfg = _integrations_cfg.get("google", {})
    client_id = google_cfg.get("client_id", "")
    client_secret = google_cfg.get("client_secret", "")

    if not client_id or not client_secret:
        return (
            "Google credentials are not configured, Boss. "
            "Please add your client ID and secret to config.yaml under integrations.google."
        )

    oauth_cfg = _integrations_cfg.get("oauth", {})
    redirect_port = int(oauth_cfg.get("redirect_port", 8765))

    try:
        if connect_google_account is None:
            return "Google auth module is not available. Check integration dependencies."
        result = connect_google_account(client_id, client_secret, redirect_port)
    except Exception as exc:
        log.error("connect_google error: %s", exc)
        return "Google authentication failed, Boss. Check the logs for details."

    if result["ok"]:
        email = result.get("email") or "your account"
        _save_account("google", email)
        return f"Google account connected successfully, Boss. I am now linked to {email}."
    return f"Google connection failed, Boss. {result.get('message', '')}"


# ── connect_outlook ───────────────────────────────────────────────────────────

def connect_outlook() -> str:
    """Initiate the Microsoft OAuth flow and persist the token."""
    ms_cfg = _integrations_cfg.get("microsoft", {})
    client_id = ms_cfg.get("client_id", "")
    client_secret = ms_cfg.get("client_secret", "")

    if not client_id or not client_secret:
        return (
            "Microsoft credentials are not configured, Boss. "
            "Please add your client ID and secret to config.yaml under integrations.microsoft."
        )

    oauth_cfg = _integrations_cfg.get("oauth", {})
    redirect_port = int(oauth_cfg.get("redirect_port", 8765))
    tenant = ms_cfg.get("tenant", "common")

    try:
        if connect_microsoft_account is None:
            return "Microsoft auth module is not available. Check integration dependencies."
        result = connect_microsoft_account(client_id, client_secret, tenant, redirect_port)
    except Exception as exc:
        log.error("connect_outlook error: %s", exc)
        return "Microsoft authentication failed, Boss. Check the logs for details."

    if result["ok"]:
        email = result.get("email") or "your account"
        _save_account("microsoft", email)
        return f"Outlook account connected successfully, Boss. I am now linked to {email}."
    return f"Outlook connection failed, Boss. {result.get('message', '')}"


# ── disconnect_account ────────────────────────────────────────────────────────

def disconnect_account(provider: str) -> str:
    """Remove stored credentials for the given provider."""
    provider = provider.strip().lower()

    # Map spoken provider names to canonical names
    _alias = {
        "google": "google",
        "gmail": "google",
        "google calendar": "google",
        "microsoft": "microsoft",
        "outlook": "microsoft",
        "outlook calendar": "microsoft",
    }
    canonical = _alias.get(provider)
    if not canonical:
        return f"I do not recognise {provider} as a provider, Boss. Try Google or Outlook."

    accounts = _connected_accounts()
    matching = [a for a in accounts if a.get("provider", "").lower() == canonical]
    if not matching:
        return f"No {provider} account is connected, Boss."

    removed_count = 0
    for account in matching:
        account_id = account.get("account_id", "")
        try:
            if _auth_disconnect is None:
                log.error("auth module unavailable for disconnect")
                continue
            result = _auth_disconnect(canonical, account_id)
            if result["ok"]:
                _remove_account(canonical, account_id)
                removed_count += 1
        except Exception as exc:
            log.error("disconnect_account error: %s", exc)

    if removed_count:
        return f"Disconnected {provider} account, Boss."
    return f"Could not remove {provider} credentials, Boss. Check logs for details."


# ── list_accounts ─────────────────────────────────────────────────────────────

def list_accounts() -> str:
    """Return a spoken summary of all connected accounts."""
    accounts = _connected_accounts()
    if not accounts:
        return _not_connected_message()

    google_accounts = [a for a in accounts if a.get("provider", "").lower() == "google"]
    ms_accounts = [a for a in accounts if a.get("provider", "").lower() in ("microsoft", "outlook")]

    parts = []
    if google_accounts:
        emails = ", ".join(a.get("account_id", "unknown") for a in google_accounts)
        parts.append(f"Google: {emails}")
    if ms_accounts:
        emails = ", ".join(a.get("account_id", "unknown") for a in ms_accounts)
        parts.append(f"Outlook: {emails}")

    if not parts:
        return _not_connected_message()

    return "Connected accounts — " + "; ".join(parts) + "."


# ── Store helpers ─────────────────────────────────────────────────────────────

def _save_account(provider: str, account_id: str) -> None:
    """Persist a newly connected account to the memory store."""
    if _memory_store is None:
        return
    try:
        _memory_store.save_connected_account(provider, account_id)
    except Exception as exc:
        log.warning("Could not persist account metadata: %s", exc)


def _remove_account(provider: str, account_id: str) -> None:
    """Remove a disconnected account from the memory store."""
    if _memory_store is None:
        return
    try:
        _memory_store.remove_connected_account(provider, account_id)
    except Exception as exc:
        log.warning("Could not remove account metadata: %s", exc)
