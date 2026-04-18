Write-Host "======================================="
Write-Host "  JARVIS v1 - Starting up (Windows)"
Write-Host "======================================="
Write-Host ""

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir
& .venv\Scripts\Activate.ps1

# -- Start Python core --------------------------------
$core = Start-Process -FilePath "python" -ArgumentList "-m jarvis" `
    -NoNewWindow -PassThru
Write-Host "  Core started (PID: $($core.Id))"

# -- Start HUD (WPF) ----------------------------------
$hudExe = "hud-win\bin\Release\net8.0-windows\JarvisHUD.exe"
$hudProc = $null
if (Test-Path $hudExe) {
    Start-Sleep -Seconds 1  # Let core open pipe
    $hudProc = Start-Process -FilePath $hudExe -PassThru
    Write-Host "  HUD started (PID: $($hudProc.Id))"
} else {
    Write-Host "  HUD not built - run .\scripts\install.ps1 first"
}

Write-Host ""
Write-Host "  Press Ctrl+C to stop."
Write-Host ""

# -- Graceful shutdown ---------------------------------
try {
    $core.WaitForExit()
} finally {
    Write-Host ""
    Write-Host "  Shutting down JARVIS..."
    if (-not $core.HasExited) { $core.Kill() }
    if ($hudProc -and -not $hudProc.HasExited) { $hudProc.Kill() }
    Write-Host "  Goodbye."
}
