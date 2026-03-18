# Overwatch — Windows Security Monitor

Real-time Windows security monitoring with Telegram alerts. Watches for logins, suspicious processes, USB devices, remote access connections, and file system changes.

## Quick Start

1. Run `setup.ps1` once to create the Python venv and install dependencies:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
2. Double-click **`Overwatch.bat`** — shield icon appears in system tray
3. Right-click the tray icon for Dashboard, Settings, Test Alert, Pause, Restart, Exit

## Monitors

| Monitor | Watches For | Alert Level |
|---------|------------|-------------|
| Login | User logon/logoff via WMI (Interactive, RDP, Cached) | Warning on RDP |
| Process | New process creation — 16 watchlisted executables | Warning on match |
| USB | Device insertion/removal | Warning on connect |
| RDP | Port 3389 + TeamViewer, AnyDesk, VNC, RustDesk, LogMeIn, Splashtop, BeyondTrust | Warning on detection |
| Filesystem | File changes in watched directories (C:\Users\Public, C:\Windows\Temp) | Warning on .exe/.dll/.bat/.ps1/.vbs |

### Process Watchlist (default)
powershell.exe, cmd.exe, wscript.exe, cscript.exe, mshta.exe, regsvr32.exe, rundll32.exe, certutil.exe, bitsadmin.exe, msiexec.exe, psexec.exe, mimikatz.exe, net.exe, net1.exe, whoami.exe, taskkill.exe

## Tray Menu

| Option | What it does |
|--------|-------------|
| Status | Shows monitor count and event stats |
| Open Dashboard | Event viewer with filters (category, severity, time) |
| Settings | Config editor (General, Telegram, Silent Hours, Monitors, Watchlist, File Paths, Database) |
| Test Alert | Sends a test Telegram message |
| Pause Monitoring | Stops/resumes all monitors |
| Restart | Restarts the monitoring engine without closing the app |
| Exit | Shuts down cleanly |

## Settings

- **General**: Machine name (shown in Telegram alerts — important for multi-machine setups), Start with Windows checkbox
- **Telegram**: Bot token, chat ID, enable/disable, test button
- **Silent Hours**: 12-hour AM/PM time picker, per-day checkboxes (default Mon-Fri 7am-5pm)
- **Monitors**: Enable/disable and alert toggle for each monitor
- **Process Watchlist**: Editable list of executables to alert on
- **File Paths**: Watched directories and file extension filters
- **Database**: DB path, max events, cleanup age

## Silent Hours

Mon-Fri 7am-5pm by default: Telegram alerts muted (events still logged to database). Configurable in Settings > Silent Hours tab.

## Telegram Alerts

Plain text alerts with machine name, category, severity, and timestamp. Rate-limited to 1 message/second. Configure bot token and chat ID in Settings > Telegram tab.

## Windows Service Mode

```powershell
# Install and start as background service (requires Admin)
powershell -ExecutionPolicy Bypass -File setup.ps1 -InstallService -StartService

# Uninstall
powershell -ExecutionPolicy Bypass -File setup.ps1 -Uninstall
```

Runs on boot without login. No tray icon in service mode.

## File Structure

```
Overwatch-main/
  Overwatch.bat                 # Single launcher — everything via tray menu
  setup.ps1                     # Setup / service installer
  requirements.txt              # Python dependencies
  run_winmon.py                 # Entry point (single-instance mutex)
  winmon/
    config.py                   # Thread-safe JSON config (singleton)
    database.py                 # SQLite event storage (WAL mode)
    engine.py                   # Central monitor orchestrator
    notifier.py                 # Telegram Bot API (queued, rate-limited)
    monitors/
      login_monitor.py          # WMI Win32_LogonSession
      process_monitor.py        # WMI process creation + psutil fallback
      usb_monitor.py            # WMI USB events + polling fallback
      rdp_monitor.py            # RDP port + Event Log + remote tool scan
      filesystem_monitor.py     # ReadDirectoryChangesW + polling fallback
    gui/
      tray.py                   # System tray (pystray + Pillow)
      dashboard.py              # Tkinter event viewer
      settings.py               # Tkinter config editor (7 tabs)
    service/
      winservice.py             # pywin32 Windows Service wrapper
```

## Config

Stored at `%APPDATA%\Overwatch\config.json`. Editable via Settings GUI or directly.

## Logs

`%APPDATA%\Overwatch\logs\overwatch.log` — rotating, 5MB max, 3 backups.

## Dependencies

- Python 3.8+ (3.14 tested)
- wmi, pywin32, psutil, pystray, Pillow
- tkinter and sqlite3 (stdlib)

## Changelog

### v1.1.0 (2026-03-17)
- Simplified to single launcher (Overwatch.bat) — dashboard and settings accessed from tray menu
- Added "Restart" option to tray menu
- Added "Start with Windows" checkbox in Settings > General
- Added machine name field in Settings > General (for multi-machine Telegram alerts)
- Silent hours UI converted to 12-hour AM/PM format
- Removed duplicate "View Events" tray menu item
- Removed unused utils module
- Fixed clean shutdown (threaded exit with os._exit fallback)
- Fixed .gitignore excluding .bat files
- Added Python 3.14 support to setup.ps1

### v1.0.0 (2026-02-25)
- Initial release — 5 monitors, Telegram alerts, system tray, dashboard, settings, Windows service mode
