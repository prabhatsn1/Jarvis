import subprocess
import platform
import logging

log = logging.getLogger("jarvis.actions.apps")

SYSTEM = platform.system()


def open_app(app: str):
    if SYSTEM == "Darwin":
        subprocess.run(["open", "-a", app], check=True, timeout=5)
    elif SYSTEM == "Windows":
        subprocess.run(["start", "", app], shell=True, check=True, timeout=5)
    return f"Opened {app}"


def close_app(app: str):
    if SYSTEM == "Darwin":
        subprocess.run(
            ["osascript", "-e", f'tell application "{app}" to quit'],
            check=True,
            timeout=5,
        )
    elif SYSTEM == "Windows":
        subprocess.run(
            ["taskkill", "/IM", f"{app}.exe", "/F"],
            check=True,
            timeout=5,
        )
    return f"Closed {app}"


def switch_to_app(app: str):
    if SYSTEM == "Darwin":
        subprocess.run(
            ["osascript", "-e", f'tell application "{app}" to activate'],
            check=True,
            timeout=5,
        )
    elif SYSTEM == "Windows":
        # Use PowerShell to bring window to front
        ps_script = (
            f"$proc = Get-Process -Name '{app}' -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; "
            "if ($proc) { "
            "Add-Type '[DllImport(\"user32.dll\")] public static extern bool "
            "SetForegroundWindow(IntPtr hWnd);' -Name User32 -Namespace Win32; "
            "[Win32.User32]::SetForegroundWindow($proc.MainWindowHandle) }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            check=True,
            timeout=5,
        )
    return f"Switched to {app}"
