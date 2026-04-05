$patterns = @(
    "uvicorn api.main:app",
    "next dev --hostname 127.0.0.1 --port 3000",
    "collector\agent.py"
)

Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    $cmd -and ($patterns | Where-Object { $cmd -like "*$_*" })
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "WarControl arrete."
