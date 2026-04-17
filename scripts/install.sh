#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "═══════════════════════════════════════"
echo "  JARVIS v1 — Installation"
echo "═══════════════════════════════════════"
echo ""

# ── Python ──────────────────────────────────
echo "[1/3] Checking Python..."
python3 --version || { echo "ERROR: Python 3.9+ required."; exit 1; }

echo "[2/3] Setting up virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Python dependencies installed"

# ── Config ──────────────────────────────────
mkdir -p ~/.jarvis

# ── HUD (macOS only) ───────────────────────
if [[ "$(uname)" == "Darwin" ]]; then
    echo "[3/3] Building HUD..."
    cd hud
    swift build -c release 2>&1 | tail -1
    cd ..
    echo "  ✓ HUD built"
else
    echo "[3/3] Skipping HUD (macOS only)"
fi

echo ""
echo "═══════════════════════════════════════"
echo "  Installation complete."
echo "═══════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Get a free Porcupine key at: https://console.picovoice.ai"
echo "  2. Add it to config.yaml → wake.porcupine_access_key"
echo "     (or skip and use keyboard mode — press Enter to wake)"
echo "  3. Run:  ./scripts/start.sh"
echo ""
