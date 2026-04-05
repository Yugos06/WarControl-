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
$stopScript = Join-Path $root "scripts\stop-warcontrol.ps1"
$proxyScript = Join-Path $root "proxy\proxy.py"
$watchScript = Join-Path $root "scripts\watch-bedrock-udp.ps1"
$windivertScript = Join-Path $root "scripts\start-windivert-observer.ps1"
$stateDir = Join-Path $env:APPDATA "WarControl"
$dbPath = Join-Path $stateDir "warcontrol.db"
$logDir = Join-Path $root "runtime-logs"
$keyPath = Join-Path $stateDir "launcher.key"
$apiPidPath = Join-Path $stateDir "api.pid"
$webPidPath = Join-Path $stateDir "web.pid"
$collectorPidPath = Join-Path $stateDir "collector.pid"
$proxyPidPath = Join-Path $stateDir "proxy.pid"
$bedrockWatchPidPath = Join-Path $stateDir "bedrock-watch.pid"
$windivertPidPath = Join-Path $stateDir "windivert.pid"
$dashboardUrl = "http://127.0.0.1:3000"
$apiUrl = "http://127.0.0.1:8000"
$proxyBindHost = "0.0.0.0"
$proxyClientHost = "127.0.0.1"
$proxyListenPort = 19132
$proxyTargetHost = "bedrock.nationsglory.fr"
$proxyTargetPort = 19132
$networkInterceptMode = "external_server"
$bedrockServerName = "NationGlory"
$bedrockServerDisplayName = "NationGlory"
$bedrockServerIcon = "1775246171"

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
    if ($config.proxyBindHost) {
        $proxyBindHost = [string]$config.proxyBindHost
    } elseif ($config.proxyListenHost) {
        $proxyBindHost = [string]$config.proxyListenHost
    }
    if ($config.proxyClientHost) {
        $proxyClientHost = [string]$config.proxyClientHost
    }
    if ($config.proxyListenPort) {
        $proxyListenPort = [int]$config.proxyListenPort
    }
    if ($config.proxyTargetHost) {
        $proxyTargetHost = [string]$config.proxyTargetHost
    }
    if ($config.proxyTargetPort) {
        $proxyTargetPort = [int]$config.proxyTargetPort
    }
    if ($config.networkInterceptMode) {
        $networkInterceptMode = [string]$config.networkInterceptMode
    }
}

if (-not $Mode) {
    $Mode = "live"
}

if (Test-Path $stopScript) {
    & powershell.exe -ExecutionPolicy Bypass -File $stopScript | Out-Null
    Start-Sleep -Milliseconds 800
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

function Get-BedrockExternalServerFiles {
    $paths = @()

    if ($env:APPDATA) {
        $roamingRoot = Join-Path $env:APPDATA "Minecraft Bedrock\Users"
        if (Test-Path $roamingRoot) {
            $paths += Get-ChildItem -LiteralPath $roamingRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                Join-Path $_.FullName "games\com.mojang\minecraftpe\external_servers.txt"
            }
        }
    }

    if ($env:LOCALAPPDATA) {
        $uwpPath = Join-Path $env:LOCALAPPDATA "Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\games\com.mojang\minecraftpe\external_servers.txt"
        $paths += $uwpPath
    }

    $paths | Where-Object { Test-Path $_ } | Select-Object -Unique
}

function Update-BedrockServerEntry {
    param(
        [string]$FilePath,
        [string]$Name,
        [string]$ProxyHost,
        [int]$Port,
        [string]$DefaultIcon
    )

    $backupPath = "$FilePath.warcontrol.bak"
    if (-not (Test-Path $backupPath)) {
        Copy-Item -LiteralPath $FilePath -Destination $backupPath -Force
    }

    $targetLine = $null
    $updated = $false
    $lines = @()
    $escapedName = [regex]::Escape($Name)

    foreach ($line in (Get-Content -LiteralPath $FilePath -ErrorAction SilentlyContinue)) {
        if ($line -match "^\s*(?<prefix>\d+:)?\s*$escapedName\s*:(?<host>[^:]*):(?<port>\d+):(?<icon>.*)$") {
            $icon = $Matches["icon"]
            $prefix = $Matches["prefix"]
            if (-not $icon) {
                $icon = $DefaultIcon
            }
            $targetLine = "${prefix}${Name} :${ProxyHost}:${Port}:${icon}"
            $lines += $targetLine
            $updated = $true
        } else {
            $lines += $line
        }
    }

    if (-not $updated) {
        if (-not $targetLine) {
            $targetLine = "${Name} :${ProxyHost}:${Port}:${DefaultIcon}"
        }
        $lines += $targetLine
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($FilePath, $lines, $utf8NoBom)
}

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
$proxyCommand = @"
Set-Location '$root'
& '$apiVenvPython' -u '$proxyScript' --listen-host '$proxyBindHost' --listen-port $proxyListenPort --target-host '$proxyTargetHost' --target-port $proxyTargetPort --api-url '$apiUrl' --api-key '$ApiKey' --server '$Server' --source '$Source'
"@

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
    Write-Host "      Rejoins NationsGlory en jeu - WarControl basculera sur le bon moteur automatiquement." -ForegroundColor Yellow
    Write-Host "      (Mode demo disponible : modifie warcontrol.config.json ou lance --Mode demo)" -ForegroundColor DarkYellow
    Write-Host ""
}

if ($Mode -eq "live" -and $Edition -ne "java" -and $networkInterceptMode -eq "external_server") {
    $bedrockFiles = Get-BedrockExternalServerFiles
    if ($bedrockFiles.Count -gt 0) {
        foreach ($file in $bedrockFiles) {
            Update-BedrockServerEntry -FilePath $file -Name $bedrockServerName -ProxyHost $proxyClientHost -Port $proxyListenPort -DefaultIcon $bedrockServerIcon
            Write-Host "Bedrock server entry updated: $file -> $proxyClientHost`:$proxyListenPort"
        }
    } else {
        Write-Host "Aucun external_servers.txt Bedrock detecte. Le proxy sera lance, mais l'entree serveur devra etre ajoutee manuellement." -ForegroundColor Yellow
    }
}

$apiProcess = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", $apiCommand `
    -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "api.log") `
    -RedirectStandardError (Join-Path $logDir "api.err.log")
Set-Content -LiteralPath $apiPidPath -Value $apiProcess.Id -NoNewline

Start-Sleep -Seconds 2

$webProcess = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", $webCommand `
    -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "web.log") `
    -RedirectStandardError (Join-Path $logDir "web.err.log")
Set-Content -LiteralPath $webPidPath -Value $webProcess.Id -NoNewline

Start-Sleep -Seconds 2

$workerProcess = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-Command", ($(if ($Mode -eq "live" -and $Edition -ne "java") { $proxyCommand } else { $collectorCommand })) `
    -PassThru `
    -RedirectStandardOutput (Join-Path $logDir $(if ($Mode -eq "live" -and $Edition -ne "java") { "proxy.log" } else { "collector.log" })) `
    -RedirectStandardError (Join-Path $logDir $(if ($Mode -eq "live" -and $Edition -ne "java") { "proxy.err.log" } else { "collector.err.log" }))

if ($Mode -eq "live" -and $Edition -ne "java") {
    Set-Content -LiteralPath $proxyPidPath -Value $workerProcess.Id -NoNewline
    if (Test-Path $collectorPidPath) {
        Remove-Item -LiteralPath $collectorPidPath -Force -ErrorAction SilentlyContinue
    }
    $watchProcess = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $watchScript `
        -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "bedrock-watch.out.log") `
        -RedirectStandardError (Join-Path $logDir "bedrock-watch.err.log")
    Set-Content -LiteralPath $bedrockWatchPidPath -Value $watchProcess.Id -NoNewline
    if ($networkInterceptMode -eq "windivert_observe" -and (Test-Path $windivertScript)) {
        $windivertProcess = Start-Process -WindowStyle Minimized -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $windivertScript `
            -PassThru `
            -RedirectStandardOutput (Join-Path $logDir "windivert-launch.out.log") `
            -RedirectStandardError (Join-Path $logDir "windivert-launch.err.log")
        Set-Content -LiteralPath $windivertPidPath -Value $windivertProcess.Id -NoNewline
    } elseif (Test-Path $windivertPidPath) {
        Remove-Item -LiteralPath $windivertPidPath -Force -ErrorAction SilentlyContinue
    }
} else {
    Set-Content -LiteralPath $collectorPidPath -Value $workerProcess.Id -NoNewline
    if (Test-Path $proxyPidPath) {
        Remove-Item -LiteralPath $proxyPidPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $bedrockWatchPidPath) {
        Remove-Item -LiteralPath $bedrockWatchPidPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $windivertPidPath) {
        Remove-Item -LiteralPath $windivertPidPath -Force -ErrorAction SilentlyContinue
    }
}

if ($OpenBrowser) {
    Start-Sleep -Seconds 2
    Start-Process $dashboardUrl | Out-Null
}

Write-Host "WarControl lance."
Write-Host "Mode: $Mode"
Write-Host "API: $apiUrl/health"
Write-Host "Dashboard: $dashboardUrl"
if ($Mode -eq "live" -and $Edition -ne "java") {
    Write-Host "Bedrock Proxy: bind $proxyBindHost`:$proxyListenPort | client $proxyClientHost`:$proxyListenPort -> $proxyTargetHost`:$proxyTargetPort"
    Write-Host "Intercept mode: $networkInterceptMode"
}
Write-Host "Logs: $logDir"
Write-Host "Config: $configPath"
