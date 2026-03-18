#!/usr/bin/env python3
"""
Overwatch - Windows Security Monitor
Run this file to start. Everything is controlled from the system tray icon.
"""

import os
import sys
import logging
import logging.handlers
import ctypes


def setup_logging():
    """Configure rotating file log + console output."""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(app_data, "Overwatch", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "overwatch.log")

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)

    # Console output when running in a terminal
    if sys.stdout and sys.stdout.isatty():
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)


def single_instance():
    """Use a Windows named mutex to prevent multiple instances."""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "OverwatchSecurityMonitor")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            0,
            "Overwatch is already running.\nCheck your system tray.",
            "Overwatch",
            0x40  # MB_ICONINFORMATION
        )
        sys.exit(0)
    return mutex  # Keep reference alive for process lifetime


def main():
    _mutex = single_instance()
    setup_logging()

    # Ensure winmon package is on the path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    from winmon.config import Config
    from winmon.engine import MonitorEngine
    from winmon.gui.tray import TrayApp

    config = Config()
    engine = MonitorEngine(config)
    engine.start()

    tray = TrayApp(engine)
    try:
        tray.run()  # Blocking — right-click tray icon for all controls
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
