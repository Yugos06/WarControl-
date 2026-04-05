$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $env:APPDATA "WarControl"
$runtimeLogs = Join-Path $root "runtime-logs"
$stopScript = Join-Path $root "scripts\stop-warcontrol.ps1"

if (Test-Path $stopScript) {
    & powershell.exe -ExecutionPolicy Bypass -File $stopScript | Out-Null
    Start-Sleep -Milliseconds 800
}

$targets = @(
    (Join-Path $stateDir "warcontrol.db"),
    (Join-Path $stateDir "warcontrol.db-journal"),
    (Join-Path $stateDir "outbox.jsonl"),
    (Join-Path $stateDir "proxy-outbox.jsonl"),
    (Join-Path $root "runtime-logs\proxy-raw.log"),
    (Join-Path $root "runtime-logs\proxy-packets.log")
)

foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $runtimeLogs) {
    Get-ChildItem -LiteralPath $runtimeLogs -File -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "WarControl local data cleared."
