@echo off
:: Overwatch Security Monitor
:: Right-click the tray icon to access Dashboard, Settings, and all controls.

set SCRIPT_DIR=%~dp0
set PYTHON=%SCRIPT_DIR%venv\Scripts\pythonw.exe

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found at %SCRIPT_DIR%venv
    echo Run setup.ps1 first to install dependencies.
    pause
    exit /b 1
)

start "" "%PYTHON%" "%SCRIPT_DIR%run_winmon.py" %*
