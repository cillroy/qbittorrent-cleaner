@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Same Bypass wrapper as install.cmd, always runs the update action.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%~dp0install.ps1' -ErrorAction SilentlyContinue"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" update %*
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo.
    echo Update failed with exit code %ERR%.
    pause
    exit /b %ERR%
)

echo.
pause
exit /b 0
