"""Central monitoring engine that orchestrates all monitors."""

import logging
import threading
import time
from datetime import datetime

from winmon.config import Config
from winmon.database import EventDB
from winmon.notifier import TelegramNotifier
from winmon.monitors.login_monitor import LoginMonitor
from winmon.monitors.process_monitor import ProcessMonitor
from winmon.monitors.usb_monitor import USBMonitor
from winmon.monitors.rdp_monitor import RDPMonitor
from winmon.monitors.filesystem_monitor import FileSystemMonitor

log = logging.getLogger("winmon.engine")


class MonitorEngine:
    """Manages lifecycle of all security monitors."""

    def __init__(self, config=None):
        self.config = config or Config()
        self.db = EventDB(self.config.get("database", "path") or "winmon_events.db")
        self.notifier = TelegramNotifier(self.config)
        self._monitors = []
        self._running = False
        self._cleanup_thread = None

    def start(self):
        """Start all enabled monitors."""
        log.info("Starting Overwatch engine")
        self._running = True

        # Start notifier
        self.notifier.start()

        # Instantiate and start monitors
        monitor_classes = [
            LoginMonitor,
            ProcessMonitor,
            USBMonitor,
            RDPMonitor,
            FileSystemMonitor,
        ]

        for cls in monitor_classes:
            try:
                mon = cls(self.config, self.db, self.notifier)
                mon.start()
                self._monitors.append(mon)
                log.info("Started monitor: %s", cls.__name__)
            except Exception as e:
                log.error("Failed to start %s: %s", cls.__name__, e)

        # Start cleanup thread
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True
        )
        self._cleanup_thread.start()

        # Log startup event
        self.db.log_event("system", "Overwatch engine started",
                          f"Monitors active: {len(self._monitors)}", "info",
                          source="engine")

        log.info("Overwatch engine running with %d monitors", len(self._monitors))

    def stop(self):
        """Stop all monitors and clean up."""
        log.info("Stopping Overwatch engine")
        self._running = False

        for mon in self._monitors:
            try:
                mon.stop()
            except Exception as e:
                log.error("Error stopping %s: %s", type(mon).__name__, e)

        self.notifier.stop()

        self.db.log_event("system", "Overwatch engine stopped",
                          severity="info", source="engine")
        self.db.close()

        log.info("Overwatch engine stopped")

    def _cleanup_loop(self):
        """Periodically clean up old events."""
        while self._running:
            try:
                days = self.config.get("database", "cleanup_days") or 30
                max_events = self.config.get("database", "max_events") or 100000
                self.db.cleanup(days=days, max_events=max_events)
            except Exception as e:
                log.error("Cleanup error: %s", e)

            # Run cleanup every 6 hours
            for _ in range(6 * 3600):
                if not self._running:
                    return
                time.sleep(1)

    def get_status(self):
        """Return current engine status."""
        return {
            "running": self._running,
            "monitors": len(self._monitors),
            "monitor_names": [type(m).__name__ for m in self._monitors],
            "stats": self.db.get_stats(),
        }
