"""Voice-action handlers for the system health monitor."""

from __future__ import annotations

import logging

from jarvis.monitor.health import get_monitor

log = logging.getLogger("jarvis.actions.monitor")


def health_status(**_slots) -> str:
    """Return a spoken summary of the latest resource metrics."""
    monitor = get_monitor()
    if monitor is None:
        return "Health monitor is not configured."

    metrics = monitor.latest_metrics()
    if metrics is None:
        if not monitor.is_running():
            return "Health monitor is not running. Say 'start resource monitor' to enable it."
        return "No metrics sampled yet. Please wait a moment."

    parts = []
    if metrics.get("cpu_percent") is not None:
        parts.append(f"CPU at {metrics['cpu_percent']:.0f}%")
    if metrics.get("ram_percent") is not None:
        parts.append(f"RAM at {metrics['ram_percent']:.0f}%")
    if metrics.get("disk_percent") is not None:
        parts.append(f"disk at {metrics['disk_percent']:.0f}%")
    if metrics.get("gpu_percent") is not None:
        parts.append(f"GPU at {metrics['gpu_percent']:.0f}%")

    if not parts:
        return "Could not read any system metrics."

    return "Boss, current usage: " + ", ".join(parts) + "."


def enable_monitor(**_slots) -> str:
    """Start the health monitor."""
    monitor = get_monitor()
    if monitor is None:
        return "Health monitor is not configured."
    if monitor.is_running():
        return "Health monitor is already running."
    monitor.start()
    return "Health monitor enabled. I'll alert you if resources run high."


def disable_monitor(**_slots) -> str:
    """Stop the health monitor."""
    monitor = get_monitor()
    if monitor is None:
        return "Health monitor is not configured."
    if not monitor.is_running():
        return "Health monitor is not running."
    monitor.stop()
    return "Health monitor disabled."
