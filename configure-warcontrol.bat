@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\configure-warcontrol.ps1"
endlocal
