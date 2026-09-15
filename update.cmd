@echo off
setlocal EnableExtensions
cd /d "%~dp0"

net session >nul 2>&1
if not %errorlevel%==0 (
    if "%*"=="" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)

cd /d "%~dp0"

if not exist "%~dp0install.ps1" (
    echo install.ps1 not found in "%~dp0"
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%~dp0install.ps1' -ErrorAction SilentlyContinue"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" update %*
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
    echo Update failed with exit code %ERR%.
) else (
    echo Update finished.
)
pause
exit /b %ERR%
