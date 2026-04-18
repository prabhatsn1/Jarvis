import subprocess
import platform
import logging
import tempfile
import os
from datetime import datetime

log = logging.getLogger("jarvis.actions.system")

SYSTEM = platform.system()


def _osascript(script: str):
    subprocess.run(["osascript", "-e", script], check=True, timeout=5)


def _powershell(script: str):
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        timeout=5,
    )


def _powershell_file(script: str):
    """Write script to a temp .ps1 file and execute it — avoids all quote escaping."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False) as f:
        f.write(script)
        tmp = f.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            check=True,
            timeout=5,
        )
    finally:
        os.unlink(tmp)


# ── Volume ──────────────────────────────────────────────────────

_WAVEVOL_TYPE = """Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class WaveVol {
    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr h, uint v);
    [DllImport("winmm.dll")] public static extern int waveOutGetVolume(IntPtr h, out uint v);
}
"@ -ErrorAction SilentlyContinue
"""


def _wave_set(level_0_to_100: int):
    v = int(level_0_to_100 / 100 * 0xFFFF)
    stereo = v | (v << 16)
    _powershell_file(f"{_WAVEVOL_TYPE}[WaveVol]::waveOutSetVolume([IntPtr]::Zero, {stereo})")


def _wave_change(delta: int):
    _powershell_file(
        f"{_WAVEVOL_TYPE}"
        "$cur = [uint32]0\n"
        "[WaveVol]::waveOutGetVolume([IntPtr]::Zero, [ref]$cur) | Out-Null\n"
        "$lo = [int]($cur -band 0xFFFF)\n"
        f"$new = [Math]::Max(0, [Math]::Min(0xFFFF, $lo + {delta}))\n"
        "[WaveVol]::waveOutSetVolume([IntPtr]::Zero, [uint32]($new -bor ($new -shl 16)))"
    )


def set_volume(level):
    level = max(0, min(100, int(level)))
    if SYSTEM == "Darwin":
        _osascript(f"set volume output volume {level}")
    elif SYSTEM == "Windows":
        try:
            subprocess.run(["nircmd", "setsysvolume", str(int(level / 100 * 65535))], check=True, timeout=5)
        except FileNotFoundError:
            _wave_set(level)
    return f"Volume set to {level}"


def mute():
    if SYSTEM == "Darwin":
        _osascript("set volume output muted true")
    elif SYSTEM == "Windows":
        try:
            subprocess.run(["nircmd", "mutesysvolume", "1"], check=True, timeout=5)
        except FileNotFoundError:
            _wave_set(0)
    return "Muted"


def unmute():
    if SYSTEM == "Darwin":
        _osascript("set volume output muted false")
    elif SYSTEM == "Windows":
        try:
            subprocess.run(["nircmd", "mutesysvolume", "0"], check=True, timeout=5)
        except FileNotFoundError:
            _wave_set(50)
    return "Unmuted"


def volume_up():
    if SYSTEM == "Darwin":
        _osascript(
            "set curVol to output volume of (get volume settings)\n"
            "set volume output volume (curVol + 10)"
        )
    elif SYSTEM == "Windows":
        try:
            subprocess.run(["nircmd", "changesysvolume", "6553"], check=True, timeout=5)
        except FileNotFoundError:
            _wave_change(6553)
    return "Volume up"


def volume_down():
    if SYSTEM == "Darwin":
        _osascript(
            "set curVol to output volume of (get volume settings)\n"
            "set volume output volume (curVol - 10)"
        )
    elif SYSTEM == "Windows":
        try:
            subprocess.run(["nircmd", "changesysvolume", "-6553"], check=True, timeout=5)
        except FileNotFoundError:
            _wave_change(-6553)
    return "Volume down"


# ── Brightness ──────────────────────────────────────────────────

def brightness_up():
    if SYSTEM == "Darwin":
        _osascript('tell application "System Events" to key code 144')
    elif SYSTEM == "Windows":
        _powershell(
            "$brightness = (Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightness).CurrentBrightness;"
            "$new = [Math]::Min(100, $brightness + 10);"
            "Set-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightnessMethods "
            "-Arguments @{Timeout=1;Brightness=$new}"
        )
    return "Brightness up"


def brightness_down():
    if SYSTEM == "Darwin":
        _osascript('tell application "System Events" to key code 145')
    elif SYSTEM == "Windows":
        _powershell(
            "$brightness = (Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightness).CurrentBrightness;"
            "$new = [Math]::Max(0, $brightness - 10);"
            "Set-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightnessMethods "
            "-Arguments @{Timeout=1;Brightness=$new}"
        )
    return "Brightness down"


# ── Do Not Disturb ──────────────────────────────────────────────

def dnd_on():
    if SYSTEM == "Darwin":
        subprocess.run(
            ["shortcuts", "run", "Turn On Focus"],
            timeout=5,
            capture_output=True,
        )
    elif SYSTEM == "Windows":
        _powershell(
            "New-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' "
            "-Name 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' -Value 0 "
            "-PropertyType DWORD -Force"
        )
    return "Do not disturb on"


def dnd_off():
    if SYSTEM == "Darwin":
        subprocess.run(
            ["shortcuts", "run", "Turn Off Focus"],
            timeout=5,
            capture_output=True,
        )
    elif SYSTEM == "Windows":
        _powershell(
            "Set-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings' "
            "-Name 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' -Value 1"
        )
    return "Do not disturb off"


# ── Appearance ──────────────────────────────────────────────────

def dark_mode_on():
    if SYSTEM == "Darwin":
        _osascript(
            'tell application "System Events" to tell appearance preferences '
            'to set dark mode to true'
        )
    elif SYSTEM == "Windows":
        _powershell(
            "Set-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' "
            "-Name 'AppsUseLightTheme' -Value 0;"
            "Set-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' "
            "-Name 'SystemUsesLightTheme' -Value 0"
        )
    return "Dark mode on"


def dark_mode_off():
    if SYSTEM == "Darwin":
        _osascript(
            'tell application "System Events" to tell appearance preferences '
            'to set dark mode to false'
        )
    elif SYSTEM == "Windows":
        _powershell(
            "Set-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' "
            "-Name 'AppsUseLightTheme' -Value 1;"
            "Set-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' "
            "-Name 'SystemUsesLightTheme' -Value 1"
        )
    return "Dark mode off"


# ── Power ───────────────────────────────────────────────────────

def lock_screen():
    if SYSTEM == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], timeout=5)
    elif SYSTEM == "Windows":
        subprocess.run(["rundll32", "user32.dll,LockWorkStation"], timeout=5)
    return "Screen locked"


def sleep():
    if SYSTEM == "Darwin":
        _osascript('tell application "System Events" to sleep')
    elif SYSTEM == "Windows":
        subprocess.run(
            ["rundll32", "powrprof.dll,SetSuspendState", "0,1,0"],
            timeout=5,
        )
    return "Sleeping"


# ── Screenshot ──────────────────────────────────────────────────

def screenshot():
    if SYSTEM == "Darwin":
        subprocess.run(["screencapture", "-i", "-c"], timeout=30)
    elif SYSTEM == "Windows":
        # Opens Snipping Tool
        subprocess.Popen(["snippingtool", "/clip"])
    return "Screenshot captured"


# ── Trash ───────────────────────────────────────────────────────

def empty_trash():
    if SYSTEM == "Darwin":
        _osascript('tell application "Finder" to empty trash')
    elif SYSTEM == "Windows":
        _powershell(
            "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"
        )
    return "Trash emptied"


# ── Time & Date ─────────────────────────────────────────────────

def tell_time():
    return datetime.now().strftime("It's %I:%M %p")


def tell_date():
    return datetime.now().strftime("Today is %A, %B %d, %Y")


# ── Jarvis Meta ─────────────────────────────────────────────────

def status():
    return "All systems operational, sir."


def jarvis_sleep():
    return "Standing by."
