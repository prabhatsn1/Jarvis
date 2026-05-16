"""Screenshot capture and GPT-4 Vision screen analysis.

Captures the current screen, encodes it to base64, and sends it to the
OpenAI GPT-4 Vision API.  The result is returned as a spoken-friendly string.

Actions registered in commands.yaml:
  - vision.describe_screen        "what's on my screen"
  - vision.analyze_screen         "analyze my screen / {question}"

Config section (config.yaml)::

    vision:
      enabled: true
      model: "gpt-4o"          # any OpenAI vision-capable model
      max_tokens: 300
      detail: "auto"           # "auto" | "low" | "high"
      screenshot_dir: "/tmp"   # directory for transient screenshots

The OpenAI client is shared with the llm config block — the same
``openai_api_key`` / ``OPENAI_API_KEY`` env var is used.
"""

from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("jarvis.actions.vision")

SYSTEM = platform.system()

# ── Runtime context (injected by core.py) ────────────────────────────────────

_cfg: dict = {}
_llm_cfg: dict = {}   # the llm config block (carries the API key)


def set_vision_context(cfg: dict, llm_cfg: dict | None = None) -> None:
    """Inject config from core.py at startup."""
    global _cfg, _llm_cfg
    _cfg = cfg or {}
    _llm_cfg = llm_cfg or {}


def _is_enabled() -> bool:
    return _cfg.get("enabled", False)


# ── Screenshot capture ────────────────────────────────────────────────────────

def capture_screenshot() -> str:
    """Capture the full screen and return the path to the saved PNG file.

    Returns the path string or raises RuntimeError on failure.
    """
    screenshot_dir = _cfg.get("screenshot_dir", tempfile.gettempdir())
    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(screenshot_dir) / "jarvis_screen.png")

    if SYSTEM == "Darwin":
        result = subprocess.run(
            ["screencapture", "-x", path],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"screencapture failed: {result.stderr.decode().strip()}"
            )
    elif SYSTEM == "Windows":
        # Use PowerShell with .NET to grab the screen
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height); "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size); "
            f"$bmp.Save('{path}'); "
            "$g.Dispose(); $bmp.Dispose()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"PowerShell screenshot failed: {result.stderr.decode().strip()}"
            )
    else:
        # Linux fallback: try scrot or gnome-screenshot
        for cmd in [["scrot", path], ["gnome-screenshot", "-f", path]]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if result.returncode == 0:
                    break
            except FileNotFoundError:
                continue
        else:
            raise RuntimeError(
                "No screenshot tool found on Linux. "
                "Install scrot: sudo apt install scrot"
            )

    log.info("Screenshot saved to: %s", path)
    return path


# ── Vision API call ───────────────────────────────────────────────────────────

def _build_openai_client():
    """Build an OpenAI client using the llm config or OPENAI_API_KEY env var."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai is not installed. Run: pip install openai"
        )

    api_key = (
        _llm_cfg.get("openai_api_key")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "No OpenAI API key found. Set openai_api_key in config.yaml "
            "under the llm section, or export OPENAI_API_KEY."
        )
    return OpenAI(api_key=api_key)


def query_vision(image_path: str, question: str = "") -> str:
    """Send a screenshot to GPT-4 Vision and return a spoken-friendly response.

    Parameters
    ----------
    image_path:
        Absolute path to a PNG/JPEG screenshot file.
    question:
        Optional follow-up question about the screen.
    """
    model = _cfg.get("model", "gpt-4o")
    max_tokens = int(_cfg.get("max_tokens", 300))
    detail = _cfg.get("detail", "auto")

    # Encode image as base64
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    user_text = (
        question.strip()
        if question.strip()
        else "Describe what is currently on this screen in 1-2 concise sentences."
    )

    client = _build_openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}",
                                "detail": detail,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        answer = response.choices[0].message.content.strip()
        log.info("Vision response: %s", answer[:120])
        return answer
    except Exception as exc:
        log.error("GPT-4 Vision query failed: %s", exc)
        raise


# ── Public action functions ───────────────────────────────────────────────────

def describe_screen() -> str:
    """Take a screenshot and describe what's on screen. No question needed."""
    if not _is_enabled():
        return "Screen vision is disabled. Enable it in config.yaml under the vision section."
    try:
        path = capture_screenshot()
        return query_vision(path)
    except ImportError as exc:
        return str(exc)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        log.error("describe_screen failed: %s", exc)
        return "I couldn't capture or analyse the screen."


def analyze_screen(question: str = "") -> str:
    """Take a screenshot and answer a specific question about it."""
    if not _is_enabled():
        return "Screen vision is disabled. Enable it in config.yaml under the vision section."
    try:
        path = capture_screenshot()
        return query_vision(path, question=question)
    except ImportError as exc:
        return str(exc)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        log.error("analyze_screen failed: %s", exc)
        return "I couldn't capture or analyse the screen."
