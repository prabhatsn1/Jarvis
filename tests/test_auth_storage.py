"""
Tests for auth.py token storage — save/load via keyring abstraction and
file-based fallback; disconnect removes credentials.
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _token_data():
    return {
        "token": "access-abc",
        "refresh_token": "refresh-xyz",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csec",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
        "expiry": None,
    }


# ── Keyring path ──────────────────────────────────────────────────────────────


class TestKeyringTokenStorage:
    """
    When keyring IS available, _save_token / _load_token / _delete_token should
    delegate to keyring.set_password / get_password / delete_password.
    """

    def _mock_keyring(self):
        kr = MagicMock()
        kr.get_password.return_value = None
        return kr

    def test_save_and_load_roundtrip(self):
        kr = self._mock_keyring()

        with (
            patch("jarvis.integrations.auth._KEYRING_AVAILABLE", True),
            patch("jarvis.integrations.auth._keyring", kr),
        ):
            from jarvis.integrations.auth import _save_token, _load_token

            data = _token_data()
            _save_token("google", "user@gmail.com", data)

            # Simulate what keyring would return
            saved_call = kr.set_password.call_args
            service, key, value = saved_call[0]
            kr.get_password.return_value = value

            loaded = _load_token("google", "user@gmail.com")

        assert loaded is not None
        assert loaded["refresh_token"] == "refresh-xyz"
        # Secret should never appear in the call to set_password's *name* args
        assert "csec" not in service
        assert "csec" not in key

    def test_load_returns_none_when_no_entry(self):
        kr = self._mock_keyring()
        kr.get_password.return_value = None

        with (
            patch("jarvis.integrations.auth._KEYRING_AVAILABLE", True),
            patch("jarvis.integrations.auth._keyring", kr),
        ):
            from jarvis.integrations.auth import _load_token
            result = _load_token("google", "nobody@gmail.com")

        assert result is None

    def test_delete_calls_keyring_delete(self):
        kr = self._mock_keyring()

        with (
            patch("jarvis.integrations.auth._KEYRING_AVAILABLE", True),
            patch("jarvis.integrations.auth._keyring", kr),
        ):
            from jarvis.integrations.auth import _delete_token
            removed = _delete_token("google", "user@gmail.com")

        kr.delete_password.assert_called_once()
        assert removed is True


# ── File-based fallback ───────────────────────────────────────────────────────


class TestFileTokenStorage:
    """
    When keyring is NOT available, tokens are stored as AES-256-GCM
    encrypted files.  We patch _KEYRING_AVAILABLE and _CRED_DIR to use a
    temp directory so no real filesystem state is modified.
    """

    def test_save_load_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cred_dir = Path(tmpdir) / "credentials"

            with (
                patch("jarvis.integrations.auth._KEYRING_AVAILABLE", False),
                patch("jarvis.integrations.auth._CRED_DIR", cred_dir),
            ):
                from jarvis.integrations import auth as _auth

                # Need to reload so _cred_path sees the patched _CRED_DIR
                import importlib
                importlib.reload(_auth)

                with (
                    patch.object(_auth, "_KEYRING_AVAILABLE", False),
                    patch.object(_auth, "_CRED_DIR", cred_dir),
                ):
                    data = _token_data()
                    _auth._save_token("google", "user@example.com", data)

                    # File must exist
                    files = list(cred_dir.glob("*.json.enc"))
                    assert len(files) == 1

                    # Loaded data matches (no raw secret in filename)
                    loaded = _auth._load_token("google", "user@example.com")
                    assert loaded is not None
                    assert loaded["refresh_token"] == "refresh-xyz"

                    # Filename must not contain the secret value
                    fname = files[0].name
                    assert "csec" not in fname
                    assert "access-abc" not in fname

                    # Delete removes the file
                    removed = _auth._delete_token("google", "user@example.com")
                    assert removed is True
                    assert not files[0].exists()

    def test_load_returns_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cred_dir = Path(tmpdir) / "credentials"
            from jarvis.integrations import auth as _auth
            import importlib
            importlib.reload(_auth)

            with (
                patch.object(_auth, "_KEYRING_AVAILABLE", False),
                patch.object(_auth, "_CRED_DIR", cred_dir),
            ):
                result = _auth._load_token("google", "ghost@example.com")
            assert result is None


# ── disconnect_account public helper ─────────────────────────────────────────


class TestDisconnectAccount:
    def test_returns_ok_when_token_exists(self):
        kr = MagicMock()

        with (
            patch("jarvis.integrations.auth._KEYRING_AVAILABLE", True),
            patch("jarvis.integrations.auth._keyring", kr),
        ):
            from jarvis.integrations.auth import _save_token, disconnect_account

            _save_token("google", "a@g.com", _token_data())
            result = disconnect_account("google", "a@g.com")

        assert result["ok"] is True
        assert "google" in result["message"].lower()

    def test_returns_not_found_when_no_token(self):
        kr = MagicMock()
        kr.delete_password.side_effect = Exception("not found")

        with (
            patch("jarvis.integrations.auth._KEYRING_AVAILABLE", True),
            patch("jarvis.integrations.auth._keyring", kr),
        ):
            from jarvis.integrations.auth import disconnect_account
            result = disconnect_account("google", "nobody@g.com")

        assert result["ok"] is False


# ── get_valid_credentials dispatcher ─────────────────────────────────────────


class TestGetValidCredentials:
    def test_unknown_provider_returns_none(self):
        from jarvis.integrations.auth import get_valid_credentials
        result = get_valid_credentials("twitter", "user", {})
        assert result is None

    def test_google_delegates_to_google_helper(self):
        from jarvis.integrations.auth import get_valid_credentials

        with patch("jarvis.integrations.auth.get_valid_google_credentials") as mock_g:
            mock_g.return_value = MagicMock()
            cfg = {"google": {"client_id": "cid", "client_secret": "csec"}}
            result = get_valid_credentials("google", "u@g.com", cfg)

        mock_g.assert_called_once_with("u@g.com", client_id="cid", client_secret="csec")
        assert result is mock_g.return_value

    def test_microsoft_delegates_to_ms_helper(self):
        from jarvis.integrations.auth import get_valid_credentials

        with patch("jarvis.integrations.auth.get_valid_microsoft_token") as mock_m:
            mock_m.return_value = "access-token"
            cfg = {
                "microsoft": {"client_id": "cid", "client_secret": "csec", "tenant": "common"}
            }
            result = get_valid_credentials("microsoft", "u@o.com", cfg)

        mock_m.assert_called_once_with(
            "u@o.com", client_id="cid", client_secret="csec", tenant="common"
        )
        assert result == "access-token"

    def test_outlook_alias_also_maps_to_microsoft(self):
        from jarvis.integrations.auth import get_valid_credentials

        with patch("jarvis.integrations.auth.get_valid_microsoft_token") as mock_m:
            mock_m.return_value = "tok"
            cfg = {"microsoft": {"client_id": "c", "client_secret": "s", "tenant": "common"}}
            result = get_valid_credentials("outlook", "u@o.com", cfg)

        mock_m.assert_called_once()
