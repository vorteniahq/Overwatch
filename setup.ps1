# Overwatch - Windows Security Monitor Setup Script
# Run as: powershell -ExecutionPolicy Bypass -File setup.ps1
# Use -InstallService flag for Windows service installation (requires Admin)

param(
    [switch]$InstallService,
    [switch]$StartService,
    [switch]$Uninstall,
    [switch]$RunNow,
    [switch]$SettingsOnly
)

$ErrorActionPreference = "Continue"
$OverwatchDir = $PSScriptRoot
$VenvDir = Join-Path $OverwatchDir "venv"
$PythonExe = $null

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Overwatch Security Monitor Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- Find Python ----
function Find-Python {
    $candidates = @(
        "python",
        "python3",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python314\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )

    foreach ($candidate in $candidates) {
        try {
            $output = & $candidate --version 2>&1
            if ($output -match "Python 3\.(\d+)") {
                $minor = [int]$Matches[1]
                if ($minor -ge 8) {
                    Write-Host "[OK] Found Python: $output" -ForegroundColor Green
                    return $candidate
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

$PythonExe = Find-Python
if (-not $PythonExe) {
    Write-Host "[ERROR] Python 3.8+ not found!" -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    exit 1
}

# ---- Handle Uninstall ----
if ($Uninstall) {
    Write-Host "`n--- Uninstalling Overwatch ---" -ForegroundColor Yellow

    # Stop and remove service
    try {
        $svc = Get-Service -Name "Overwatch" -ErrorAction SilentlyContinue
        if ($svc) {
            if ($svc.Status -eq "Running") {
                Write-Host "Stopping Overwatch service..."
                Stop-Service -Name "Overwatch" -Force
            }
            Write-Host "Removing Overwatch service..."
            & sc.exe delete Overwatch
        }
    } catch {
        Write-Host "Note: Service removal may require admin rights" -ForegroundColor Yellow
    }

    # Remove startup shortcut
    $StartupDir = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs\Startup")
    $ShortcutPath = Join-Path $StartupDir "Overwatch.lnk"
    if (Test-Path $ShortcutPath) {
        Remove-Item $ShortcutPath -Force
        Write-Host "Startup shortcut removed" -ForegroundColor Green
    }

    # Remove venv
    if (Test-Path $VenvDir) {
        Write-Host "Removing virtual environment..."
        Remove-Item $VenvDir -Recurse -Force
    }

    Write-Host "[OK] Overwatch uninstalled" -ForegroundColor Green
    Write-Host "Config and database files preserved in $env:APPDATA\Overwatch" -ForegroundColor Gray
    exit 0
}

# ---- Create Virtual Environment ----
Write-Host "`n--- Setting up Python virtual environment ---"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating venv..."
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "[OK] Virtual environment already exists" -ForegroundColor Green
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

# ---- Install Dependencies ----
Write-Host "`n--- Installing dependencies ---"
& $VenvPip install --upgrade pip 2>&1 | Out-Null
& $VenvPip install -r (Join-Path $OverwatchDir "requirements.txt") 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Some packages may have failed to install" -ForegroundColor Yellow
    Write-Host "Attempting individual installs..." -ForegroundColor Yellow

    $packages = @("wmi", "pywin32", "psutil", "pystray", "Pillow")
    foreach ($pkg in $packages) {
        Write-Host "  Installing $pkg..."
        & $VenvPip install $pkg 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    [OK] $pkg" -ForegroundColor Green
        } else {
            Write-Host "    [FAIL] $pkg" -ForegroundColor Red
        }
    }
}

# Run pywin32 post-install
Write-Host "Running pywin32 post-install..."
try {
    & $VenvPython -c "import win32api" 2>&1 | Out-Null
    Write-Host "[OK] pywin32 ready" -ForegroundColor Green
} catch {
    try {
        & $VenvPython (Join-Path $VenvDir "Scripts\pywin32_postinstall.py") -install 2>&1 | Out-Null
    } catch {
        Write-Host "[NOTE] pywin32 post-install may need admin rights" -ForegroundColor Yellow
    }
}

Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ---- Create config directory ----
$ConfigDir = Join-Path $env:APPDATA "Overwatch"
if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    Write-Host "[OK] Config directory created: $ConfigDir" -ForegroundColor Green
}

$LogDir = Join-Path $ConfigDir "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ---- Create launcher script ----
Write-Host "`n--- Creating launcher script ---"

$launcherContent = @"
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
"@
Set-Content -Path (Join-Path $OverwatchDir "Overwatch.bat") -Value $launcherContent

Write-Host "[OK] Launcher script created" -ForegroundColor Green

# ---- Create startup shortcut ----
Write-Host "`n--- Creating startup shortcut ---"
$StartupDir = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs\Startup")
$ShortcutPath = Join-Path $StartupDir "Overwatch.lnk"

try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $OverwatchDir "Overwatch.bat"
    $Shortcut.WorkingDirectory = $OverwatchDir
    $Shortcut.Description = "Overwatch Security Monitor"
    $Shortcut.WindowStyle = 7  # Minimized
    $Shortcut.Save()
    Write-Host "[OK] Startup shortcut created" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Could not create startup shortcut: $_" -ForegroundColor Yellow
}

# ---- Install as Windows Service (if requested) ----
if ($InstallService) {
    Write-Host "`n--- Installing Windows Service ---"
    Write-Host "NOTE: This requires Administrator privileges" -ForegroundColor Yellow

    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(`
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        Write-Host "[ERROR] Please run this script as Administrator to install service" -ForegroundColor Red
    } else {
        try {
            & $VenvPython (Join-Path $OverwatchDir "winmon\service\winservice.py") install
            Write-Host "[OK] Service installed" -ForegroundColor Green

            if ($StartService) {
                & $VenvPython (Join-Path $OverwatchDir "winmon\service\winservice.py") start
                Write-Host "[OK] Service started" -ForegroundColor Green
            }
        } catch {
            Write-Host "[ERROR] Service installation failed: $_" -ForegroundColor Red
        }
    }
}

# ---- Open Settings ----
if ($SettingsOnly) {
    Write-Host "`nOpening settings..."
    & $VenvPython (Join-Path $OverwatchDir "run_winmon.py") settings
    exit 0
}

# ---- Run Now ----
if ($RunNow) {
    Write-Host "`n--- Starting Overwatch ---"
    & $VenvPython (Join-Path $OverwatchDir "run_winmon.py") tray
    exit 0
}

# ---- Done ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Overwatch Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Quick Start:" -ForegroundColor Cyan
Write-Host "  1. Double-click Overwatch.bat to start"
Write-Host "  2. Right-click the tray icon for Dashboard, Settings, and controls"
Write-Host ""
Write-Host "Service Mode (requires admin):" -ForegroundColor Cyan
Write-Host "  Install:  .\setup.ps1 -InstallService"
Write-Host "  Start:    .\setup.ps1 -InstallService -StartService"
Write-Host "  Remove:   .\setup.ps1 -Uninstall"
Write-Host ""
Write-Host "Config: $ConfigDir\config.json" -ForegroundColor Gray
Write-Host "Logs:   $ConfigDir\logs\overwatch.log" -ForegroundColor Gray
Write-Host ""
