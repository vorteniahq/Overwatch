"""Manage the Windows Startup-folder shortcut that launches Overwatch on login.

We use a shortcut (.lnk) in the per-user Startup folder rather than a Registry
Run-key, because:
  - It's per-user (matches the install we ship — no admin needed)
  - It plays well with `setup.ps1` which already creates the same shortcut
  - It's easy for the user to inspect / remove manually if anything breaks
"""

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("winmon.system.autostart")

STARTUP_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / \
    "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
STARTUP_SHORTCUT_PATH = STARTUP_DIR / "Overwatch.lnk"


def _resolve_launch_target() -> tuple[str, str]:
    """Return (target_path, working_dir) for the launcher.

    Prefers Overwatch.bat next to run_winmon.py. Falls back to the running
    executable when packaged with PyInstaller (sys.frozen).
    """
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, os.path.dirname(exe)

    base_dir = os.path.dirname(os.path.abspath(sys.argv[0])) or os.getcwd()
    bat = os.path.join(base_dir, "Overwatch.bat")
    if os.path.exists(bat):
        return bat, base_dir

    # No .bat next to us (dev run via python.exe directly) — best effort:
    return os.path.abspath(sys.argv[0]), base_dir


def is_autostart_enabled() -> bool:
    """True if the Startup shortcut currently exists."""
    return STARTUP_SHORTCUT_PATH.exists()


def _create_shortcut(target: str, working_dir: str) -> bool:
    """Create the Startup-folder shortcut. Returns True on success."""
    try:
        import pythoncom
        from win32com.client import Dispatch
    except ImportError:
        log.error("pywin32 not available; cannot create autostart shortcut")
        return False

    try:
        STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        pythoncom.CoInitialize()
        try:
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(STARTUP_SHORTCUT_PATH))
            shortcut.TargetPath = target
            shortcut.WorkingDirectory = working_dir
            shortcut.Description = "Overwatch Security Monitor"
            shortcut.WindowStyle = 7  # Minimised
            shortcut.Save()
        finally:
            pythoncom.CoUninitialize()
        log.info("Autostart shortcut created: %s -> %s",
                 STARTUP_SHORTCUT_PATH, target)
        return True
    except Exception as e:
        log.error("Failed to create autostart shortcut: %s", e)
        return False


def _remove_shortcut() -> bool:
    """Remove the Startup-folder shortcut. Returns True on success or if absent."""
    try:
        if STARTUP_SHORTCUT_PATH.exists():
            STARTUP_SHORTCUT_PATH.unlink()
            log.info("Autostart shortcut removed: %s", STARTUP_SHORTCUT_PATH)
        return True
    except Exception as e:
        log.error("Failed to remove autostart shortcut: %s", e)
        return False


def sync_autostart(desired_enabled: bool) -> bool:
    """Reconcile the on-disk shortcut to match `desired_enabled`.

    Returns True if the resulting state matches `desired_enabled`.
    """
    current = is_autostart_enabled()
    if desired_enabled and not current:
        target, working_dir = _resolve_launch_target()
        return _create_shortcut(target, working_dir)
    if (not desired_enabled) and current:
        return _remove_shortcut()
    return True  # already in desired state
