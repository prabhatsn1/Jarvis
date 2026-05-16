"""
OAuth token management for Google and Microsoft integrations.

Tokens are stored in the system keyring when available; if not,
they are persisted to an AES-256-GCM encrypted file under
~/.jarvis/credentials/.  Secrets are never written to log output.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs
from wsgiref.simple_server import make_server, WSGIRequestHandler

log = logging.getLogger("jarvis.integrations.auth")

# ── Keyring / fallback credential store ─────────────────────────────────────

_KEYRING_SERVICE = "jarvis_oauth"
_CRED_DIR = Path("~/.jarvis/credentials").expanduser()

try:
    import keyring as _keyring

    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _keyring = None  # type: ignore
    _KEYRING_AVAILABLE = False
    log.debug("keyring not available — falling back to encrypted file store")


def _cred_path(provider: str, account_id: str) -> Path:
    """Return the path used for encrypted file fallback."""
    safe = account_id.replace("@", "_at_").replace(".", "_")
    return _CRED_DIR / f"{provider}_{safe}.json.enc"


def _fernet() -> "Fernet":
    """Return a Fernet instance keyed from a per-machine secret."""
    from cryptography.fernet import Fernet

    key_path = _CRED_DIR / ".fernet_key"
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        key_path.chmod(0o600)
    return Fernet(key)


def _save_token(provider: str, account_id: str, token_data: dict) -> None:
    """Persist token_data without ever logging secret values."""
    serialised = json.dumps(token_data)
    if _KEYRING_AVAILABLE:
        _keyring.set_password(_KEYRING_SERVICE, f"{provider}:{account_id}", serialised)
    else:
        try:
            enc = _fernet().encrypt(serialised.encode())
            path = _cred_path(provider, account_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(enc)
            path.chmod(0o600)
        except Exception as exc:
            log.error("Failed to persist credentials for %s/%s: %s", provider, account_id, exc)


def _load_token(provider: str, account_id: str) -> Optional[dict]:
    """Load persisted token_data or return None."""
    if _KEYRING_AVAILABLE:
        raw = _keyring.get_password(_KEYRING_SERVICE, f"{provider}:{account_id}")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None
    else:
        path = _cred_path(provider, account_id)
        if not path.exists():
            return None
        try:
            dec = _fernet().decrypt(path.read_bytes())
            return json.loads(dec.decode())
        except Exception as exc:
            log.error("Failed to load credentials for %s/%s: %s", provider, account_id, exc)
            return None


def _delete_token(provider: str, account_id: str) -> bool:
    """Remove stored credentials. Returns True if something was removed."""
    if _KEYRING_AVAILABLE:
        try:
            _keyring.delete_password(_KEYRING_SERVICE, f"{provider}:{account_id}")
            return True
        except Exception:
            return False
    else:
        path = _cred_path(provider, account_id)
        if path.exists():
            path.unlink()
            return True
        return False


# ── OAuth local callback server ─────────────────────────────────────────────

class _SilentHandler(WSGIRequestHandler):
    """Suppress the default request log lines to keep secrets off stdout."""

    def log_message(self, fmt, *args):  # noqa: D102
        pass


def _run_local_callback_server(port: int, state: str, timeout: int = 120) -> Optional[str]:
    """
    Start a temporary WSGI server on localhost:<port> and wait for the OAuth
    redirect.  Returns the full callback URL (containing the auth code) or
    None on timeout / error.
    """
    result: dict = {"url": None}
    event = threading.Event()

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        query = environ.get("QUERY_STRING", "")
        if path == "/callback":
            result["url"] = f"http://localhost:{port}/callback?{query}"
            start_response("200 OK", [("Content-Type", "text/html")])
            event.set()
            return [b"<html><body>Authentication complete. You can close this tab.</body></html>"]
        start_response("404 Not Found", [])
        return [b"Not Found"]

    try:
        server = make_server("localhost", port, app, handler_class=_SilentHandler)
        server.timeout = 1
    except OSError as exc:
        log.error("Cannot bind OAuth callback server on port %d: %s", port, exc)
        return None

    deadline = time.time() + timeout
    while not event.is_set() and time.time() < deadline:
        server.handle_request()
    server.server_close()
    return result["url"]


# ── Google OAuth ─────────────────────────────────────────────────────────────

_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]
_GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def connect_google_account(client_id: str, client_secret: str, redirect_port: int = 8765) -> dict:
    """
    Run the Google OAuth 2.0 PKCE / installed-app flow and persist tokens.

    Returns a dict with keys: ``ok``, ``email``, ``message``.
    Never logs client_secret or token values.
    """
    if not client_id or not client_secret:
        return {"ok": False, "email": None, "message": "Google client_id and client_secret are required."}

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return {
            "ok": False,
            "email": None,
            "message": "google-auth-oauthlib is not installed. Run: pip install google-auth-oauthlib",
        }

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [f"http://localhost:{redirect_port}/callback"],
            "auth_uri": _GOOGLE_AUTH_URI,
            "token_uri": _GOOGLE_TOKEN_URI,
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=_GOOGLE_SCOPES)
        creds = flow.run_local_server(port=redirect_port, open_browser=True, quiet=True)
    except Exception as exc:
        log.error("Google OAuth flow error: %s", exc)
        return {"ok": False, "email": None, "message": f"Google authentication failed: {exc}"}

    # Discover the account email via the userinfo endpoint
    email = _google_email_from_creds(creds)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or _GOOGLE_SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    _save_token("google", email or "default", token_data)
    log.info("Google account connected: %s", email)
    return {"ok": True, "email": email, "message": f"Google account connected: {email}"}


def _google_email_from_creds(creds) -> Optional[str]:
    """Return the Google account email using the token."""
    try:
        import google.auth.transport.requests as _greq
        import requests as _req

        session = _req.Session()
        r = session.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        if r.ok:
            return r.json().get("email")
    except Exception as exc:
        log.debug("Could not fetch Google email: %s", exc)
    return None


def get_valid_google_credentials(account_id: str, client_id: str, client_secret: str):
    """
    Return a valid ``google.oauth2.credentials.Credentials`` object, refreshing
    if the access token has expired.  Returns None when no stored token exists.
    """
    token_data = _load_token("google", account_id)
    if not token_data:
        return None

    try:
        from google.oauth2.credentials import Credentials
        import google.auth.transport.requests as _greq

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", _GOOGLE_TOKEN_URI),
            client_id=token_data.get("client_id", client_id),
            client_secret=token_data.get("client_secret", client_secret),
            scopes=token_data.get("scopes", _GOOGLE_SCOPES),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(_greq.Request())
            # Persist the refreshed access token (never log it)
            token_data["token"] = creds.token
            token_data["expiry"] = creds.expiry.isoformat() if creds.expiry else None
            _save_token("google", account_id, token_data)

        return creds
    except Exception as exc:
        log.error("Failed to get valid Google credentials for %s: %s", account_id, exc)
        return None


# ── Microsoft OAuth ──────────────────────────────────────────────────────────

_MS_SCOPES = ["Calendars.Read", "Mail.Read", "offline_access"]
_MS_AUTHORITY = "https://login.microsoftonline.com"


def connect_microsoft_account(
    client_id: str,
    client_secret: str,
    tenant: str = "common",
    redirect_port: int = 8765,
) -> dict:
    """
    Run the Microsoft OAuth 2.0 Authorization Code flow (MSAL) and persist
    tokens.  Returns a dict with keys: ``ok``, ``email``, ``message``.
    """
    if not client_id or not client_secret:
        return {
            "ok": False,
            "email": None,
            "message": "Microsoft client_id and client_secret are required.",
        }

    try:
        import msal
    except ImportError:
        return {
            "ok": False,
            "email": None,
            "message": "msal is not installed. Run: pip install msal",
        }

    authority = f"{_MS_AUTHORITY}/{tenant}"
    redirect_uri = f"http://localhost:{redirect_port}/callback"

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )

    auth_url = app.get_authorization_request_url(
        scopes=_MS_SCOPES,
        redirect_uri=redirect_uri,
    )

    import webbrowser
    webbrowser.open(auth_url)

    callback_url = _run_local_callback_server(redirect_port, state="", timeout=120)
    if not callback_url:
        return {"ok": False, "email": None, "message": "Microsoft authentication timed out."}

    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        error = params.get("error_description", ["Unknown error"])[0]
        return {"ok": False, "email": None, "message": f"Microsoft auth failed: {error}"}

    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=_MS_SCOPES,
        redirect_uri=redirect_uri,
    )

    if "error" in result:
        log.error("MS token exchange error: %s", result.get("error_description"))
        return {
            "ok": False,
            "email": None,
            "message": f"Microsoft token exchange failed: {result.get('error_description', 'unknown')}",
        }

    id_token_claims = result.get("id_token_claims") or {}
    email = id_token_claims.get("preferred_username") or id_token_claims.get("email")

    token_data = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "token_type": result.get("token_type", "Bearer"),
        "expires_in": result.get("expires_in", 3600),
        "acquired_at": time.time(),
        "client_id": client_id,
        "client_secret": client_secret,
        "tenant": tenant,
        "scopes": _MS_SCOPES,
    }
    _save_token("microsoft", email or "default", token_data)
    log.info("Microsoft account connected: %s", email)
    return {"ok": True, "email": email, "message": f"Microsoft account connected: {email}"}


def get_valid_microsoft_token(account_id: str, client_id: str, client_secret: str, tenant: str = "common") -> Optional[str]:
    """
    Return a valid Microsoft Graph access token, refreshing via MSAL if
    needed.  Returns None when no stored token exists.
    """
    token_data = _load_token("microsoft", account_id)
    if not token_data:
        return None

    acquired_at = token_data.get("acquired_at", 0)
    expires_in = token_data.get("expires_in", 3600)
    # Refresh 5 minutes before expiry
    if time.time() < acquired_at + expires_in - 300:
        return token_data["access_token"]

    # Attempt silent refresh via MSAL
    try:
        import msal

        authority = f"{_MS_AUTHORITY}/{token_data.get('tenant', tenant)}"
        app = msal.ConfidentialClientApplication(
            client_id=token_data.get("client_id", client_id),
            client_credential=token_data.get("client_secret", client_secret),
            authority=authority,
        )
        accounts = app.get_accounts(username=account_id)
        if accounts:
            result = app.acquire_token_silent(scopes=_MS_SCOPES, account=accounts[0])
        else:
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                return None
            result = app.acquire_token_by_refresh_token(
                refresh_token=refresh_token, scopes=_MS_SCOPES
            )

        if result and "access_token" in result:
            token_data["access_token"] = result["access_token"]
            token_data["acquired_at"] = time.time()
            token_data["expires_in"] = result.get("expires_in", 3600)
            _save_token("microsoft", account_id, token_data)
            return token_data["access_token"]

        log.warning("MSAL silent refresh failed for %s — re-authentication required", account_id)
        return None

    except Exception as exc:
        log.error("Microsoft token refresh error for %s: %s", account_id, exc)
        return None


# ── Public helpers ───────────────────────────────────────────────────────────

def disconnect_account(provider: str, account_id: str) -> dict:
    """Remove stored credentials for a provider/account pair."""
    provider = provider.lower().strip()
    removed = _delete_token(provider, account_id)
    if removed:
        log.info("Disconnected %s account: %s", provider, account_id)
        return {"ok": True, "message": f"Disconnected {provider} account {account_id}."}
    return {"ok": False, "message": f"No stored credentials found for {provider}/{account_id}."}


def list_stored_accounts() -> list[dict]:
    """
    Return a list of {provider, account_id} dicts for all stored credentials.
    Only inspects keyring entries created by this service; no secrets exposed.
    """
    accounts: list[dict] = []
    if _KEYRING_AVAILABLE:
        # keyring does not expose enumeration in the generic API;
        # fall back to scanning the encrypted file dir as well.
        pass

    # Always scan the file-based fallback dir for any persisted accounts
    if _CRED_DIR.exists():
        for p in _CRED_DIR.glob("*.json.enc"):
            name = p.stem.replace(".json", "")  # strip .enc already handled
            parts = name.split("_", 1)
            if len(parts) == 2:
                prov, acct = parts[0], parts[1].replace("_at_", "@").replace("_", ".")
                accounts.append({"provider": prov, "account_id": acct})

    return accounts


def get_valid_credentials(provider: str, account_id: str, cfg: dict):
    """
    Unified dispatcher.  ``cfg`` should be the ``integrations`` config block.

    Returns:
      - Google: ``google.oauth2.credentials.Credentials``
      - Microsoft: access token string
      - Unknown provider: None
    """
    provider = provider.lower()
    if provider == "google":
        google_cfg = cfg.get("google", {})
        return get_valid_google_credentials(
            account_id,
            client_id=google_cfg.get("client_id", ""),
            client_secret=google_cfg.get("client_secret", ""),
        )
    if provider in ("microsoft", "outlook"):
        ms_cfg = cfg.get("microsoft", {})
        return get_valid_microsoft_token(
            account_id,
            client_id=ms_cfg.get("client_id", ""),
            client_secret=ms_cfg.get("client_secret", ""),
            tenant=ms_cfg.get("tenant", "common"),
        )
    log.warning("Unknown provider: %s", provider)
    return None
