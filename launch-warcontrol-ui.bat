@echo off
setlocal
if exist "%~dp0api\.venv\Scripts\python.exe" (
  "%~dp0api\.venv\Scripts\python.exe" -m launcher.app
) else (
  python -m launcher.app
)
endlocal
