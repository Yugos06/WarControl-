@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start-warcontrol-v2.ps1" %*
endlocal
