"""Smart home voice actions — lights, plugs, thermostats.

core.py calls ``set_smarthome_context()`` at startup to inject the config
and instantiate the SmartHomeClient.  All public functions are callable from
the ActionExecutor and accept only slot kwargs.
"""

from __future__ import annotations

import logging

log = logging.getLogger("jarvis.actions.smarthome")

# ── Runtime context (injected by core.py) ────────────────────────────────────

_smarthome_cfg: dict = {}
_client = None  # SmartHomeClient instance


def set_smarthome_context(cfg: dict) -> None:
    """Instantiate the SmartHomeClient and cache it for action calls."""
    global _smarthome_cfg, _client
    _smarthome_cfg = cfg or {}
    if not _smarthome_cfg.get("enabled", False):
        _client = None
        return
    try:
        from jarvis.integrations.smarthome import SmartHomeClient
        _client = SmartHomeClient(_smarthome_cfg)
        log.info("SmartHomeClient initialised (backend=%s)", _smarthome_cfg.get("backend", "home_assistant"))
    except Exception as exc:
        log.warning("Could not initialise SmartHomeClient: %s", exc)
        _client = None


def _not_configured() -> str:
    return (
        "Smart home is not configured, Boss. "
        "Set smart_home.enabled: true in config.yaml and provide your "
        "Home Assistant URL and token (or Hue Bridge credentials)."
    )


# ── Light actions ─────────────────────────────────────────────────────────────

def turn_on_light(entity: str, brightness: int | None = None, color: str | None = None) -> str:
    """Turn on a light, optionally setting brightness and/or colour."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.turn_on_light(entity, brightness=brightness, color=color)
    return msg


def turn_off_light(entity: str) -> str:
    """Turn off a light."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.turn_off_light(entity)
    return msg


def set_brightness(entity: str, brightness: int) -> str:
    """Set a light's brightness (0–100)."""
    if _client is None:
        return _not_configured()
    try:
        brightness = max(0, min(100, int(brightness)))
    except (TypeError, ValueError):
        return "Please provide a brightness value between 0 and 100, Boss."
    ok, msg = _client.set_brightness(entity, brightness)
    return msg


def set_color(entity: str, color: str) -> str:
    """Change a light's colour."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.set_color(entity, color)
    return msg


# ── Plug / switch actions ─────────────────────────────────────────────────────

def turn_on_plug(entity: str) -> str:
    """Turn on a smart plug or switch."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.turn_on_plug(entity)
    return msg


def turn_off_plug(entity: str) -> str:
    """Turn off a smart plug or switch."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.turn_off_plug(entity)
    return msg


# ── Thermostat actions ────────────────────────────────────────────────────────

def set_temperature(temperature: str, entity: str = "thermostat") -> str:
    """Set a thermostat to the given temperature."""
    if _client is None:
        return _not_configured()
    try:
        temp_val = float(str(temperature).replace("°", "").replace("degrees", "").strip())
    except ValueError:
        return f"I didn't understand the temperature '{temperature}', Boss."
    ok, msg = _client.set_temperature(entity, temp_val)
    return msg


def get_temperature(entity: str = "thermostat") -> str:
    """Read the current and target temperature from a thermostat."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.get_temperature(entity)
    return msg


# ── State / discovery actions ─────────────────────────────────────────────────

def get_device_state(entity: str) -> str:
    """Report the current state of any smart home device."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.get_state(entity)
    return msg


def list_devices(device_type: str | None = None) -> str:
    """List known smart home devices, optionally filtered by type."""
    if _client is None:
        return _not_configured()
    ok, msg = _client.list_devices(device_type=device_type)
    return msg
