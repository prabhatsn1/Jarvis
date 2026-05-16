"""On-demand terminal command and Python script execution with approval gate.

Flow
────
1.  User (or LLM tool) requests a command / script.
2.  ``run_terminal_command`` / ``run_python_script`` validate the request,
    store a *pending action*, and return the ``APPROVAL_PREFIX`` sentinel so
    core.py knows it must ask the user for confirmation.
3.  core.py speaks the approval prompt, sets ``_awaiting_approval = True``,
    and loops back to listen for "confirm" or "cancel".
4.  On "confirm", core.py calls ``execute_pending()`` which runs the stored
    callable and returns the output string.
5.  On "cancel" (or timeout), core.py calls ``cancel_pending()``.

Safety
──────
A hard-coded blocklist rejects commands that could cause irreversible system
damage (disk wipes, fork bombs, etc.) even if the user says "confirm".
Separate config knobs let the operator tighten or loosen the allowed working
directory, timeout, and max-output length.

Config (config.yaml):
    exec_commands:
      enabled: true
      timeout_sec: 30
      max_output_chars: 2000
      working_dir: ""          # "" = current working directory
      allowed_dir: "~"         # restrict scripts to this subtree
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("jarvis.actions.exec_commands")

APPROVAL_PREFIX = "__APPROVAL_REQUIRED__:"
SYSTEM = platform.system()

# ── Approval-word helpers (also imported by core.py) ─────────────────────────

_CONFIRM_WORDS = frozenset({
    "confirm", "yes", "yeah", "yep", "sure", "go ahead",
    "proceed", "do it", "run it", "execute", "ok", "okay",
    "affirmative", "approved", "approve", "go for it",
})
_REJECT_WORDS = frozenset({
    "cancel", "no", "nope", "nah", "stop", "abort",
    "don't", "do not", "negative", "reject", "deny",
    "never mind", "nevermind", "forget it", "skip it",
})


def _is_confirmation(text: str) -> bool:
    return text in _CONFIRM_WORDS or any(w in text.split() for w in _CONFIRM_WORDS)


def _is_rejection(text: str) -> bool:
    return text in _REJECT_WORDS or any(w in text.split() for w in _REJECT_WORDS)

# ── Dangerous-pattern blocklist ───────────────────────────────────────────────

_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brm\s+(-[^\s]*f[^\s]*\s+)?/",     # rm targeting root paths
        r"\brm\s+.*-[rR][fF]",                # rm -rf / rm -fr
        r"\bdd\s+.*of=/dev/",                 # dd to raw disk
        r"\bmkfs\b",                          # format filesystem
        r":\(\)\s*\{.*:\s*\|",               # fork bomb :(){ :|:& };:
        r"\bchown\b.*/",                      # chown on root paths
        r">\s*/dev/sd[a-z]",                  # write to block device
        r"\bwipe\b",                          # wipe utility
        r"curl\s+.+\|\s*(ba)?sh",             # curl | sh
        r"wget\s+.+\|\s*(ba)?sh",             # wget | sh
        r"\bpython[23]?\s+-c\s+.*(exec|eval|__import__)",  # code injection
        # Windows-specific
        r"\bformat\s+[a-zA-Z]:",              # format C:
        r"\bdel\s+/[fFsS]",                   # del /f /s
        r"\brd\s+/s\s+/q\s+[cC]:",           # rd /s /q C:
        r"Remove-Item\s+-Recurse\s+-Force\s+[cC]:",
    ]
]


def _is_blocked(command: str) -> bool:
    return any(p.search(command) for p in _BLOCKED_PATTERNS)


# ── Config (injected by core.py) ──────────────────────────────────────────────

_cfg: dict = {}


def set_exec_context(cfg: dict) -> None:
    global _cfg
    _cfg = cfg or {}


def _timeout() -> int:
    return int(_cfg.get("timeout_sec", 30))


def _max_chars() -> int:
    return int(_cfg.get("max_output_chars", 2000))


def _working_dir() -> str | None:
    wd = _cfg.get("working_dir", "")
    if wd:
        return str(Path(wd).expanduser().resolve())
    return None


def _allowed_dir() -> Path:
    d = _cfg.get("allowed_dir", "~")
    return Path(d).expanduser().resolve()


# ── Pending-approval store (thread-safe) ──────────────────────────────────────

_pending_lock = threading.Lock()
_pending_action: dict | None = None   # {"description": str, "run": callable}


def _set_pending(description: str, run_fn) -> None:
    global _pending_action
    with _pending_lock:
        _pending_action = {"description": description, "run": run_fn}


def has_pending() -> bool:
    with _pending_lock:
        return _pending_action is not None


def execute_pending() -> str:
    """Run and clear the pending action; return its output or an error."""
    global _pending_action
    with _pending_lock:
        if _pending_action is None:
            return "No pending command to execute."
        fn = _pending_action["run"]
        _pending_action = None

    try:
        return fn()
    except Exception as exc:
        log.error("execute_pending error: %s", exc)
        return f"Command failed: {exc}"


def cancel_pending() -> str:
    global _pending_action
    with _pending_lock:
        _pending_action = None
    return "Command cancelled."


# ── Output helpers ────────────────────────────────────────────────────────────

def _format_output(stdout: str, stderr: str, returncode: int) -> str:
    """Return a voice-friendly summary of subprocess output."""
    max_c = _max_chars()
    parts: list[str] = []

    if stdout.strip():
        lines = stdout.strip().splitlines()
        preview = "\n".join(lines[:20])
        truncated = len(lines) > 20
        parts.append(preview[:max_c])
        if truncated:
            parts.append(f"… ({len(lines)} lines total, showing first 20)")
    if returncode != 0:
        parts.append(f"[exit code {returncode}]")
        if stderr.strip():
            parts.append(stderr.strip()[:max_c // 2])
    elif stderr.strip():
        parts.append(f"[stderr] {stderr.strip()[:max_c // 4]}")

    return "\n".join(parts) if parts else "(no output)"


# ── Low-level runners ─────────────────────────────────────────────────────────

def _run_shell(command: str) -> str:
    """Execute *command* in a shell subprocess and return formatted output."""
    log.info("Running shell command: %s", command)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_timeout(),
            cwd=_working_dir(),
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {_timeout()} seconds."
    except Exception as exc:
        return f"Failed to run command: {exc}"

    return _format_output(result.stdout, result.stderr, result.returncode)


def _run_script(script_path: Path, args: list[str]) -> str:
    """Execute a Python script in a subprocess and return formatted output."""
    log.info("Running Python script: %s %s", script_path, args)
    cmd = [sys.executable, str(script_path)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_timeout(),
            cwd=_working_dir() or str(script_path.parent),
            env={**os.environ},  # pass full env so the script works normally
        )
    except subprocess.TimeoutExpired:
        return f"Script timed out after {_timeout()} seconds."
    except Exception as exc:
        return f"Failed to run script: {exc}"

    return _format_output(result.stdout, result.stderr, result.returncode)


# ── Public action functions ───────────────────────────────────────────────────

def run_terminal_command(command: str) -> str:
    """Request approval to run a shell command, then execute on confirmation."""
    if not _cfg.get("enabled", True):
        return "Command execution is disabled, Boss."

    command = command.strip()
    if not command:
        return "Please provide a command to run, Boss."

    if _is_blocked(command):
        log.warning("Blocked dangerous command: %s", command)
        return (
            f"I won't run that command, Boss — it matches a dangerous pattern. "
            f"Command: {command}"
        )

    _set_pending(
        description=command,
        run_fn=lambda: _run_shell(command),
    )

    return (
        f"{APPROVAL_PREFIX}"
        f"I'm about to run this terminal command: {command}. "
        f"Say confirm to proceed, or cancel to abort."
    )


def run_python_script(path: str, args: str = "") -> str:
    """Request approval to run a Python script file."""
    if not _cfg.get("enabled", True):
        return "Command execution is disabled, Boss."

    path = path.strip()
    if not path:
        return "Please provide a script path, Boss."

    script = Path(path).expanduser().resolve()

    if script.suffix.lower() != ".py":
        return f"Only Python (.py) scripts are supported, Boss. Got: {script.name}"

    if not script.exists():
        return f"Script not found: {script}"

    if not script.is_file():
        return f"That path is not a file: {script}"

    # Restrict to allowed directory
    allowed = _allowed_dir()
    try:
        script.relative_to(allowed)
    except ValueError:
        return (
            f"Script is outside the allowed directory ({allowed}), Boss. "
            f"Adjust exec_commands.allowed_dir in config.yaml to permit it."
        )

    arg_list = args.split() if args.strip() else []

    _set_pending(
        description=f"{script.name} {args}".strip(),
        run_fn=lambda: _run_script(script, arg_list),
    )

    display = str(script)
    if args.strip():
        display += f" {args}"
    return (
        f"{APPROVAL_PREFIX}"
        f"I'm about to run the script: {display}. "
        f"Say confirm to proceed, or cancel to abort."
    )
