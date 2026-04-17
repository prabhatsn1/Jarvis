import os
import subprocess
import platform
import logging

log = logging.getLogger("jarvis.actions.files")

SYSTEM = platform.system()


def open_file(path: str):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"File not found: {path}"

    if SYSTEM == "Darwin":
        subprocess.run(["open", path], check=True, timeout=5)
    elif SYSTEM == "Windows":
        os.startfile(path)
    return f"Opened {path}"


def open_folder(path: str):
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return f"Folder not found: {path}"

    if SYSTEM == "Darwin":
        subprocess.run(["open", path], check=True, timeout=5)
    elif SYSTEM == "Windows":
        subprocess.run(["explorer", path], check=True, timeout=5)
    return f"Opened {path}"
