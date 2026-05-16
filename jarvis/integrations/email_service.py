"""
Email integration metadata and connectivity checks.

This module provides lightweight account-connection checks for Gmail (via
Google API) and Outlook Mail (via Microsoft Graph).  It is *not* intended to
read email bodies — only to verify that credentials are valid and list which
accounts are reachable.
"""

from __future__ import annotations

import logging
from typing import List, Optional

log = logging.getLogger("jarvis.integrations.email")

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Gmail connectivity ───────────────────────────────────────────────────────


def _check_gmail(account_id: str, creds) -> dict:
    """Return a status dict for a Gmail account."""
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile.get("emailAddress", account_id)
        return {
            "provider": "gmail",
            "account_id": account_id,
            "email": email_address,
            "status": "connected",
        }
    except ImportError:
        return {
            "provider": "gmail",
            "account_id": account_id,
            "status": "error",
            "detail": "google-api-python-client not installed",
        }
    except Exception as exc:
        log.warning("Gmail health check failed for %s: %s", account_id, exc)
        return {
            "provider": "gmail",
            "account_id": account_id,
            "status": "error",
            "detail": str(exc),
        }


# ── Outlook Mail connectivity ────────────────────────────────────────────────


def _check_outlook_mail(account_id: str, access_token: str) -> dict:
    """Return a status dict for an Outlook Mail account."""
    try:
        import requests

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        r = requests.get(
            f"{_GRAPH_BASE}/me/mailFolders/inbox",
            headers=headers,
            timeout=10,
        )
        if r.ok:
            return {
                "provider": "outlook_mail",
                "account_id": account_id,
                "status": "connected",
            }
        return {
            "provider": "outlook_mail",
            "account_id": account_id,
            "status": "error",
            "detail": f"HTTP {r.status_code}",
        }
    except ImportError:
        return {
            "provider": "outlook_mail",
            "account_id": account_id,
            "status": "error",
            "detail": "requests not installed",
        }
    except Exception as exc:
        log.warning("Outlook mail check failed for %s: %s", account_id, exc)
        return {
            "provider": "outlook_mail",
            "account_id": account_id,
            "status": "error",
            "detail": str(exc),
        }


# ── Public API ───────────────────────────────────────────────────────────────


class EmailService:
    """
    Lightweight email integration service for connectivity checks.

    Parameters
    ----------
    integrations_cfg:
        The ``integrations`` block from ``config.yaml``.
    connected_accounts:
        List of ``{"provider": str, "account_id": str}`` dicts.
    """

    def __init__(self, integrations_cfg: dict, connected_accounts: List[dict] | None = None):
        self._cfg = integrations_cfg or {}
        self._accounts: List[dict] = connected_accounts or []

    def list_connected_email_accounts(self) -> List[dict]:
        """Return metadata for all email-capable connected accounts."""
        email_cfg = self._cfg.get("email", {})
        result = []
        for account in self._accounts:
            provider = account.get("provider", "").lower()
            if provider == "google" and email_cfg.get("gmail_enabled", True):
                result.append({
                    "provider": "gmail",
                    "account_id": account.get("account_id", ""),
                    "status": "stored",
                })
            elif provider in ("microsoft", "outlook") and email_cfg.get("outlook_enabled", True):
                result.append({
                    "provider": "outlook_mail",
                    "account_id": account.get("account_id", ""),
                    "status": "stored",
                })
        return result

    def health_check_email_connections(self) -> List[dict]:
        """Perform live connectivity checks for all email accounts."""
        from jarvis.integrations.auth import get_valid_credentials

        statuses = []
        email_cfg = self._cfg.get("email", {})

        for account in self._accounts:
            provider = account.get("provider", "").lower()
            account_id = account.get("account_id", "")

            if provider == "google" and email_cfg.get("gmail_enabled", True):
                creds = get_valid_credentials("google", account_id, self._cfg)
                if creds:
                    statuses.append(_check_gmail(account_id, creds))
                else:
                    statuses.append({
                        "provider": "gmail",
                        "account_id": account_id,
                        "status": "unauthenticated",
                    })

            elif provider in ("microsoft", "outlook") and email_cfg.get("outlook_enabled", True):
                token = get_valid_credentials("microsoft", account_id, self._cfg)
                if token:
                    statuses.append(_check_outlook_mail(account_id, token))
                else:
                    statuses.append({
                        "provider": "outlook_mail",
                        "account_id": account_id,
                        "status": "unauthenticated",
                    })

        return statuses
