"""Central monitoring engine that orchestrates all monitors."""

import logging
import threading
import time
from datetime import datetime

from winmon.config import Config
from winmon.database import EventDB
from winmon.notifier import TelegramNotifier
from winmon.api import APIServer
from winmon.system import sync_autostart, is_autostart_enabled
from winmon.monitors.session_monitor import SessionMonitor
from winmon.monitors.login_monitor import LoginMonitor
from winmon.monitors.process_monitor import ProcessMonitor
from winmon.monitors.usb_monitor import USBMonitor
from winmon.monitors.rdp_monitor import RDPMonitor
from winmon.monitors.filesystem_monitor import FileSystemMonitor
from winmon.monitors.network_monitor import NetworkMonitor
from winmon.monitors.power_monitor import PowerMonitor

log = logging.getLogger("winmon.engine")

MONITOR_CLASSES = [
    SessionMonitor,
    LoginMonitor,
    ProcessMonitor,
    USBMonitor,
    RDPMonitor,
    FileSystemMonitor,
    NetworkMonitor,
    PowerMonitor,
]


class MonitorEngine:
    """Manages lifecycle of all security monitors + dashboard API."""

    def __init__(self, config=None):
        self.config = config or Config()
        self.db = EventDB(self.config.get("database", "path") or "winmon_events.db")
        self.notifier = TelegramNotifier(self.config)
        self.api = APIServer(
            self,
            host=self.config.get("api", "host") or "127.0.0.1",
            port=self.config.get("api", "port") or 7373,
        )
        self._monitors = []
        self._running = False
        self._paused = False
        self._cleanup_thread = None

    # ---- lifecycle --------------------------------------------------------

    def start(self):
        """Start API server, notifier, all enabled monitors, and cleanup loop."""
        log.info("Starting Overwatch engine")
        self._running = True

        # Reconcile config <-> Startup-folder shortcut on boot:
        #   - If the shortcut already exists on disk (e.g. created by setup.ps1)
        #     but config says autostart=false, ADOPT reality so the toggle UI shows true.
        #   - We never auto-modify the shortcut at boot; the user does that via Settings.
        try:
            shortcut_exists = is_autostart_enabled()
            config_says = bool(self.config.get("general", "autostart"))
            if shortcut_exists and not config_says:
                self.config.set("general", "autostart", True)
                log.info("Adopted existing Startup shortcut into config")
            elif config_says and not shortcut_exists:
                self.config.set("general", "autostart", False)
                log.info("Startup shortcut missing; cleared autostart flag in config")
        except Exception as e:
            log.warning("Autostart adoption at startup failed: %s", e)

        self.api.start()
        self.notifier.start()
        self._start_monitors()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True
        )
        self._cleanup_thread.start()

        self.db.log_event(
            "system", "Overwatch engine started",
            f"Monitors active: {len(self._monitors)}",
            "info", source="engine"
        )
        log.info("Overwatch engine running with %d monitors", len(self._monitors))

    def stop(self):
        """Stop monitors, notifier, API server, and clean up."""
        log.info("Stopping Overwatch engine")
        self._running = False

        self._stop_monitors()
        self.notifier.stop()
        self.api.stop()

        self.db.log_event(
            "system", "Overwatch engine stopped",
            severity="info", source="engine"
        )
        self.db.close()
        log.info("Overwatch engine stopped")

    def pause(self):
        """Stop monitors but keep API + notifier alive."""
        if self._paused:
            return
        log.info("Pausing monitors")
        self._stop_monitors()
        self._paused = True
        self.db.log_event(
            "system", "Monitoring paused",
            severity="info", source="engine"
        )

    def resume(self):
        """Restart monitors after a pause."""
        if not self._paused:
            return
        log.info("Resuming monitors")
        self._start_monitors()
        self._paused = False
        self.db.log_event(
            "system", "Monitoring resumed",
            severity="info", source="engine"
        )

    def restart(self):
        """Restart all monitors (e.g. after a config change)."""
        log.info("Restarting monitors")
        self._stop_monitors()
        self._start_monitors()
        self.db.log_event(
            "system", "Monitors restarted",
            severity="info", source="engine"
        )

    # ---- helpers ----------------------------------------------------------

    def _start_monitors(self):
        self._monitors = []
        for cls in MONITOR_CLASSES:
            try:
                mon = cls(self.config, self.db, self.notifier)
                mon.start()
                self._monitors.append(mon)
                log.info("Started monitor: %s", cls.__name__)
            except Exception as e:
                log.error("Failed to start %s: %s", cls.__name__, e)

    def _stop_monitors(self):
        for mon in self._monitors:
            try:
                mon.stop()
            except Exception as e:
                log.error("Error stopping %s: %s", type(mon).__name__, e)
        self._monitors = []

    def _cleanup_loop(self):
        """Periodically clean up old events."""
        while self._running:
            try:
                days = self.config.get("database", "cleanup_days") or 30
                max_events = self.config.get("database", "max_events") or 100000
                self.db.cleanup(days=days, max_events=max_events)
            except Exception as e:
                log.error("Cleanup error: %s", e)

            for _ in range(6 * 3600):  # 6 hours
                if not self._running:
                    return
                time.sleep(1)

    def get_status(self):
        """Return current engine status."""
        return {
            "running": self._running,
            "paused": self._paused,
            "monitors": len(self._monitors),
            "monitor_names": [type(m).__name__ for m in self._monitors],
            "stats": self.db.get_stats(),
            "machine_name": self.config.get("general", "machine_name") or "",
            "dashboard_url": self.api.url,
        }
