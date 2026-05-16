"""System health monitor with threshold-based proactive voice alerts."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, Optional

log = logging.getLogger("jarvis.monitor.health")

# ── psutil (required) ────────────────────────────────────────────────────────
try:
    import psutil  # type: ignore
    _PSUTIL_OK = True
except ImportError:  # pragma: no cover
    log.warning("psutil not installed – health monitor will not sample metrics")
    _PSUTIL_OK = False

# ── GPUtil (optional) ────────────────────────────────────────────────────────
try:
    import GPUtil  # type: ignore
    _GPUTIL_OK = True
except ImportError:
    _GPUTIL_OK = False


# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------
Metrics = Dict[str, Optional[float]]
AlertCallback = Callable[[str, float, float, str], None]


# ---------------------------------------------------------------------------
# Severity thresholds
# ---------------------------------------------------------------------------
_SEVERITY_EMERGENCY = "emergency"   # value >= emergency_threshold
_SEVERITY_WARNING = "warning"       # value >= warning_threshold


class _MetricCooldown:
    """Tracks per-metric cooldown and crossing state."""

    def __init__(self, cooldown_sec: float, emergency_cooldown_sec: float):
        self.cooldown_sec = cooldown_sec
        self.emergency_cooldown_sec = emergency_cooldown_sec
        self._last_alert_time: Optional[float] = None
        self._was_above: bool = False          # above warning threshold
        self._was_above_emergency: bool = False

    def should_alert(self, value: float, threshold: float,
                     emergency_threshold: float) -> Optional[str]:
        """
        Return severity string if an alert should fire, else None.

        Alert fires when:
        - value crosses above threshold for the first time, OR
        - value was below threshold (reset) and crossed again, OR
        - cooldown elapsed since last alert.
        """
        now = time.monotonic()
        above_emergency = value >= emergency_threshold
        above_warning = value >= threshold

        if above_emergency:
            elapsed = (now - self._last_alert_time) if self._last_alert_time else float("inf")
            if not self._was_above_emergency or elapsed >= self.emergency_cooldown_sec:
                self._last_alert_time = now
                self._was_above = True
                self._was_above_emergency = True
                return _SEVERITY_EMERGENCY
            return None

        if above_warning:
            if not self._was_above:
                # Fresh crossing
                self._last_alert_time = now
                self._was_above = True
                self._was_above_emergency = False
                return _SEVERITY_WARNING
            elapsed = (now - self._last_alert_time) if self._last_alert_time else float("inf")
            if elapsed >= self.cooldown_sec:
                self._last_alert_time = now
                self._was_above_emergency = False
                return _SEVERITY_WARNING
            return None

        # Below threshold – reset crossing flags so next crossing fires fresh
        self._was_above = False
        self._was_above_emergency = False
        return None


# ---------------------------------------------------------------------------
# SystemHealthMonitor
# ---------------------------------------------------------------------------

class SystemHealthMonitor:
    """
    Background monitor that samples CPU/RAM/disk/(GPU) at a fixed interval
    and fires alert callbacks when metrics cross configured thresholds.

    Parameters
    ----------
    config : dict
        The ``health_monitor`` sub-config block from ``config.yaml``.
    on_alert : AlertCallback, optional
        Signature: ``on_alert(metric_name, value, threshold, severity)``.
    """

    def __init__(self, config: dict, on_alert: Optional[AlertCallback] = None):
        self._cfg = config
        self._on_alert = on_alert
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._latest: Optional[Metrics] = None
        self._lock = threading.Lock()

        interval = self._cfg.get("sample_interval_sec", 10)
        cooldown = self._cfg.get("cooldown_sec", 180)
        emergency_cooldown = max(30, cooldown // 3)

        self._cooldowns: Dict[str, _MetricCooldown] = {
            m: _MetricCooldown(cooldown, emergency_cooldown)
            for m in ("cpu", "ram", "disk", "gpu")
        }

    # ── Public interface ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            log.warning("Health monitor already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="health-monitor", daemon=True
        )
        self._thread.start()
        log.info("Health monitor started (interval=%ss)", self._cfg.get("sample_interval_sec", 10))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        log.info("Health monitor stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def sample_metrics(self) -> Metrics:
        """Take an immediate synchronous metrics sample."""
        result: Metrics = {
            "cpu_percent": None,
            "ram_percent": None,
            "disk_percent": None,
            "gpu_percent": None,
            "timestamp": datetime.now().isoformat(),
        }
        if not _PSUTIL_OK:
            return result

        try:
            result["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        except Exception as exc:
            log.warning("CPU sampling error: %s", exc)

        try:
            result["ram_percent"] = psutil.virtual_memory().percent
        except Exception as exc:
            log.warning("RAM sampling error: %s", exc)

        try:
            disk_path = self._cfg.get("disk_path", "/")
            result["disk_percent"] = psutil.disk_usage(disk_path).percent
        except Exception as exc:
            log.warning("Disk sampling error: %s", exc)

        if _GPUTIL_OK:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    result["gpu_percent"] = gpus[0].load * 100.0
            except Exception as exc:
                log.warning("GPU sampling error: %s", exc)

        return result

    def latest_metrics(self) -> Optional[Metrics]:
        """Return the most recent cached sample, or None if none yet."""
        with self._lock:
            return dict(self._latest) if self._latest else None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        interval = max(1, self._cfg.get("sample_interval_sec", 10))
        while not self._stop_event.is_set():
            try:
                metrics = self.sample_metrics()
                with self._lock:
                    self._latest = metrics
                self._check_thresholds(metrics)
            except Exception as exc:
                log.warning("Health monitor sampling error: %s", exc)
            self._stop_event.wait(interval)

    def _check_thresholds(self, metrics: Metrics) -> None:
        thresholds = self._cfg.get("thresholds", {})
        emergency = self._cfg.get("emergency_thresholds", {})

        checks = [
            ("cpu",  metrics.get("cpu_percent"),  thresholds.get("cpu_percent",  90),
             emergency.get("cpu_percent",  98)),
            ("ram",  metrics.get("ram_percent"),  thresholds.get("ram_percent",  85),
             emergency.get("ram_percent",  95)),
            ("disk", metrics.get("disk_percent"), thresholds.get("disk_percent", 90),
             emergency.get("disk_percent", 98)),
            ("gpu",  metrics.get("gpu_percent"),  thresholds.get("gpu_percent",  90),
             emergency.get("gpu_percent",  98)),
        ]

        for key, value, threshold, emerg_threshold in checks:
            if value is None:
                continue
            severity = self._cooldowns[key].should_alert(value, threshold, emerg_threshold)
            if severity:
                log.warning(
                    "Threshold crossed: %s=%.1f%% threshold=%.1f%% severity=%s",
                    key, value, threshold, severity,
                )
                if self._on_alert:
                    try:
                        self._on_alert(key, value, threshold, severity)
                    except Exception as exc:
                        log.warning("Alert callback error: %s", exc)


# ---------------------------------------------------------------------------
# Singleton / service-locator used by action module
# ---------------------------------------------------------------------------

_instance: Optional[SystemHealthMonitor] = None
_instance_lock = threading.Lock()


def get_monitor() -> Optional[SystemHealthMonitor]:
    """Return the shared monitor instance (may be None if not yet set up)."""
    with _instance_lock:
        return _instance


def set_monitor(monitor: SystemHealthMonitor) -> None:
    """Register the shared monitor instance (called from core.py)."""
    global _instance
    with _instance_lock:
        _instance = monitor
