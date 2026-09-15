@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Windows PowerShell defaults to Restricted on many machines, which
:: blocks .ps1 files. Bypass is process-only and does not change the
:: system policy. Unblock-File clears Mark-of-the-Web if this folder
:: was copied from another PC.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%~dp0install.ps1' -ErrorAction SilentlyContinue"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo.
    echo Command failed with exit code %ERR%.
    pause
    exit /b %ERR%
)

echo.
pause
exit /b 0
