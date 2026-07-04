# Overwatch

Real-time Windows security monitoring with Telegram alerts, built for snoop detection: know who or what touched your computer, and when. Watches for logins, workstation lock/unlock, suspicious processes, USB devices, remote access connections, network changes, laptop power events, and file system changes. Events show up in a local web dashboard with plain-English summaries; alerts go to Telegram.

**[Download Overwatch.exe (latest release)](https://github.com/Safetypinz/Overwatch/releases/latest)** · Windows 10/11 · free, MIT · [vortenia.com/overwatch](https://vortenia.com/overwatch/)

![Overwatch dashboard: eight monitors watching, a plain-English live event feed, Away Mode one click away](docs/dashboard.png)
*The dashboard on a demo machine: seeded example data, not a real install.*

## Quick Start

**Release exe** (no Python needed):

1. [Download Overwatch.exe](https://github.com/Safetypinz/Overwatch/releases/latest) and run it. The exe is unsigned, so Windows SmartScreen warns on first run: click **More info**, then **Run anyway**. A shield icon appears in the system tray.
2. Right-click the tray icon for Dashboard, Settings, Test Alert, Pause, Restart, Exit.

**From source:**

1. Run `setup.ps1` once to create the Python venv and install dependencies:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
2. Double-click **`Overwatch.bat`**. Same tray icon, same menu.

## Requirements

- Windows 10 or 11
- Python 3.8–3.12, source install only; the release exe is self-contained (3.12 recommended; 3.13+ lacks pre-built wheels for `httptools` / `psutil`)
- Administrator rights for some monitors (login/process via WMI) and for service mode
- WebView2 runtime for the native dashboard window (preinstalled on Windows 10/11; falls back to your default browser if unavailable)

## Monitors

| Monitor | Watches For | Alert Level |
|---------|------------|-------------|
| Login | User logon/logoff via WMI (Interactive, RDP, Cached) | Warning on RDP |
| Session | Workstation lock/unlock (the key snoop signal; non-admin) | Warning on unlock |
| Process | New process creation (16 watchlisted executables) | Warning on match |
| USB | Device insertion/removal | Warning on connect |
| RDP | Port 3389 + TeamViewer, AnyDesk, VNC, RustDesk, LogMeIn, Splashtop, BeyondTrust | Warning on detection |
| Network | Wi-Fi network changes, new IP/gateway, optional outbound connection watch | Warning on change |
| Power | Charger unplug and battery drain while away (laptops only; auto-idle on desktops) | Warning on unplug |
| Filesystem | File changes in watched directories (default: your Documents, Desktop, Downloads, Pictures) | Warning on .exe/.dll/.bat/.ps1/.vbs and other executable types |

### Process Watchlist (default)
powershell.exe, cmd.exe, wscript.exe, cscript.exe, mshta.exe, regsvr32.exe, rundll32.exe, certutil.exe, bitsadmin.exe, msiexec.exe, psexec.exe, mimikatz.exe, net.exe, net1.exe, whoami.exe, taskkill.exe

## Tray Menu

| Option | What it does |
|--------|-------------|
| Open Dashboard | Web dashboard: event feed with filters, plain-English summaries, Away Mode toggle |
| Settings | Config editor (General, Telegram, Silent Hours, Monitors, Watchlist, File Paths, Database) |
| Mode | Presence mode: Auto (quiet while you're at the PC), Quiet (force present), Loud (force away, alert everything) |
| Send Test Alert | Sends a test Telegram message |
| Pause Monitoring | Stops/resumes all monitors (checkbox) |
| Restart Monitors | Restarts the monitoring engine without closing the app |
| Status | Shows monitor count and event stats |
| Exit | Shuts down cleanly |

## Away Mode

Flip on Away Mode from the dashboard when you step away from the machine. While it is on, any snoop-relevant event (login, lock/unlock, USB, remote access, file change, network or power change) escalates to critical severity and forces a Telegram ping, even during silent hours.

## Presence Detection

When you are actively at the keyboard, routine info-severity events skip Telegram (they still land in the dashboard and event database). Warning and critical events always come through, so genuine intrusion signals are never silenced. Three modes, switchable from the tray "Mode" submenu: Auto (detect via input activity, default), Quiet (force present), Loud (force away, alert everything).

## Dashboard

The dashboard is a local web app served on `127.0.0.1:7373` (configurable) and shown in a native WebView2 window, falling back to your browser. Basic display mode shows plain-English summaries ("Someone signed in to this computer"); detailed mode adds process analysis with command-line scoring and MITRE ATT&CK technique tags.

## Settings

- **General**: Machine name (shown in Telegram alerts, important for multi-machine setups), Start with Windows checkbox
- **Telegram**: Bot token, chat ID, enable/disable, test button
- **Silent Hours**: 12-hour AM/PM time picker, per-day checkboxes (default Mon-Fri 7am-5pm)
- **Monitors**: Enable/disable and alert toggle for each monitor
- **Process Watchlist**: Editable list of executables to alert on
- **File Paths**: Watched directories and file extension filters
- **Database**: DB path, max events, cleanup age

## Silent Hours

Mon-Fri 7am-5pm by default: Telegram alerts muted (events still logged to database). Configurable in Settings > Silent Hours tab.

## Telegram Alerts

Plain text alerts with machine name, category, severity, and timestamp. Rate-limited to 1 message/second. Configure bot token and chat ID in Settings > Telegram tab. Your bot token and chat ID are stored only in your local config (`%APPDATA%\Overwatch\config.json`), never in this repository.

## Update Check

Once a day, Overwatch fetches `https://vortenia.com/version/overwatch.json` to see if a newer version exists. If one does, the dashboard shows a banner with a download link. **No data is sent**: the request carries nothing beyond a User-Agent header with the running version — no machine ID, no config, no event data. Disable it in `config.json` by setting `updates.enabled` to `false`.

## Build a standalone .exe (optional)

To produce a single-file `Overwatch.exe` (no Python install needed on the target machine), run on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Output is `dist\Overwatch.exe`. The build uses PyInstaller with `Overwatch.spec`. WebView2 runtime is required for the dashboard window (preinstalled on Windows 10/11).

## Windows Service Mode

```powershell
# Install and start as background service (requires Admin)
powershell -ExecutionPolicy Bypass -File setup.ps1 -InstallService -StartService

# Uninstall
powershell -ExecutionPolicy Bypass -File setup.ps1 -Uninstall
```

Runs on boot without login. No tray icon in service mode.

## Config

Stored at `%APPDATA%\Overwatch\config.json`. Editable via the Settings GUI or directly.

## Logs

`%APPDATA%\Overwatch\logs\overwatch.log`, rotating, 5MB max, 3 backups.

## Dependencies

- Python 3.8–3.12 (3.12 recommended; 3.13+ lacks pre-built wheels for `httptools` / `psutil`)
- wmi, pywin32, psutil, pystray, Pillow
- fastapi, uvicorn, pywebview (web dashboard)
- sqlite3 (stdlib)

## Changelog

### v2.0.0 (2026-07-03)
- Rebuilt as a snoop-detection app: the dashboard is now a local web UI (FastAPI + WebView2 window) replacing the Tkinter GUI
- Plain-English event summaries in basic mode; detailed mode adds process analysis (parent chain, command-line scoring, signing checks) with MITRE ATT&CK technique tags
- Away Mode: one toggle escalates all snoop-relevant events to critical and forces Telegram pings, even during silent hours
- Presence detection: routine info alerts skip Telegram while you are actively at the keyboard; Auto/Quiet/Loud modes in the tray menu
- Daily anonymous update check with a dashboard banner when a new version is out; sends no data, off switch in config (see Update Check)
- New Session monitor: workstation lock/unlock detection without admin rights
- New Network monitor: Wi-Fi changes, new IP/gateway, optional outbound connection watch
- New Power monitor for laptops: charger unplug and battery drain while away
- Filesystem monitor now defaults to watching your Documents, Desktop, Downloads, and Pictures folders
- Fixed RDP monitor startup spam (known state seeded before alerting)
- Fixed crash and data-loss bugs found in review
- Fixed launch blockers found in pre-launch testing: WMI startup race, silent pythonw crashes (stdio now redirected to a log), native filesystem watch on current pywin32
- The user-editable process watchlist now escalates matches to warning, and the filesystem watchlist catches double extensions like invoice.exe.txt
- Log rotation hardening; build.ps1 prefers Python 3.12 to avoid source builds
- Vortenia branding: lime-on-black dashboard palette, new tray icon and favicon
- Windows packaging: PyInstaller spec and build.ps1 produce a single-file Overwatch.exe
- MIT license (Vortenia)

### v1.1.0 (2026-03-17)
- Simplified to a single launcher (Overwatch.bat): dashboard and settings accessed from the tray menu
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
- Initial release: 5 monitors, Telegram alerts, system tray, dashboard, settings, Windows service mode

## License

[MIT](LICENSE) © Vortenia

A [Vortenia](https://vortenia.com) tool.
