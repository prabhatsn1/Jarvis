"""Periodic IPC broadcaster for live stats (time, weather, system health)."""

import threading
import time
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("jarvis.monitor.stats")

_WEATHER_TTL = 600  # re-fetch every 10 minutes


class StatsBroadcaster:
    """Broadcasts {"type": "stats", ...} to HUD clients every N seconds."""

    def __init__(self, ipc, health_monitor, interval_sec: int = 5):
        self._ipc = ipc
        self._monitor = health_monitor
        self._interval = max(1, interval_sec)
        self._weather_cache: Optional[str] = None
        self._weather_fetched_at: float = 0.0
        self._task = ""
        self._lock = threading.Lock()
        self._running = False

    def set_task(self, task: str) -> None:
        """Update the active-task label shown on the HUD."""
        with self._lock:
            self._task = (task or "")[:50]

    def start(self) -> None:
        self._running = True
        threading.Thread(
            target=self._loop, daemon=True, name="stats-broadcaster"
        ).start()
        log.info("Stats broadcaster started (interval=%ss)", self._interval)

    def stop(self) -> None:
        self._running = False

    # ── internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._broadcast()
            except Exception as exc:
                log.debug("Stats broadcast error: %s", exc)
            time.sleep(self._interval)

    def _broadcast(self) -> None:
        metrics: dict = {}
        if self._monitor:
            metrics = self._monitor.latest_metrics() or {}
        with self._lock:
            task = self._task

        try:
            self._ipc.broadcast({
                "type": "stats",
                "time": datetime.now().strftime("%H:%M"),
                "cpu": metrics.get("cpu_percent"),
                "ram": metrics.get("ram_percent"),
                "disk": metrics.get("disk_percent"),
                "weather": self._get_weather(),
                "task": task,
            })
        except Exception as exc:
            log.debug("Stats IPC error: %s", exc)

    def _get_weather(self) -> Optional[str]:
        now = time.monotonic()
        if self._weather_cache is not None and now - self._weather_fetched_at < _WEATHER_TTL:
            return self._weather_cache
        try:
            from urllib.request import urlopen
            with urlopen("https://wttr.in/?format=%t+%C", timeout=5) as resp:
                raw = resp.read().decode().strip()
            self._weather_cache = raw.lstrip("+")
            self._weather_fetched_at = now
            return self._weather_cache
        except Exception as exc:
            log.debug("Weather fetch failed: %s", exc)
            return self._weather_cache
