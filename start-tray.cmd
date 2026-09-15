@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: Find pythonw.exe (no console window).
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
    echo Could not find pythonw.exe.
    echo Install Python or pass a venv under this folder.
    pause
    exit /b 1
)

if not exist "%~dp0tray.py" (
    echo tray.py not found in "%~dp0"
    pause
    exit /b 1
)

:: Elevate so Start/Stop service works, then launch with no leftover console.
net session >nul 2>&1
if %errorlevel%==0 (
    start "" /D "%~dp0" "%PYW%" "%~dp0tray.py"
    exit /b 0
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%PYW%' -ArgumentList '\"%~dp0tray.py\"' -WorkingDirectory '%~dp0' -Verb RunAs"
exit /b %ERRORLEVEL%
