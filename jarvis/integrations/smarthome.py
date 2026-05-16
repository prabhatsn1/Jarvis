"""Smart home client — Home Assistant REST API and Philips Hue direct API.

Supports:
  - Home Assistant  (backend="home_assistant")  — controls Hue lights, smart
    plugs, and thermostats through HA entity IDs.
  - Philips Hue direct  (backend="hue_direct")  — talks to the Hue Bridge
    without Home Assistant.

Config section (config.yaml):
    smart_home:
      enabled: true
      backend: "home_assistant"   # or "hue_direct"
      home_assistant:
        url: "http://homeassistant.local:8123"
        token: ""                 # long-lived access token
        timeout_sec: 10
      hue_direct:
        bridge_ip: ""             # IP of the Hue Bridge
        username: ""              # registered app key
        timeout_sec: 5
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("jarvis.integrations.smarthome")

# ── Named colour → RGB mapping ──────────────────────────────────────────────

_COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "warm white": (255, 197, 143),
    "cool white": (200, 220, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 105, 180),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "teal": (0, 128, 128),
    "lime": (0, 255, 0),
    "indigo": (75, 0, 130),
    "violet": (238, 130, 238),
}


def _parse_color(color: str) -> tuple[int, int, int] | None:
    """Return (r, g, b) for a color name or '#RRGGBB' hex string, or None."""
    color = color.strip().lower()
    if color in _COLOR_MAP:
        return _COLOR_MAP[color]
    if color.startswith("#") and len(color) in (4, 7):
        try:
            if len(color) == 4:
                r = int(color[1] * 2, 16)
                g = int(color[2] * 2, 16)
                b = int(color[3] * 2, 16)
            else:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
            return (r, g, b)
        except ValueError:
            pass
    return None


def _rgb_to_xy(r: int, g: int, b: int) -> tuple[float, float]:
    """Convert sRGB (0-255 each) to CIE 1931 xy for Philips Hue."""
    r_lin = ((r / 255) ** 2.2)
    g_lin = ((g / 255) ** 2.2)
    b_lin = ((b / 255) ** 2.2)
    X = r_lin * 0.664511 + g_lin * 0.154324 + b_lin * 0.162028
    Y = r_lin * 0.283881 + g_lin * 0.668433 + b_lin * 0.047685
    Z = r_lin * 0.000088 + g_lin * 0.072310 + b_lin * 0.986039
    total = X + Y + Z
    if total == 0:
        return (0.0, 0.0)
    return (round(X / total, 4), round(Y / total, 4))


# ── Home Assistant client ────────────────────────────────────────────────────

class HomeAssistantClient:
    """Thin wrapper around the Home Assistant REST API."""

    def __init__(self, cfg: dict) -> None:
        self._url = cfg.get("url", "http://homeassistant.local:8123").rstrip("/")
        self._token = cfg.get("token", "")
        self._timeout = int(cfg.get("timeout_sec", 10))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Any:
        import requests
        resp = requests.get(
            f"{self._url}{path}",
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict) -> Any:
        import requests
        resp = requests.post(
            f"{self._url}{path}",
            headers=self._headers(),
            json=data,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _entity_id(self, entity: str, domain: str | None = None) -> str:
        """Normalise a human name to an entity_id if it isn't one already.

        e.g. "bedroom light" → "light.bedroom_light"
             "light.bedroom" → "light.bedroom"
        """
        entity = entity.strip()
        if "." in entity:
            return entity  # already a valid entity_id
        slug = entity.lower().replace(" ", "_")
        if domain:
            return f"{domain}.{slug}"
        # Unknown domain — return as-is so HA can reject it with a clear error
        return slug

    def get_state(self, entity: str) -> dict:
        """Return the full state dict for an entity."""
        eid = self._entity_id(entity)
        return self._get(f"/api/states/{eid}")

    def list_states(self, domain: str | None = None) -> list[dict]:
        """Return all entity states, optionally filtered by domain."""
        states = self._get("/api/states")
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        return states

    # ── Light control ─────────────────────────────────────────────────────────

    def light_turn_on(
        self,
        entity: str,
        brightness_pct: int | None = None,
        color: str | None = None,
    ) -> None:
        eid = self._entity_id(entity, domain="light")
        data: dict[str, Any] = {"entity_id": eid}
        if brightness_pct is not None:
            data["brightness_pct"] = max(0, min(100, int(brightness_pct)))
        if color:
            rgb = _parse_color(color)
            if rgb:
                data["rgb_color"] = list(rgb)
            else:
                data["color_name"] = color.lower()
        self._post("/api/services/light/turn_on", data)

    def light_turn_off(self, entity: str) -> None:
        eid = self._entity_id(entity, domain="light")
        self._post("/api/services/light/turn_off", {"entity_id": eid})

    def light_set_brightness(self, entity: str, brightness_pct: int) -> None:
        eid = self._entity_id(entity, domain="light")
        self._post(
            "/api/services/light/turn_on",
            {"entity_id": eid, "brightness_pct": max(0, min(100, int(brightness_pct)))},
        )

    def light_set_color(self, entity: str, color: str) -> None:
        eid = self._entity_id(entity, domain="light")
        data: dict[str, Any] = {"entity_id": eid}
        rgb = _parse_color(color)
        if rgb:
            data["rgb_color"] = list(rgb)
        else:
            data["color_name"] = color.lower()
        self._post("/api/services/light/turn_on", data)

    # ── Switch / plug control ─────────────────────────────────────────────────

    def switch_turn_on(self, entity: str) -> None:
        eid = self._entity_id(entity, domain="switch")
        self._post("/api/services/switch/turn_on", {"entity_id": eid})

    def switch_turn_off(self, entity: str) -> None:
        eid = self._entity_id(entity, domain="switch")
        self._post("/api/services/switch/turn_off", {"entity_id": eid})

    # ── Climate / thermostat ──────────────────────────────────────────────────

    def climate_set_temperature(self, entity: str, temperature: float) -> None:
        eid = self._entity_id(entity, domain="climate")
        self._post(
            "/api/services/climate/set_temperature",
            {"entity_id": eid, "temperature": float(temperature)},
        )

    def climate_get_temperature(self, entity: str) -> dict:
        eid = self._entity_id(entity, domain="climate")
        return self.get_state(eid)


# ── Philips Hue direct client ────────────────────────────────────────────────

class HueDirectClient:
    """Philips Hue Bridge v1 (CLIP) API client."""

    def __init__(self, cfg: dict) -> None:
        self._ip = cfg.get("bridge_ip", "").strip()
        self._username = cfg.get("username", "").strip()
        self._timeout = int(cfg.get("timeout_sec", 5))

    def _base(self) -> str:
        return f"http://{self._ip}/api/{self._username}"

    def _get(self, path: str) -> Any:
        import requests
        resp = requests.get(
            f"{self._base()}{path}",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, data: dict) -> Any:
        import requests
        resp = requests.put(
            f"{self._base()}{path}",
            json=data,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_light_id(self, name: str) -> str | None:
        """Return the numeric light id whose name contains *name* (case-insensitive)."""
        lights = self._get("/lights")
        if isinstance(lights, list):
            # Error response from bridge
            return None
        needle = name.strip().lower()
        for lid, info in lights.items():
            if needle in info.get("name", "").lower():
                return lid
        return None

    def list_lights(self) -> dict:
        return self._get("/lights")

    # ── Light control ─────────────────────────────────────────────────────────

    def light_turn_on(
        self,
        entity: str,
        brightness_pct: int | None = None,
        color: str | None = None,
    ) -> None:
        lid = self._find_light_id(entity)
        if lid is None:
            raise ValueError(f"Hue light '{entity}' not found on bridge.")
        state: dict[str, Any] = {"on": True}
        if brightness_pct is not None:
            state["bri"] = max(1, min(254, int(brightness_pct / 100 * 254)))
        if color:
            rgb = _parse_color(color)
            if rgb:
                xy = _rgb_to_xy(*rgb)
                state["xy"] = list(xy)
        self._put(f"/lights/{lid}/state", state)

    def light_turn_off(self, entity: str) -> None:
        lid = self._find_light_id(entity)
        if lid is None:
            raise ValueError(f"Hue light '{entity}' not found on bridge.")
        self._put(f"/lights/{lid}/state", {"on": False})

    def light_set_brightness(self, entity: str, brightness_pct: int) -> None:
        self.light_turn_on(entity, brightness_pct=brightness_pct)

    def light_set_color(self, entity: str, color: str) -> None:
        self.light_turn_on(entity, color=color)

    def get_state(self, entity: str) -> dict:
        lid = self._find_light_id(entity)
        if lid is None:
            raise ValueError(f"Hue light '{entity}' not found on bridge.")
        return self._get(f"/lights/{lid}")


# ── Unified SmartHomeClient ──────────────────────────────────────────────────

class SmartHomeClient:
    """Facade over HomeAssistantClient or HueDirectClient."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._backend = cfg.get("backend", "home_assistant")

        if self._backend == "home_assistant":
            self._ha = HomeAssistantClient(cfg.get("home_assistant", {}))
            self._hue: HueDirectClient | None = None
        elif self._backend == "hue_direct":
            self._ha = None  # type: ignore[assignment]
            self._hue = HueDirectClient(cfg.get("hue_direct", {}))
        else:
            raise ValueError(f"Unknown smart_home backend: '{self._backend}'")

    # ── Lights ───────────────────────────────────────────────────────────────

    def turn_on_light(
        self,
        entity: str,
        brightness: int | None = None,
        color: str | None = None,
    ) -> tuple[bool, str]:
        try:
            if self._backend == "home_assistant":
                self._ha.light_turn_on(entity, brightness_pct=brightness, color=color)
            else:
                self._hue.light_turn_on(entity, brightness_pct=brightness, color=color)
            parts = [f"Turned on {entity}"]
            if brightness is not None:
                parts.append(f"brightness {brightness}%")
            if color:
                parts.append(f"color {color}")
            return True, ", ".join(parts) + "."
        except Exception as exc:
            log.error("turn_on_light failed: %s", exc)
            return False, f"Could not turn on {entity}: {exc}"

    def turn_off_light(self, entity: str) -> tuple[bool, str]:
        try:
            if self._backend == "home_assistant":
                self._ha.light_turn_off(entity)
            else:
                self._hue.light_turn_off(entity)
            return True, f"Turned off {entity}."
        except Exception as exc:
            log.error("turn_off_light failed: %s", exc)
            return False, f"Could not turn off {entity}: {exc}"

    def set_brightness(self, entity: str, brightness: int) -> tuple[bool, str]:
        try:
            if self._backend == "home_assistant":
                self._ha.light_set_brightness(entity, brightness)
            else:
                self._hue.light_set_brightness(entity, brightness)
            return True, f"Set {entity} brightness to {brightness}%."
        except Exception as exc:
            log.error("set_brightness failed: %s", exc)
            return False, f"Could not set brightness for {entity}: {exc}"

    def set_color(self, entity: str, color: str) -> tuple[bool, str]:
        try:
            if self._backend == "home_assistant":
                self._ha.light_set_color(entity, color)
            else:
                self._hue.light_set_color(entity, color)
            return True, f"Changed {entity} to {color}."
        except Exception as exc:
            log.error("set_color failed: %s", exc)
            return False, f"Could not set color for {entity}: {exc}"

    # ── Switches / plugs ─────────────────────────────────────────────────────

    def turn_on_plug(self, entity: str) -> tuple[bool, str]:
        if self._backend != "home_assistant":
            return False, "Smart plug control requires the Home Assistant backend."
        try:
            self._ha.switch_turn_on(entity)
            return True, f"Turned on {entity}."
        except Exception as exc:
            log.error("turn_on_plug failed: %s", exc)
            return False, f"Could not turn on {entity}: {exc}"

    def turn_off_plug(self, entity: str) -> tuple[bool, str]:
        if self._backend != "home_assistant":
            return False, "Smart plug control requires the Home Assistant backend."
        try:
            self._ha.switch_turn_off(entity)
            return True, f"Turned off {entity}."
        except Exception as exc:
            log.error("turn_off_plug failed: %s", exc)
            return False, f"Could not turn off {entity}: {exc}"

    # ── Thermostat ───────────────────────────────────────────────────────────

    def set_temperature(self, entity: str, temperature: float) -> tuple[bool, str]:
        if self._backend != "home_assistant":
            return False, "Thermostat control requires the Home Assistant backend."
        try:
            self._ha.climate_set_temperature(entity, temperature)
            return True, f"Set {entity} temperature to {temperature}°."
        except Exception as exc:
            log.error("set_temperature failed: %s", exc)
            return False, f"Could not set temperature for {entity}: {exc}"

    def get_temperature(self, entity: str) -> tuple[bool, str]:
        if self._backend != "home_assistant":
            return False, "Thermostat queries require the Home Assistant backend."
        try:
            state = self._ha.climate_get_temperature(entity)
            attrs = state.get("attributes", {})
            current = attrs.get("current_temperature", "unknown")
            target = attrs.get("temperature", "unknown")
            unit = attrs.get("unit_of_measurement", "°")
            return True, (
                f"{entity}: current {current}{unit}, target {target}{unit}."
            )
        except Exception as exc:
            log.error("get_temperature failed: %s", exc)
            return False, f"Could not read temperature for {entity}: {exc}"

    # ── State / discovery ────────────────────────────────────────────────────

    def get_state(self, entity: str) -> tuple[bool, str]:
        try:
            if self._backend == "home_assistant":
                state = self._ha.get_state(entity)
                attrs = state.get("attributes", {})
                s = state.get("state", "unknown")
                detail_parts = [f"{k}: {v}" for k, v in attrs.items()
                                 if k in ("brightness", "color_temp", "rgb_color",
                                          "temperature", "current_temperature",
                                          "friendly_name")]
                detail = ", ".join(detail_parts)
                name = attrs.get("friendly_name", entity)
                return True, f"{name} is {s}. {detail}".strip()
            else:
                info = self._hue.get_state(entity)
                state_dict = info.get("state", {})
                on = state_dict.get("on", False)
                bri = state_dict.get("bri", 0)
                bri_pct = round(bri / 254 * 100)
                status = "on" if on else "off"
                return True, f"{entity} is {status}, brightness {bri_pct}%."
        except Exception as exc:
            log.error("get_state failed: %s", exc)
            return False, f"Could not read state for {entity}: {exc}"

    def list_devices(self, device_type: str | None = None) -> tuple[bool, str]:
        """Return a formatted list of known smart home devices."""
        try:
            if self._backend == "home_assistant":
                domains = []
                if device_type in (None, "light"):
                    domains.append("light")
                if device_type in (None, "switch", "plug"):
                    domains.append("switch")
                if device_type in (None, "thermostat", "climate"):
                    domains.append("climate")

                lines: list[str] = []
                for domain in domains:
                    states = self._ha.list_states(domain=domain)
                    for s in states:
                        eid = s.get("entity_id", "")
                        name = s.get("attributes", {}).get("friendly_name", eid)
                        status = s.get("state", "unknown")
                        lines.append(f"  {name} ({eid}): {status}")

                if not lines:
                    return True, "No smart home devices found."
                return True, "Smart home devices:\n" + "\n".join(lines)

            else:
                lights = self._hue.list_lights()
                if isinstance(lights, list):
                    return False, "Bridge returned an error listing lights."
                lines = []
                for lid, info in lights.items():
                    name = info.get("name", f"light {lid}")
                    on = info.get("state", {}).get("on", False)
                    lines.append(f"  {name} (id={lid}): {'on' if on else 'off'}")
                if not lines:
                    return True, "No Hue lights found on bridge."
                return True, "Philips Hue lights:\n" + "\n".join(lines)

        except Exception as exc:
            log.error("list_devices failed: %s", exc)
            return False, f"Could not list devices: {exc}"
