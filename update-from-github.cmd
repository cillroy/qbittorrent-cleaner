@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Downloads the latest GitHub release zip and runs install.ps1 update
:: from that zip. rules.yaml, logs\, and data\ are not overwritten.
net session >nul 2>&1
if not %errorlevel%==0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

if not exist "%~dp0self_update.py" (
    echo self_update.py not found in "%~dp0"
    echo Copy self_update.py from the repo, or run this after a manual file copy.
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
echo Downloading latest GitHub release and installing into "%~dp0"
echo.
"%PY%" "%~dp0self_update.py" --apply --dest "%~dp0" --python "%PY%" --start-web %*
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
    echo GitHub update failed with exit code %ERR%.
) else (
    echo GitHub update finished. Restart the tray with start-tray.cmd.
)
pause
exit /b %ERR%
