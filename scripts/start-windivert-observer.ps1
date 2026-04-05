$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $env:APPDATA "WarControl"
$logDir = Join-Path $root "runtime-logs"
$venvPython = Join-Path $root "api\.venv\Scripts\python.exe"
$scriptPath = Join-Path $root "proxy\windivert_redirect.py"
$pidPath = Join-Path $stateDir "windivert.pid"

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $venvPython)) {
    throw "Python venv introuvable: $venvPython"
}

$process = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", "& '$venvPython' -u '$scriptPath' --mode observe" `
    -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "windivert.out.log") `
    -RedirectStandardError (Join-Path $logDir "windivert.err.log")

Set-Content -LiteralPath $pidPath -Value $process.Id -NoNewline
Write-Host "WinDivert observer launched."
