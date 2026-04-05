$stateDir = Join-Path $env:APPDATA "WarControl"
$pidFiles = @(
    (Join-Path $stateDir "api.pid"),
    (Join-Path $stateDir "web.pid"),
    (Join-Path $stateDir "collector.pid"),
    (Join-Path $stateDir "proxy.pid"),
    (Join-Path $stateDir "bedrock-watch.pid"),
    (Join-Path $stateDir "windivert.pid")
)

foreach ($pidFile in $pidFiles) {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        continue
    }
    $pidValue = (Get-Content -LiteralPath $pidFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ($pidValue -match '^\d+$') {
        Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

foreach ($port in @(8000, 3000)) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
}

Get-NetUDPEndpoint -LocalPort 19132 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
}

$bedrockPaths = @()
if ($env:APPDATA) {
    $roamingRoot = Join-Path $env:APPDATA "Minecraft Bedrock\Users"
    if (Test-Path $roamingRoot) {
        $bedrockPaths += Get-ChildItem -LiteralPath $roamingRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            Join-Path $_.FullName "games\com.mojang\minecraftpe\external_servers.txt"
        }
    }
}
if ($env:LOCALAPPDATA) {
    $bedrockPaths += Join-Path $env:LOCALAPPDATA "Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\games\com.mojang\minecraftpe\external_servers.txt"
}

$bedrockPaths | Select-Object -Unique | ForEach-Object {
    $backup = "$_.warcontrol.bak"
    if ((Test-Path $_) -and (Test-Path $backup)) {
        Copy-Item -LiteralPath $backup -Destination $_ -Force
    }
}

Write-Host "WarControl arrete."
