@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\stop-warcontrol.ps1"
endlocal
