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
Write-Host "     (wake word detection works out of the box — no API key needed)"
Write-Host ""
