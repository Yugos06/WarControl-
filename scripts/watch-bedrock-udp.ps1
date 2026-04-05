$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "runtime-logs"
$stateDir = Join-Path $env:APPDATA "WarControl"
$pidPath = Join-Path $stateDir "bedrock-watch.pid"
$logPath = Join-Path $logDir "bedrock-udp.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$selfPid = $PID
Set-Content -LiteralPath $pidPath -Value $selfPid -NoNewline

function Write-WatchLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "$timestamp $Message"
}

function Get-MinecraftProcess {
    Get-Process -Name "Minecraft.Windows" -ErrorAction SilentlyContinue | Select-Object -First 1
}

$lastSignature = ""
Write-WatchLog "watcher_started"

while ($true) {
    $process = Get-MinecraftProcess
    if (-not $process) {
        if ($lastSignature -ne "missing") {
            Write-WatchLog "minecraft_process_missing"
            $lastSignature = "missing"
        }
        Start-Sleep -Milliseconds 700
        continue
    }

    $udpRows = netstat -ano -p udp | Select-String -Pattern "\s+$($process.Id)\s*$" | ForEach-Object {
        ($_ -replace '^\s*UDP\s+', '') -replace '\s+', ' '
    }
    $signature = ($udpRows | Sort-Object) -join "|"

    if (-not $signature) {
        $signature = "pid=$($process.Id):no-udp"
    }

    if ($signature -ne $lastSignature) {
        Write-WatchLog "minecraft_pid=$($process.Id)"
        foreach ($row in $udpRows) {
            Write-WatchLog "udp $row"
        }
        if (-not $udpRows) {
            Write-WatchLog "udp none"
        }
        $lastSignature = $signature
    }

    Start-Sleep -Milliseconds 700
}
