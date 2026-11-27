@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-microservices.ps1" %*
echo.
echo Press any key to close this window (started servers keep running in their own windows).
pause >nul
