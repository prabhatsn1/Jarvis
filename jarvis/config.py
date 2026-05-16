import os
import platform
import logging

import yaml
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
SYSTEM = platform.system()

log = logging.getLogger("jarvis.config")


def _clamp(value, lo, hi, default, label):
    """Return value clamped to [lo, hi], logging a warning if out of range."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        log.warning("Invalid config value for %s (%r), using default %s", label, value, default)
        return default
    if v < lo or v > hi:
        clamped = max(lo, min(hi, v))
        log.warning("Config %s=%s out of range [%s, %s], clamping to %s", label, v, lo, hi, clamped)
        return clamped
    return v


def _validate_health_monitor(cfg: dict) -> dict:
    """Apply defaults and validate ranges for the health_monitor block."""
    defaults = {
        "enabled": False,
        "sample_interval_sec": 10,
        "cooldown_sec": 180,
        "disk_path": "/" if SYSTEM != "Windows" else "C:/",
        "thresholds": {
            "cpu_percent": 90,
            "ram_percent": 85,
            "disk_percent": 90,
            "gpu_percent": 90,
        },
        "emergency_thresholds": {
            "cpu_percent": 98,
            "ram_percent": 95,
            "disk_percent": 98,
            "gpu_percent": 98,
        },
    }

    # Merge missing top-level keys
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v

    cfg["sample_interval_sec"] = int(
        _clamp(cfg.get("sample_interval_sec", 10), 1, 3600, 10, "health_monitor.sample_interval_sec")
    )
    cfg["cooldown_sec"] = int(
        _clamp(cfg.get("cooldown_sec", 180), 10, 86400, 180, "health_monitor.cooldown_sec")
    )

    for sub_key in ("thresholds", "emergency_thresholds"):
        block = cfg.get(sub_key) or {}
        for metric in ("cpu_percent", "ram_percent", "disk_percent", "gpu_percent"):
            default_val = defaults[sub_key][metric]
            block[metric] = int(
                _clamp(block.get(metric, default_val), 1, 100, default_val,
                       f"health_monitor.{sub_key}.{metric}")
            )
        cfg[sub_key] = block

    return cfg


def _validate_integrations(cfg: dict) -> dict:
    """Apply safe defaults and validate the integrations config block."""
    defaults: dict = {
        "enabled": True,
        "timezone": "local",
        "schedule_default_window_hours": 24,
        "calendar": {
            "google_enabled": True,
            "outlook_enabled": True,
            "max_events_per_query": 20,
        },
        "email": {
            "gmail_enabled": True,
            "outlook_enabled": True,
        },
        "oauth": {
            "redirect_port": 8765,
            "use_local_server_callback": True,
            "token_store": "keyring",
        },
        "google": {
            "client_id": "",
            "client_secret": "",
        },
        "microsoft": {
            "tenant": "common",
            "client_id": "",
            "client_secret": "",
        },
    }

    # Merge top-level keys that are missing
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
        elif isinstance(v, dict) and isinstance(cfg[k], dict):
            for sub_k, sub_v in v.items():
                if sub_k not in cfg[k]:
                    cfg[k][sub_k] = sub_v

    # Validate redirect_port
    port = cfg["oauth"].get("redirect_port", 8765)
    try:
        port = int(port)
        if not (1024 <= port <= 65535):
            log.warning(
                "integrations.oauth.redirect_port %d out of range, using 8765", port
            )
            port = 8765
    except (TypeError, ValueError):
        log.warning("Invalid integrations.oauth.redirect_port, using 8765")
        port = 8765
    cfg["oauth"]["redirect_port"] = port

    # Validate booleans
    for bool_path in (
        ("enabled",),
        ("calendar", "google_enabled"),
        ("calendar", "outlook_enabled"),
        ("email", "gmail_enabled"),
        ("email", "outlook_enabled"),
        ("oauth", "use_local_server_callback"),
    ):
        if len(bool_path) == 1:
            v = cfg.get(bool_path[0])
        else:
            v = cfg.get(bool_path[0], {}).get(bool_path[1])
        if not isinstance(v, bool):
            default_v = defaults
            for part in bool_path:
                default_v = default_v[part]
            log.warning(
                "integrations.%s is not a boolean (%r), using %s",
                ".".join(bool_path), v, default_v,
            )
            if len(bool_path) == 1:
                cfg[bool_path[0]] = bool(default_v)
            else:
                cfg[bool_path[0]][bool_path[1]] = bool(default_v)

    # Validate max_events_per_query
    max_ev = cfg["calendar"].get("max_events_per_query", 20)
    try:
        max_ev = int(max_ev)
        if max_ev < 1:
            max_ev = 20
    except (TypeError, ValueError):
        max_ev = 20
    cfg["calendar"]["max_events_per_query"] = max_ev

    # Never let secrets appear in logs — redact them before returning
    return cfg


def load_config(path=None):
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Expand ~ in paths
    if "memory" in config and "db_path" in config["memory"]:
        config["memory"]["db_path"] = os.path.expanduser(config["memory"]["db_path"])
    if "memory" in config and "vector_db_path" in config["memory"]:
        config["memory"]["vector_db_path"] = os.path.expanduser(
            config["memory"]["vector_db_path"]
        )

    # Platform-specific IPC defaults
    if "ipc" in config and "socket_path" in config["ipc"]:
        if SYSTEM == "Windows" and config["ipc"]["socket_path"] == "/tmp/jarvis.sock":
            config["ipc"]["socket_path"] = r"\\.\pipe\jarvis"

    # Platform-specific voice defaults
    if "voice" in config:
        if SYSTEM == "Windows" and config["voice"].get("voice") == "Daniel":
            config["voice"]["voice"] = "David"

    # Health monitor defaults + validation
    config["health_monitor"] = _validate_health_monitor(
        config.get("health_monitor") or {}
    )

    # Integrations defaults + validation (backwards-compatible — block may be absent)
    config["integrations"] = _validate_integrations(
        config.get("integrations") or {}
    )

    return config
