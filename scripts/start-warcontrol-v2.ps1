param(
    [string]$ApiKey = "",
    [string]$Server = "NationGlory",
    [string]$Source = $env:USERNAME,
    [string]$Edition = "auto",
    [string]$LogPath = "",
    [ValidateSet("live", "demo")]
    [string]$Mode = "",
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "warcontrol.config.json"
$exampleConfigPath = Join-Path $root "warcontrol.config.json.example"
$apiVenvPython = Join-Path $root "api\.venv\Scripts\python.exe"
$npmCmd = "C:\Program Files\nodejs\npm.cmd"
$stateDir = Join-Path $env:APPDATA "WarControl"
$dbPath = Join-Path $stateDir "warcontrol.db"
$logDir = Join-Path $root "runtime-logs"
$keyPath = Join-Path $stateDir "launcher.key"
$dashboardUrl = "http://127.0.0.1:3000"
$apiUrl = "http://127.0.0.1:8000"

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $configPath) -and (Test-Path $exampleConfigPath)) {
    Copy-Item -LiteralPath $exampleConfigPath -Destination $configPath
}

$config = $null
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
}

if ($config) {
    if (-not $PSBoundParameters.ContainsKey("Server") -and $config.server) {
        $Server = [string]$config.server
    }
    if (-not $PSBoundParameters.ContainsKey("Source") -and $config.source) {
        $Source = [string]$config.source
    }
    if (-not $PSBoundParameters.ContainsKey("Edition") -and $config.edition) {
        $Edition = [string]$config.edition
    }
    if (-not $PSBoundParameters.ContainsKey("LogPath") -and $config.logPath) {
        $LogPath = [string]$config.logPath
    }
    if (-not $PSBoundParameters.ContainsKey("Mode") -and $config.mode) {
        $Mode = [string]$config.mode
    }
    if (-not $PSBoundParameters.ContainsKey("OpenBrowser") -and $null -ne $config.openBrowser) {
        $OpenBrowser = [bool]$config.openBrowser
    }
    if ($config.dashboardUrl) {
        $dashboardUrl = [string]$config.dashboardUrl
    }
    if ($config.apiUrl) {
        $apiUrl = [string]$config.apiUrl
    }
}

if (-not $Mode) {
    $Mode = "live"
}

if (-not $ApiKey) {
    if (Test-Path $keyPath) {
        $ApiKey = (Get-Content $keyPath -Raw).Trim()
    }
    if (-not $ApiKey) {
        $ApiKey = [guid]::NewGuid().ToString("N")
        Set-Content -LiteralPath $keyPath -Value $ApiKey -NoNewline
    }
}

if (-not (Test-Path $npmCmd)) {
    throw "npm introuvable: $npmCmd. Installe Node.js depuis https://nodejs.org"
}

if (-not (Test-Path $apiVenvPython)) {
    Write-Host "Venv Python absent, creation en cours..."
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        throw "Python introuvable. Installe Python 3.11+ et relance."
    }
    & $pythonExe -m venv (Join-Path $root "api\.venv")
    & (Join-Path $root "api\.venv\Scripts\pip.exe") install -r (Join-Path $root "api\requirements.txt") --quiet
    Write-Host "Venv cree."
}

$apiCommand = @"
Set-Location '$root'
`$env:WARCONTROL_DB_PATH='$dbPath'
`$env:WARCONTROL_INGEST_KEY='$ApiKey'
`$env:WARCONTROL_WEB_ORIGINS='*'
& '$apiVenvPython' -m uvicorn api.main:app --host 127.0.0.1 --port 8000
"@

$webCommand = @"
Set-Location '$root\web'
`$env:Path='C:\Program Files\nodejs;' + `$env:Path
`$env:NEXT_PUBLIC_API_URL='$apiUrl'
& '$npmCmd' run dev -- --hostname 127.0.0.1 --port 3000
"@

if ($Mode -eq "demo") {
    $collectorArgs = @(
        "collector\agent.py",
        "--demo",
        "--api-url", $apiUrl,
        "--api-key", $ApiKey,
        "--server", $Server,
        "--source", $Source
    )
} else {
    $collectorArgs = @(
        "collector\agent.py",
        "--edition", $Edition,
        "--api-url", $apiUrl,
        "--api-key", $ApiKey,
        "--server", $Server,
        "--source", $Source
    )
}

if ($LogPath) {
    $collectorArgs += @("--log-path", $LogPath)
}

$collectorArgString = (($collectorArgs | ForEach-Object {
    if ($_ -match "\s") { '"' + $_ + '"' } else { $_ }
}) -join " ")

$collectorCommand = "Set-Location '$root'; & '$apiVenvPython' $collectorArgString"

$logCandidates = @(
    "$env:APPDATA\.minecraft\logs\latest.log",
    "$env:APPDATA\Minecraft Bedrock\logs\latest.log",
    "$env:LOCALAPPDATA\Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\logs\latest.log"
)

if ($LogPath) {
    $expectedLog = $LogPath
} else {
    $expectedLog = $logCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $expectedLog) {
        $expectedLog = $logCandidates[0]
    }
}

if ($Mode -eq "live" -and -not (Test-Path $expectedLog)) {
    Write-Host ""
    Write-Host "  [!] Log Minecraft absent : $expectedLog" -ForegroundColor Yellow
    Write-Host "      Rejoins NationsGlory en jeu - le collector demarrera automatiquement." -ForegroundColor Yellow
    Write-Host "      (Mode demo disponible : modifie warcontrol.config.json ou lance --Mode demo)" -ForegroundColor DarkYellow
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

if ($OpenBrowser) {
    Start-Sleep -Seconds 2
    Start-Process $dashboardUrl | Out-Null
}

Write-Host "WarControl lance."
Write-Host "Mode: $Mode"
Write-Host "API: $apiUrl/health"
Write-Host "Dashboard: $dashboardUrl"
Write-Host "Logs: $logDir"
Write-Host "Config: $configPath"
