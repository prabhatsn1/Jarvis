"""Callable tool implementations for LLM function-calling.

Each tool function accepts validated kwargs and returns a plain-text result
string suitable for feeding back to the model as a tool response.
"""

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

log = logging.getLogger("jarvis.brain.tools")

# ── Calendar context (injected by core.py) ──────────────────────

_calendar_integrations_cfg: dict = {}
_calendar_memory_store = None


def set_calendar_context(cfg: dict, store=None) -> None:
    """Inject integration config + memory store for calendar tools.

    Called once by core.py after startup.  ``cfg`` is the ``integrations``
    block from config.yaml; ``store`` is the MemoryStore instance.
    """
    global _calendar_integrations_cfg, _calendar_memory_store
    _calendar_integrations_cfg = cfg or {}
    _calendar_memory_store = store

# ── Constants ───────────────────────────────────────────────────

MAX_FILE_LINES = 500
MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB
MAX_OUTPUT_CHARS = 4000
DEFAULT_CODE_TIMEOUT = 10  # overridden by config

BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".flac", ".ogg", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".sqlite", ".db",
})


# ── web_search ──────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5, **_kwargs) -> str:
    """Search the web using duckduckgo-search and return structured results."""
    if not query or not query.strip():
        return "Error: empty search query."

    max_results = max(1, min(int(max_results), 10))

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return (
            "Error: duckduckgo-search is not installed. "
            "Run: pip install duckduckgo-search"
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        log.warning(f"web_search failed: {exc}")
        return f"Error: web search failed — {exc}"

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("href", "")
        snippet = r.get("body", "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


# ── read_file ───────────────────────────────────────────────────

def _is_path_allowed(resolved: Path, workspace_root: str | None) -> bool:
    """Check that resolved path is inside workspace or home-safe locations."""
    home = Path.home()
    allowed_roots = [home]
    if workspace_root:
        allowed_roots.insert(0, Path(workspace_root).resolve())

    # Block sensitive directories
    blocked = {
        home / ".ssh",
        home / ".gnupg",
        home / ".aws",
        home / ".config" / "gcloud",
        Path("/etc"),
        Path("/var"),
        Path("/private/etc"),
    }
    for b in blocked:
        try:
            resolved.relative_to(b)
            return False
        except ValueError:
            pass

    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 200,
    workspace_root: str | None = None,
    **_kwargs,
) -> str:
    """Read lines from a text file with safety checks."""
    if not path or not path.strip():
        return "Error: no file path provided."

    try:
        target = Path(path).expanduser().resolve()
    except Exception:
        return f"Error: invalid path '{path}'."

    if not target.exists():
        return f"Error: file not found — {target}"

    if not target.is_file():
        return f"Error: not a file — {target}"

    if target.suffix.lower() in BINARY_EXTENSIONS:
        return f"Error: binary file type '{target.suffix}' not supported."

    try:
        size = target.stat().st_size
    except OSError as exc:
        return f"Error: cannot stat file — {exc}"

    if size > MAX_FILE_SIZE_BYTES:
        return (
            f"Error: file too large ({size:,} bytes). "
            f"Max allowed: {MAX_FILE_SIZE_BYTES:,} bytes."
        )

    if not _is_path_allowed(target, workspace_root):
        return f"Error: access denied — path outside allowed directories."

    start_line = max(1, int(start_line))
    end_line = max(start_line, int(end_line))
    if end_line - start_line + 1 > MAX_FILE_LINES:
        end_line = start_line + MAX_FILE_LINES - 1

    try:
        with open(target, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        return f"Error: cannot read file — {exc}"

    total = len(lines)
    selected = lines[start_line - 1 : end_line]

    if not selected:
        return f"File has {total} lines; requested range {start_line}-{end_line} is empty."

    numbered = []
    for i, line in enumerate(selected, start_line):
        numbered.append(f"{i:>4} | {line.rstrip()}")

    header = f"[{target.name}] lines {start_line}-{min(end_line, total)} of {total}"
    body = "\n".join(numbered)
    result = f"{header}\n{body}"
    return result[:MAX_OUTPUT_CHARS]


# ── run_code ────────────────────────────────────────────────────

def run_code(
    code: str,
    language: str = "python",
    timeout: int = DEFAULT_CODE_TIMEOUT,
    **_kwargs,
) -> str:
    """Execute a code snippet in a subprocess with strict sandboxing."""
    if language != "python":
        return f"Error: unsupported language '{language}'. Only 'python' is supported."

    if not code or not code.strip():
        return "Error: empty code."

    code = textwrap.dedent(code)

    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_safe_env(),
        )
    except subprocess.TimeoutExpired:
        return f"Error: code execution timed out after {timeout}s."
    except Exception as exc:
        return f"Error: failed to run code — {exc}"

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    parts = []
    if stdout:
        parts.append(stdout[:MAX_OUTPUT_CHARS])
    if result.returncode != 0:
        parts.append(f"[exit code {result.returncode}]")
        if stderr:
            parts.append(stderr[:MAX_OUTPUT_CHARS // 2])
    elif stderr:
        # Warnings etc. on success
        parts.append(f"[stderr] {stderr[:MAX_OUTPUT_CHARS // 4]}")

    output = "\n".join(parts) if parts else "(no output)"
    return output


def _safe_env() -> dict:
    """Minimal environment for subprocess execution."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    # Propagate virtual-env so imports work
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        env["VIRTUAL_ENV"] = venv
        env["PATH"] = f"{venv}/bin:{env['PATH']}"
    return env


# ── calendar tools ──────────────────────────────────────────────

def _get_calendar_service():
    """Return a CalendarService instance using injected context, or None."""
    if not _calendar_memory_store:
        return None, "No calendar accounts are connected. Ask the user to connect a Google or Outlook account first."
    try:
        accounts = _calendar_memory_store.list_connected_accounts()
    except Exception as exc:
        return None, f"Error reading connected accounts: {exc}"
    if not accounts:
        return None, "No calendar accounts are connected. Ask the user to connect a Google or Outlook account first."
    try:
        from jarvis.integrations.calendar_service import CalendarService
        svc = CalendarService(_calendar_integrations_cfg, accounts)
        return svc, None
    except Exception as exc:
        return None, f"Calendar service unavailable: {exc}"


def _format_event_line(ev) -> str:
    """Return a single readable line for one CalendarEvent."""
    try:
        local_dt = ev.start_dt.astimezone()
    except Exception:
        local_dt = ev.start_dt
    if ev.is_all_day:
        time_str = "all day"
    else:
        time_str = local_dt.strftime("%I:%M %p").lstrip("0") or local_dt.strftime("%I:%M %p")
    parts = [f"- {ev.title} ({time_str})"]
    if ev.location:
        parts.append(f"  Location: {ev.location}")
    if ev.attendees_count:
        parts.append(f"  Attendees: {ev.attendees_count}")
    return "\n".join(parts)


def get_schedule(date: str = "today", **_kwargs) -> str:
    """Return today's calendar events (or a specified date) as plain text."""
    svc, err = _get_calendar_service()
    if err:
        return err

    try:
        if date and date.lower() not in ("today", ""):
            # Parse an explicit date like "2026-05-15" or "tomorrow"
            from datetime import datetime, timedelta
            if date.lower() == "tomorrow":
                ref = datetime.now() + timedelta(days=1)
            else:
                try:
                    from dateutil import parser as _dp
                    ref = _dp.parse(date)
                except Exception:
                    ref = None
            events = svc.get_todays_schedule(user_tz=None) if ref is None else svc.get_todays_schedule()
        else:
            events = svc.get_todays_schedule()
    except Exception as exc:
        log.error("get_schedule tool error: %s", exc)
        return f"Error fetching calendar: {exc}"

    if not events:
        return "No events scheduled for today."

    lines = [f"You have {len(events)} event{'s' if len(events) != 1 else ''} today:"]
    for ev in events:
        lines.append(_format_event_line(ev))
    return "\n".join(lines)


def get_next_event(hours: int = 24, **_kwargs) -> str:
    """Return the next upcoming calendar event within the given number of hours."""
    hours = max(1, min(int(hours), 168))  # cap at 1 week
    svc, err = _get_calendar_service()
    if err:
        return err

    try:
        upcoming = svc.get_upcoming_events(hours=hours, limit=1)
    except Exception as exc:
        log.error("get_next_event tool error: %s", exc)
        return f"Error fetching next event: {exc}"

    if not upcoming:
        return f"No events in the next {hours} hours."

    ev = upcoming[0]
    return _format_event_line(ev)


# ── browser_action ──────────────────────────────────────────────

def browser_action(
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    query: str = "",
    **_kwargs,
) -> str:
    """Control a real browser via Playwright to complete multi-step web tasks.

    Delegates to ``jarvis.actions.browser.browser_action`` which owns the
    live browser session.
    """
    from jarvis.actions.browser import browser_action as _ba
    return _ba(action=action, url=url, selector=selector, text=text, query=query)


# ── run_command (shell, with approval gate) ─────────────────────

def run_command(command: str, reason: str = "", **_kwargs) -> str:
    """LLM tool: request execution of a shell command — always requires approval.

    Returns the APPROVAL_PREFIX sentinel so core.py can gate on user consent.
    The pending action is stored in exec_commands and will be executed when the
    user says "confirm".
    """
    from jarvis.actions.exec_commands import run_terminal_command, APPROVAL_PREFIX

    result = run_terminal_command(command)
    if result.startswith(APPROVAL_PREFIX):
        prompt = result[len(APPROVAL_PREFIX):]
        # Return a message the LLM can relay to the user
        return (
            f"PENDING_APPROVAL — {prompt} "
            f"{'Reason: ' + reason if reason else ''}"
        ).strip()
    # Blocked by safety check — return the refusal message directly
    return result


# ── smart_home_control ──────────────────────────────────────────

# Context injected by core.py
_smarthome_cfg: dict = {}


def set_smarthome_context(cfg: dict) -> None:
    """Inject smart home config so the LLM tool can delegate to the action layer."""
    global _smarthome_cfg
    _smarthome_cfg = cfg or {}


def smart_home_control(
    action: str,
    entity: str = "",
    brightness: int | None = None,
    color: str = "",
    temperature: float | None = None,
    device_type: str | None = None,
    **_kwargs,
) -> str:
    """LLM tool: control smart home devices (lights, plugs, thermostats)."""
    from jarvis.actions import smarthome as sh

    action = action.strip().lower()

    if action == "turn_on_light":
        if not entity:
            return "Error: 'entity' is required for turn_on_light."
        return sh.turn_on_light(
            entity,
            brightness=brightness,
            color=color or None,
        )
    elif action == "turn_off_light":
        if not entity:
            return "Error: 'entity' is required for turn_off_light."
        return sh.turn_off_light(entity)
    elif action == "set_brightness":
        if not entity:
            return "Error: 'entity' is required for set_brightness."
        if brightness is None:
            return "Error: 'brightness' (0-100) is required for set_brightness."
        return sh.set_brightness(entity, brightness)
    elif action == "set_color":
        if not entity:
            return "Error: 'entity' is required for set_color."
        if not color:
            return "Error: 'color' is required for set_color."
        return sh.set_color(entity, color)
    elif action == "turn_on_plug":
        if not entity:
            return "Error: 'entity' is required for turn_on_plug."
        return sh.turn_on_plug(entity)
    elif action == "turn_off_plug":
        if not entity:
            return "Error: 'entity' is required for turn_off_plug."
        return sh.turn_off_plug(entity)
    elif action == "set_temperature":
        if temperature is None:
            return "Error: 'temperature' is required for set_temperature."
        return sh.set_temperature(
            temperature=str(temperature),
            entity=entity or "thermostat",
        )
    elif action == "get_temperature":
        return sh.get_temperature(entity=entity or "thermostat")
    elif action == "get_state":
        if not entity:
            return "Error: 'entity' is required for get_state."
        return sh.get_device_state(entity)
    elif action == "list_devices":
        return sh.list_devices(device_type=device_type or None)
    else:
        return f"Error: unknown smart_home action '{action}'."

