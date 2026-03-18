@echo off
:: Overwatch Setup — installs Python venv and dependencies
:: Run this once on a new machine, then use Overwatch.bat

echo.
echo ========================================
echo   Overwatch Setup
echo ========================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
pause
