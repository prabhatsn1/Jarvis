import os
import platform

import yaml
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
SYSTEM = platform.system()


def load_config(path=None):
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Expand ~ in paths
    if "memory" in config and "db_path" in config["memory"]:
        config["memory"]["db_path"] = os.path.expanduser(config["memory"]["db_path"])

    # Platform-specific IPC defaults
    if "ipc" in config and "socket_path" in config["ipc"]:
        if SYSTEM == "Windows" and config["ipc"]["socket_path"] == "/tmp/jarvis.sock":
            config["ipc"]["socket_path"] = r"\\.\pipe\jarvis"

    # Platform-specific voice defaults
    if "voice" in config:
        if SYSTEM == "Windows" and config["voice"].get("voice") == "Daniel":
            config["voice"]["voice"] = "David"

    return config
