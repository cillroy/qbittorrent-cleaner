@echo off
setlocal
:: Double-click this (or run from an elevated prompt) to update
:: the production install. Default dest is C:\qBittorrent Cleaner
:: if that exists, otherwise this folder (in-place).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" update %*
if errorlevel 1 (
    echo.
    echo Update failed.
    pause
    exit /b 1
)
echo.
pause
