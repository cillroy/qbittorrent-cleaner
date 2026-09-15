@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Moves leftover root logs/debug files into logs\ and data\, then
:: removes duplicate leftovers and __pycache__. Stops the service
:: briefly so files are not locked.
net session >nul 2>&1
if not %errorlevel%==0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

if not exist "%~dp0install.ps1" (
    echo install.ps1 not found in "%~dp0"
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%~dp0install.ps1' -ErrorAction SilentlyContinue"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" cleanup %*
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
    echo Cleanup failed with exit code %ERR%.
) else (
    echo Cleanup finished. Logs are under logs\  state under data\
)
pause
exit /b %ERR%
