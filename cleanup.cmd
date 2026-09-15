@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Standalone: does not need a new install.ps1. Copy this file and paths.py
:: into C:\qBittorrent Cleaner, then double-click.
net session >nul 2>&1
if not %errorlevel%==0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

if not exist "%~dp0paths.py" (
    echo paths.py not found in "%~dp0"
    echo Copy paths.py from the repo into this folder, then run cleanup.cmd again.
    pause
    exit /b 1
)

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY (
    for /f "delims=" %%I in ('where python.exe 2^>nul') do (
        if not defined PY set "PY=%%I"
    )
)

if not defined PY (
    echo Could not find python.exe while elevated.
    pause
    exit /b 1
)

echo Using "%PY%"
echo Stopping QBCleanerService and web.py so log files are not locked...
sc.exe query QBCleanerService >nul 2>&1
if %errorlevel%==0 (
    sc.exe stop QBCleanerService >nul
    timeout /t 3 /nobreak >nul
)
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'web\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
"%PY%" "%~dp0paths.py"
set "ERR=%ERRORLEVEL%"

echo.
echo Starting QBCleanerService...
sc.exe query QBCleanerService >nul 2>&1
if %errorlevel%==0 (
    sc.exe start QBCleanerService >nul
)

echo.
if not "%ERR%"=="0" (
    echo Cleanup failed with exit code %ERR%.
) else (
    echo Cleanup finished. Logs are under logs\  state under data\
)
pause
exit /b %ERR%
