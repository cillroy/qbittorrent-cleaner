@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Re-launch this script elevated. Passing pythonw through nested
:: PowerShell quotes breaks on "C:\qBittorrent Cleaner".
net session >nul 2>&1
if not %errorlevel%==0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not defined PYW if exist "C:\Python314\pythonw.exe" set "PYW=C:\Python314\pythonw.exe"
if not defined PYW if exist "C:\Python313\pythonw.exe" set "PYW=C:\Python313\pythonw.exe"
if not defined PYW (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
        if not defined PYW set "PYW=%%I"
    )
)

if not defined PYW (
    echo Could not find pythonw.exe while elevated.
    echo Install Python for all users, or put a .venv in this folder.
    pause
    exit /b 1
)

if not exist "%~dp0tray.py" (
    echo tray.py not found in "%~dp0"
    pause
    exit /b 1
)

echo Starting tray with:
echo   "%PYW%"
echo   "%~dp0tray.py"
echo If the icon vanishes, open logs\tray\tray-crash.log in this folder.
start "" /D "%~dp0" "%PYW%" "%~dp0tray.py"
exit /b 0
