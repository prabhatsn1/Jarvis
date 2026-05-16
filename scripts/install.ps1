Write-Host "======================================="
Write-Host "  JARVIS v1 - Installation (Windows)"
Write-Host "======================================="
Write-Host ""

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

# -- Python -------------------------------------------
Write-Host "[1/3] Checking Python..."
try {
    python --version
} catch {
    Write-Host "ERROR: Python 3.10+ required. Install from https://python.org"
    exit 1
}

Write-Host "[2/3] Setting up virtual environment..."
python -m venv .venv
& .venv\Scripts\Activate.ps1
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pywin32 -q
Write-Host "  + Python dependencies installed"

# -- Config -------------------------------------------
$jarvisDir = "$env:USERPROFILE\.jarvis"
if (-not (Test-Path $jarvisDir)) {
    New-Item -ItemType Directory -Path $jarvisDir -Force | Out-Null
}

# -- HUD (WPF) ---------------------------------------
Write-Host "[3/3] Building HUD..."
try {
    Set-Location hud-win
    dotnet build -c Release 2>&1 | Select-Object -Last 1
    Set-Location ..
    Write-Host "  + HUD built"
} catch {
    Write-Host "  ! HUD build failed - install .NET 8 SDK from https://dotnet.microsoft.com"
    Set-Location $ProjectDir
}

Write-Host ""
Write-Host "======================================="
Write-Host "  Installation complete."
Write-Host "======================================="
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Run:  .\scripts\start.ps1"
Write-Host "     (wake word detection works out of the box - no API key needed)"
Write-Host ""
Write-Host "  Optional - Calendar & Email integration:"
Write-Host "  2. Fill in config.yaml under 'integrations':"
Write-Host "       integrations.google.client_id / client_secret"
Write-Host "       integrations.microsoft.client_id / client_secret"
Write-Host "     (see README.md for step-by-step OAuth credential creation)"
Write-Host ""
Write-Host "  3. Start Jarvis, then say:"
Write-Host "       'Connect Google account'   <- opens browser for Google sign-in"
Write-Host "       'Connect Outlook account'  <- opens browser for Microsoft sign-in"
Write-Host "     Tokens are stored in Windows Credential Manager automatically."
Write-Host ""
Write-Host "  4. Ask: 'What is on my schedule today'"
Write-Host ""
