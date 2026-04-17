#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
source .venv/bin/activate

echo "═══════════════════════════════════════"
echo "  JARVIS v1 — Starting up"
echo "═══════════════════════════════════════"
echo ""

# ── Start Python core ──────────────────────
python -m jarvis &
JARVIS_PID=$!

# ── Start HUD (macOS) ──────────────────────
HUD_PID=""
if [[ "$(uname)" == "Darwin" ]]; then
    HUD_BIN="hud/.build/release/JarvisHUD"
    if [[ -f "$HUD_BIN" ]]; then
        sleep 1  # Let core start and open socket
        "$HUD_BIN" &
        HUD_PID=$!
        echo "  HUD started (PID: $HUD_PID)"
    else
        echo "  HUD not built — run ./scripts/install.sh first"
    fi
fi

echo "  Core started (PID: $JARVIS_PID)"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# ── Graceful shutdown ──────────────────────
cleanup() {
    echo ""
    echo "  Shutting down JARVIS..."
    kill "$JARVIS_PID" 2>/dev/null || true
    [[ -n "$HUD_PID" ]] && kill "$HUD_PID" 2>/dev/null || true
    wait "$JARVIS_PID" 2>/dev/null || true
    echo "  Goodbye."
    exit 0
}

trap cleanup SIGINT SIGTERM

wait "$JARVIS_PID"
