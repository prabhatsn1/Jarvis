"""Tests for SystemHealthMonitor – metrics sampling, threshold/cooldown, GPU fallback."""

import sys
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**overrides):
    cfg = {
        "enabled": True,
        "sample_interval_sec": 1,
        "cooldown_sec": 60,
        "disk_path": "/",
        "thresholds": {
            "cpu_percent": 80,
            "ram_percent": 80,
            "disk_percent": 80,
            "gpu_percent": 80,
        },
        "emergency_thresholds": {
            "cpu_percent": 95,
            "ram_percent": 95,
            "disk_percent": 95,
            "gpu_percent": 95,
        },
    }
    cfg.update(overrides)
    return cfg


def _mock_psutil(cpu=50.0, ram=50.0, disk=50.0):
    """Return a mock psutil module with controllable values."""
    m = MagicMock()
    m.cpu_percent.return_value = cpu
    vm = MagicMock()
    vm.percent = ram
    m.virtual_memory.return_value = vm
    du = MagicMock()
    du.percent = disk
    m.disk_usage.return_value = du
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSampleMetrics(unittest.TestCase):
    """sample_metrics() populates expected keys and uses psutil values."""

    def test_returns_expected_keys(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()), \
             patch("jarvis.monitor.health._GPUTIL_OK", False):
            monitor = SystemHealthMonitor(_make_cfg())
            m = monitor.sample_metrics()
        self.assertIn("cpu_percent", m)
        self.assertIn("ram_percent", m)
        self.assertIn("disk_percent", m)
        self.assertIn("gpu_percent", m)
        self.assertIn("timestamp", m)

    def test_values_come_from_psutil(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil(cpu=42.0, ram=55.0, disk=70.0)), \
             patch("jarvis.monitor.health._GPUTIL_OK", False):
            monitor = SystemHealthMonitor(_make_cfg())
            m = monitor.sample_metrics()
        self.assertAlmostEqual(m["cpu_percent"], 42.0, places=1)
        self.assertAlmostEqual(m["ram_percent"], 55.0, places=1)
        self.assertAlmostEqual(m["disk_percent"], 70.0, places=1)

    def test_no_gpu_returns_none(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()), \
             patch("jarvis.monitor.health._GPUTIL_OK", False):
            monitor = SystemHealthMonitor(_make_cfg())
            m = monitor.sample_metrics()
        self.assertIsNone(m["gpu_percent"])

    def test_psutil_unavailable(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", False):
            monitor = SystemHealthMonitor(_make_cfg())
            m = monitor.sample_metrics()
        self.assertIsNone(m["cpu_percent"])
        self.assertIsNone(m["ram_percent"])
        self.assertIsNone(m["disk_percent"])
        self.assertIsNone(m["gpu_percent"])

    def test_gpu_value_from_gputil(self):
        from jarvis.monitor.health import SystemHealthMonitor
        mock_gpu = MagicMock()
        mock_gpu.load = 0.75
        mock_gputil = MagicMock()
        mock_gputil.getGPUs.return_value = [mock_gpu]
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()), \
             patch("jarvis.monitor.health._GPUTIL_OK", True), \
             patch("jarvis.monitor.health.GPUtil", mock_gputil):
            monitor = SystemHealthMonitor(_make_cfg())
            m = monitor.sample_metrics()
        self.assertAlmostEqual(m["gpu_percent"], 75.0, places=1)


class TestThresholdAlerts(unittest.TestCase):
    """Threshold crossing fires callback exactly once per cooldown."""

    def _make_monitor_and_tracker(self, cfg=None):
        from jarvis.monitor.health import SystemHealthMonitor
        alerts = []

        def on_alert(metric, value, threshold, severity):
            alerts.append((metric, value, threshold, severity))

        monitor = SystemHealthMonitor(cfg or _make_cfg(), on_alert=on_alert)
        return monitor, alerts

    def test_crossing_fires_exactly_once(self):
        monitor, alerts = self._make_monitor_and_tracker()
        metrics = {
            "cpu_percent": 90.0,   # above threshold 80
            "ram_percent": 50.0,
            "disk_percent": 50.0,
            "gpu_percent": None,
            "timestamp": "now",
        }
        with patch("jarvis.monitor.health._PSUTIL_OK", True):
            monitor._check_thresholds(metrics)
            monitor._check_thresholds(metrics)   # second call in cooldown → no second alert
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "cpu")

    def test_no_alert_below_threshold(self):
        monitor, alerts = self._make_monitor_and_tracker()
        metrics = {
            "cpu_percent": 50.0,
            "ram_percent": 50.0,
            "disk_percent": 50.0,
            "gpu_percent": None,
            "timestamp": "now",
        }
        monitor._check_thresholds(metrics)
        self.assertEqual(len(alerts), 0)

    def test_alert_after_reset_and_recross(self):
        monitor, alerts = self._make_monitor_and_tracker()
        high = {"cpu_percent": 90.0, "ram_percent": 50.0, "disk_percent": 50.0,
                "gpu_percent": None, "timestamp": "now"}
        low  = {"cpu_percent": 50.0, "ram_percent": 50.0, "disk_percent": 50.0,
                "gpu_percent": None, "timestamp": "now"}
        monitor._check_thresholds(high)   # crosses → alert 1
        monitor._check_thresholds(low)    # drops below → reset
        monitor._check_thresholds(high)   # crosses again → alert 2
        self.assertEqual(len(alerts), 2)

    def test_emergency_severity_fires(self):
        monitor, alerts = self._make_monitor_and_tracker()
        metrics = {
            "cpu_percent": 97.0,   # above emergency threshold 95
            "ram_percent": 50.0,
            "disk_percent": 50.0,
            "gpu_percent": None,
            "timestamp": "now",
        }
        monitor._check_thresholds(metrics)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][3], "emergency")

    def test_cooldown_elapsed_fires_again(self):
        """After cooldown_sec passes, another alert fires."""
        cfg = _make_cfg(cooldown_sec=10)
        monitor, alerts = self._make_monitor_and_tracker(cfg)
        metrics = {"cpu_percent": 90.0, "ram_percent": 50.0,
                   "disk_percent": 50.0, "gpu_percent": None, "timestamp": "now"}
        monitor._check_thresholds(metrics)
        # Manually backdate the last alert time by more than cooldown
        monitor._cooldowns["cpu"]._last_alert_time -= 11
        monitor._check_thresholds(metrics)
        self.assertEqual(len(alerts), 2)

    def test_no_gpu_no_alert(self):
        monitor, alerts = self._make_monitor_and_tracker()
        metrics = {"cpu_percent": 50.0, "ram_percent": 50.0,
                   "disk_percent": 50.0, "gpu_percent": None, "timestamp": "now"}
        monitor._check_thresholds(metrics)
        gpu_alerts = [a for a in alerts if a[0] == "gpu"]
        self.assertEqual(len(gpu_alerts), 0)


class TestStartStop(unittest.TestCase):
    """start/stop are idempotent and thread-safe."""

    def test_start_stop(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()):
            monitor = SystemHealthMonitor(_make_cfg())
            monitor.start()
            self.assertTrue(monitor.is_running())
            monitor.stop()
            self.assertFalse(monitor.is_running())

    def test_double_start_idempotent(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()):
            monitor = SystemHealthMonitor(_make_cfg())
            monitor.start()
            monitor.start()   # second start must not raise
            self.assertTrue(monitor.is_running())
            monitor.stop()

    def test_double_stop_idempotent(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()):
            monitor = SystemHealthMonitor(_make_cfg())
            monitor.start()
            monitor.stop()
            monitor.stop()   # second stop must not raise
            self.assertFalse(monitor.is_running())

    def test_not_running_initially(self):
        from jarvis.monitor.health import SystemHealthMonitor
        monitor = SystemHealthMonitor(_make_cfg())
        self.assertFalse(monitor.is_running())

    def test_thread_safe_concurrent_start(self):
        from jarvis.monitor.health import SystemHealthMonitor
        with patch("jarvis.monitor.health._PSUTIL_OK", True), \
             patch("jarvis.monitor.health.psutil", _mock_psutil()):
            monitor = SystemHealthMonitor(_make_cfg())
            errors = []

            def start_it():
                try:
                    monitor.start()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=start_it) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            monitor.stop()


if __name__ == "__main__":
    unittest.main()
