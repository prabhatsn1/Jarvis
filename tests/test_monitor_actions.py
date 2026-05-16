"""Tests for jarvis/actions/monitor.py – health_status, enable/disable."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_mock_monitor(running=True, latest=None):
    m = MagicMock()
    m.is_running.return_value = running
    m.latest_metrics.return_value = latest or {
        "cpu_percent": 45.0,
        "ram_percent": 62.0,
        "disk_percent": 30.0,
        "gpu_percent": None,
        "timestamp": "2026-01-01T00:00:00",
    }
    return m


class TestHealthStatus(unittest.TestCase):

    def test_returns_formatted_string(self):
        mock_monitor = _make_mock_monitor()
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertIsInstance(result, str)
        self.assertIn("CPU", result)
        self.assertIn("RAM", result)
        self.assertIn("disk", result)

    def test_no_gpu_not_mentioned(self):
        mock_monitor = _make_mock_monitor()
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertNotIn("GPU", result)

    def test_gpu_mentioned_when_present(self):
        metrics = {
            "cpu_percent": 45.0, "ram_percent": 62.0,
            "disk_percent": 30.0, "gpu_percent": 55.0,
            "timestamp": "2026-01-01T00:00:00",
        }
        mock_monitor = _make_mock_monitor(latest=metrics)
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertIn("GPU", result)

    def test_monitor_none(self):
        with patch("jarvis.actions.monitor.get_monitor", return_value=None):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertIn("not configured", result.lower())

    def test_no_sample_yet(self):
        mock_monitor = _make_mock_monitor(running=True, latest=None)
        mock_monitor.latest_metrics.return_value = None
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertTrue(
            "wait" in result.lower() or "not running" in result.lower() or "no metrics" in result.lower()
        )

    def test_not_running_no_sample(self):
        mock_monitor = _make_mock_monitor(running=False, latest=None)
        mock_monitor.latest_metrics.return_value = None
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.health_status()
        self.assertIn("not running", result.lower())


class TestEnableMonitor(unittest.TestCase):

    def test_starts_monitor(self):
        mock_monitor = _make_mock_monitor(running=False)
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.enable_monitor()
        mock_monitor.start.assert_called_once()
        self.assertIsInstance(result, str)

    def test_already_running(self):
        mock_monitor = _make_mock_monitor(running=True)
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.enable_monitor()
        mock_monitor.start.assert_not_called()
        self.assertIn("already", result.lower())

    def test_monitor_none(self):
        with patch("jarvis.actions.monitor.get_monitor", return_value=None):
            from jarvis.actions import monitor as act
            result = act.enable_monitor()
        self.assertIn("not configured", result.lower())


class TestDisableMonitor(unittest.TestCase):

    def test_stops_monitor(self):
        mock_monitor = _make_mock_monitor(running=True)
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.disable_monitor()
        mock_monitor.stop.assert_called_once()
        self.assertIsInstance(result, str)

    def test_already_stopped(self):
        mock_monitor = _make_mock_monitor(running=False)
        with patch("jarvis.actions.monitor.get_monitor", return_value=mock_monitor):
            from jarvis.actions import monitor as act
            result = act.disable_monitor()
        mock_monitor.stop.assert_not_called()
        self.assertIn("not running", result.lower())

    def test_monitor_none(self):
        with patch("jarvis.actions.monitor.get_monitor", return_value=None):
            from jarvis.actions import monitor as act
            result = act.disable_monitor()
        self.assertIn("not configured", result.lower())


if __name__ == "__main__":
    unittest.main()
