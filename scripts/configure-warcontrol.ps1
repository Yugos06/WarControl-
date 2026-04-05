$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "warcontrol.config.json"
$examplePath = Join-Path $root "warcontrol.config.json.example"

if (-not (Test-Path $configPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $configPath
    Write-Host "Configuration creee : $configPath"
} else {
    Write-Host "Configuration existante : $configPath"
}

Start-Process notepad.exe -ArgumentList $configPath
