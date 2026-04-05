param(
    [string]$ApiKey = "change-me",
    [string]$Server = "NationGlory",
    [string]$Source = $env:USERNAME,
    [string]$Edition = "auto",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$apiVenvPython = Join-Path $root "api\.venv\Scripts\python.exe"
$npmCmd = "C:\Program Files\nodejs\npm.cmd"
$dbDir = Join-Path $env:APPDATA "WarControl"
$dbPath = Join-Path $dbDir "warcontrol.db"
$logDir = Join-Path $root "runtime-logs"

New-Item -ItemType Directory -Force -Path $dbDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $npmCmd)) {
    throw "npm introuvable: $npmCmd. Installe Node.js depuis https://nodejs.org"
}

if (-not (Test-Path $apiVenvPython)) {
    Write-Host "Venv Python absent, creation en cours..."
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) { throw "Python introuvable. Installe Python 3.11+ et relance." }
    & $pythonExe -m venv (Join-Path $root "api\.venv")
    & (Join-Path $root "api\.venv\Scripts\pip.exe") install -r (Join-Path $root "api\requirements.txt") --quiet
    Write-Host "Venv cree."
}

$apiCommand = @"
Set-Location '$root'
`$env:WARCONTROL_DB_PATH='$dbPath'
`$env:WARCONTROL_INGEST_KEY='$ApiKey'
& '$apiVenvPython' -m uvicorn api.main:app --host 127.0.0.1 --port 8000
"@

$webCommand = @"
Set-Location '$root\web'
`$env:Path='C:\Program Files\nodejs;' + `$env:Path
`$env:NEXT_PUBLIC_API_URL='http://127.0.0.1:8000'
& '$npmCmd' run dev -- --hostname 127.0.0.1 --port 3000
"@

$collectorArgs = @(
    "collector\agent.py",
    "--edition", $Edition,
    "--api-url", "http://127.0.0.1:8000",
    "--api-key", $ApiKey,
    "--server", $Server,
    "--source", $Source
)

if ($LogPath) {
    $collectorArgs += @("--log-path", $LogPath)
}

$collectorArgString = (($collectorArgs | ForEach-Object {
    if ($_ -match "\s") { '"' + $_ + '"' } else { $_ }
}) -join " ")

$collectorCommand = "Set-Location '$root'; & '$apiVenvPython' $collectorArgString"

# Vérifier si le fichier log Minecraft existe et avertir si absent
$logCandidates = @(
    "$env:APPDATA\.minecraft\logs\latest.log",
    "$env:APPDATA\Minecraft Bedrock\logs\latest.log",
    "$env:LOCALAPPDATA\Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\logs\latest.log"
)
if ($LogPath) {
    $expectedLog = $LogPath
} else {
    $expectedLog = $logCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $expectedLog) { $expectedLog = $logCandidates[0] }
}
if (-not (Test-Path $expectedLog)) {
    Write-Host ""
    Write-Host "  [!] Log Minecraft absent : $expectedLog" -ForegroundColor Yellow
    Write-Host "      Rejoins NationsGlory en jeu — le collector demarrera automatiquement." -ForegroundColor Yellow
    Write-Host "      (Mode demo disponible : python collector\agent.py --demo)" -ForegroundColor DarkYellow
    Write-Host ""
}

Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", $apiCommand `
    -RedirectStandardOutput (Join-Path $logDir "api.log") `
    -RedirectStandardError (Join-Path $logDir "api.err.log")

Start-Sleep -Seconds 2

Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", $webCommand `
    -RedirectStandardOutput (Join-Path $logDir "web.log") `
    -RedirectStandardError (Join-Path $logDir "web.err.log")

Start-Sleep -Seconds 2

Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", $collectorCommand `
    -RedirectStandardOutput (Join-Path $logDir "collector.log") `
    -RedirectStandardError (Join-Path $logDir "collector.err.log")

Write-Host "WarControl lance."
Write-Host "API: http://127.0.0.1:8000/health"
Write-Host "Dashboard: http://127.0.0.1:3000"
Write-Host "Logs: $logDir"
