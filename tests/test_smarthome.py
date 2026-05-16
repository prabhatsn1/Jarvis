"""Tests for jarvis/actions/smarthome.py and jarvis/integrations/smarthome.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import jarvis.actions.smarthome as sh
from jarvis.integrations.smarthome import (
    SmartHomeClient,
    HomeAssistantClient,
    HueDirectClient,
    _parse_color,
    _rgb_to_xy,
)


# ── Colour helpers ────────────────────────────────────────────────────────────

class TestParseColor:
    def test_named_color(self):
        assert _parse_color("red") == (255, 0, 0)
        assert _parse_color("blue") == (0, 0, 255)
        assert _parse_color("WHITE") == (255, 255, 255)

    def test_hex_6(self):
        assert _parse_color("#ff0000") == (255, 0, 0)
        assert _parse_color("#00FF00") == (0, 255, 0)

    def test_hex_3(self):
        r, g, b = _parse_color("#f00")
        assert r == 255 and g == 0 and b == 0

    def test_unknown_returns_none(self):
        assert _parse_color("chartreuse_xyzzy") is None

    def test_bad_hex_returns_none(self):
        assert _parse_color("#gggggg") is None


class TestRgbToXy:
    def test_red(self):
        x, y = _rgb_to_xy(255, 0, 0)
        # Pure red in CIE 1931 is approximately (0.700, 0.299)
        assert 0.65 < x < 0.75
        assert 0.2 < y < 0.4

    def test_black(self):
        x, y = _rgb_to_xy(0, 0, 0)
        assert x == 0.0 and y == 0.0


# ── Action module: not-configured path ───────────────────────────────────────

class TestNotConfigured:
    def setup_method(self):
        sh.set_smarthome_context({"enabled": False})

    def test_turn_on_light_not_configured(self):
        result = sh.turn_on_light("bedroom light")
        assert "not configured" in result.lower()

    def test_turn_off_light_not_configured(self):
        result = sh.turn_off_light("bedroom light")
        assert "not configured" in result.lower()

    def test_set_brightness_not_configured(self):
        result = sh.set_brightness("kitchen", 50)
        assert "not configured" in result.lower()

    def test_set_color_not_configured(self):
        result = sh.set_color("lamp", "blue")
        assert "not configured" in result.lower()

    def test_turn_on_plug_not_configured(self):
        result = sh.turn_on_plug("coffee maker")
        assert "not configured" in result.lower()

    def test_turn_off_plug_not_configured(self):
        result = sh.turn_off_plug("coffee maker")
        assert "not configured" in result.lower()

    def test_set_temperature_not_configured(self):
        result = sh.set_temperature("22")
        assert "not configured" in result.lower()

    def test_get_temperature_not_configured(self):
        result = sh.get_temperature()
        assert "not configured" in result.lower()

    def test_list_devices_not_configured(self):
        result = sh.list_devices()
        assert "not configured" in result.lower()


# ── Action module: happy paths via mocked SmartHomeClient ────────────────────

def _inject_mock_client():
    mock = MagicMock()
    mock.turn_on_light.return_value = (True, "Turned on bedroom light, brightness 80%.")
    mock.turn_off_light.return_value = (True, "Turned off bedroom light.")
    mock.set_brightness.return_value = (True, "Set bedroom light brightness to 50%.")
    mock.set_color.return_value = (True, "Changed bedroom light to blue.")
    mock.turn_on_plug.return_value = (True, "Turned on coffee maker.")
    mock.turn_off_plug.return_value = (True, "Turned off coffee maker.")
    mock.set_temperature.return_value = (True, "Set thermostat temperature to 22.0°.")
    mock.get_temperature.return_value = (True, "thermostat: current 20°, target 22°.")
    mock.get_state.return_value = (True, "bedroom light is on. brightness: 204")
    mock.list_devices.return_value = (True, "Smart home devices:\n  Bedroom Light (light.bedroom): on")

    sh._client = mock
    return mock


class TestActionsHappyPath:
    def setup_method(self):
        _inject_mock_client()

    def test_turn_on_light(self):
        result = sh.turn_on_light("bedroom light", brightness=80)
        assert "Turned on" in result
        sh._client.turn_on_light.assert_called_once_with(
            "bedroom light", brightness=80, color=None
        )

    def test_turn_off_light(self):
        result = sh.turn_off_light("bedroom light")
        assert "Turned off" in result

    def test_set_brightness_clamps(self):
        sh.set_brightness("kitchen", 150)
        sh._client.set_brightness.assert_called_once_with("kitchen", 100)

    def test_set_brightness_bad_value(self):
        result = sh.set_brightness("kitchen", "not_a_number")
        assert "between 0 and 100" in result.lower() or "brightness" in result.lower()

    def test_set_color(self):
        result = sh.set_color("bedroom light", "blue")
        assert "blue" in result.lower() or "Changed" in result

    def test_turn_on_plug(self):
        result = sh.turn_on_plug("coffee maker")
        assert "Turned on" in result

    def test_turn_off_plug(self):
        result = sh.turn_off_plug("coffee maker")
        assert "Turned off" in result

    def test_set_temperature_numeric(self):
        result = sh.set_temperature("22")
        sh._client.set_temperature.assert_called_once_with("thermostat", 22.0)
        assert "22" in result

    def test_set_temperature_with_degree_symbol(self):
        sh.set_temperature("21°")
        sh._client.set_temperature.assert_called_once_with("thermostat", 21.0)

    def test_set_temperature_bad_value(self):
        result = sh.set_temperature("warm")
        assert "didn't understand" in result.lower()

    def test_get_temperature(self):
        result = sh.get_temperature()
        assert "thermostat" in result.lower() or "current" in result.lower()

    def test_get_device_state(self):
        result = sh.get_device_state("bedroom light")
        assert "bedroom light" in result.lower() or "on" in result.lower()

    def test_list_devices(self):
        result = sh.list_devices()
        assert "Bedroom" in result or "devices" in result.lower()


# ── HomeAssistantClient unit tests ────────────────────────────────────────────

class TestHomeAssistantClientEntityId:
    def setup_method(self):
        self.ha = HomeAssistantClient({"url": "http://ha.local:8123", "token": "tok"})

    def test_already_entity_id(self):
        assert self.ha._entity_id("light.bedroom") == "light.bedroom"

    def test_human_name_with_domain(self):
        assert self.ha._entity_id("bedroom light", domain="light") == "light.bedroom_light"

    def test_human_name_no_domain(self):
        assert self.ha._entity_id("bedroom light") == "bedroom_light"


class TestHomeAssistantClientLightOn:
    def setup_method(self):
        self.ha = HomeAssistantClient({"url": "http://ha.local:8123", "token": "tok"})

    def _mock_post(self, post_mock, entity, brightness_pct=None, color=None):
        self.ha.light_turn_on(entity, brightness_pct=brightness_pct, color=color)
        assert post_mock.called

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_turn_on_basic(self, mock_post):
        self.ha.light_turn_on("bedroom light")
        mock_post.assert_called_once()
        data = mock_post.call_args[0][1]
        assert data["entity_id"] == "light.bedroom_light"
        assert "brightness_pct" not in data

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_turn_on_with_brightness(self, mock_post):
        self.ha.light_turn_on("light.living_room", brightness_pct=75)
        data = mock_post.call_args[0][1]
        assert data["brightness_pct"] == 75

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_turn_on_with_named_color(self, mock_post):
        self.ha.light_turn_on("light.bedroom", color="red")
        data = mock_post.call_args[0][1]
        assert data["rgb_color"] == [255, 0, 0]

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_turn_on_with_unknown_color(self, mock_post):
        self.ha.light_turn_on("light.bedroom", color="seafoam")
        data = mock_post.call_args[0][1]
        assert data.get("color_name") == "seafoam"

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_brightness_clamped_high(self, mock_post):
        self.ha.light_turn_on("light.x", brightness_pct=150)
        data = mock_post.call_args[0][1]
        assert data["brightness_pct"] == 100

    @patch("jarvis.integrations.smarthome.HomeAssistantClient._post")
    def test_brightness_clamped_low(self, mock_post):
        self.ha.light_turn_on("light.x", brightness_pct=-10)
        data = mock_post.call_args[0][1]
        assert data["brightness_pct"] == 0


# ── HueDirectClient unit tests ────────────────────────────────────────────────

class TestHueDirectClient:
    def setup_method(self):
        self.hue = HueDirectClient({"bridge_ip": "192.168.1.2", "username": "appkey"})

    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_find_light_id_match(self, mock_get):
        mock_get.return_value = {
            "1": {"name": "Bedroom Light", "state": {"on": True, "bri": 200}},
            "2": {"name": "Kitchen", "state": {"on": False, "bri": 0}},
        }
        lid = self.hue._find_light_id("bedroom")
        assert lid == "1"

    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_find_light_id_no_match(self, mock_get):
        mock_get.return_value = {"1": {"name": "Kitchen", "state": {}}}
        assert self.hue._find_light_id("bedroom") is None

    @patch("jarvis.integrations.smarthome.HueDirectClient._put")
    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_light_turn_on(self, mock_get, mock_put):
        mock_get.return_value = {"3": {"name": "Living Room", "state": {}}}
        self.hue.light_turn_on("living room", brightness_pct=50)
        call_data = mock_put.call_args[0][1]
        assert call_data["on"] is True
        assert 100 < call_data["bri"] < 140  # ~50% of 254

    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_light_turn_on_not_found(self, mock_get):
        mock_get.return_value = {}
        with pytest.raises(ValueError, match="not found"):
            self.hue.light_turn_on("ghost light")

    @patch("jarvis.integrations.smarthome.HueDirectClient._put")
    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_light_turn_on_with_color(self, mock_get, mock_put):
        mock_get.return_value = {"1": {"name": "Desk Lamp", "state": {}}}
        self.hue.light_turn_on("desk lamp", color="blue")
        data = mock_put.call_args[0][1]
        assert "xy" in data
        assert len(data["xy"]) == 2


# ── SmartHomeClient facade ─────────────────────────────────────────────────────

class TestSmartHomeClientHA:
    def setup_method(self):
        cfg = {
            "backend": "home_assistant",
            "home_assistant": {"url": "http://ha:8123", "token": "t"},
        }
        self.client = SmartHomeClient(cfg)

    @patch("jarvis.integrations.smarthome.HomeAssistantClient.light_turn_on")
    def test_turn_on_light_success(self, mock_on):
        ok, msg = self.client.turn_on_light("bedroom", brightness=70, color="red")
        assert ok is True
        assert "Turned on" in msg
        mock_on.assert_called_once_with("bedroom", brightness_pct=70, color="red")

    @patch("jarvis.integrations.smarthome.HomeAssistantClient.light_turn_on",
           side_effect=Exception("timeout"))
    def test_turn_on_light_failure(self, _mock):
        ok, msg = self.client.turn_on_light("bedroom")
        assert ok is False
        assert "timeout" in msg

    @patch("jarvis.integrations.smarthome.HomeAssistantClient.switch_turn_on")
    def test_turn_on_plug(self, mock_on):
        ok, msg = self.client.turn_on_plug("coffee maker")
        assert ok is True
        assert "Turned on" in msg

    @patch("jarvis.integrations.smarthome.HomeAssistantClient.climate_set_temperature")
    def test_set_temperature(self, mock_set):
        ok, msg = self.client.set_temperature("climate.living_room", 22.0)
        assert ok is True
        mock_set.assert_called_once_with("climate.living_room", 22.0)

    @patch("jarvis.integrations.smarthome.HomeAssistantClient.climate_get_temperature")
    def test_get_temperature(self, mock_get):
        mock_get.return_value = {
            "state": "heat",
            "attributes": {
                "current_temperature": 20,
                "temperature": 22,
                "unit_of_measurement": "°C",
            },
        }
        ok, msg = self.client.get_temperature("climate.living_room")
        assert ok is True
        assert "20" in msg and "22" in msg


class TestSmartHomeClientHueDirect:
    def setup_method(self):
        cfg = {
            "backend": "hue_direct",
            "hue_direct": {"bridge_ip": "192.168.1.2", "username": "key"},
        }
        self.client = SmartHomeClient(cfg)

    def test_plug_not_supported(self):
        ok, msg = self.client.turn_on_plug("plug")
        assert ok is False
        assert "Home Assistant" in msg

    def test_thermostat_not_supported(self):
        ok, msg = self.client.set_temperature("thermostat", 22.0)
        assert ok is False

    @patch("jarvis.integrations.smarthome.HueDirectClient._put")
    @patch("jarvis.integrations.smarthome.HueDirectClient._get")
    def test_turn_on_light(self, mock_get, mock_put):
        mock_get.return_value = {"1": {"name": "Desk", "state": {}}}
        ok, msg = self.client.turn_on_light("desk")
        assert ok is True
        assert "Turned on" in msg


class TestSmartHomeClientUnknownBackend:
    def test_raises_on_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown smart_home backend"):
            SmartHomeClient({"backend": "magic"})
