"""Monitor suspicious process creation events via WMI."""

import logging
import threading
import os

log = logging.getLogger("winmon.monitors.process")


class ProcessMonitor:
    """Watches for process creation events, alerting on watchlisted executables."""

    CATEGORY = "process"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._thread = None

    def start(self):
        if not self._config.get("monitors", "process", "enabled"):
            log.info("Process monitor disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        log.info("Process monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def _watch_loop(self):
        """Subscribe to WMI process creation events."""
        try:
            import wmi
            import pythoncom

            pythoncom.CoInitialize()
            try:
                c = wmi.WMI()
                watcher = c.Win32_Process.watch_for("creation")

                while self._running:
                    try:
                        new_proc = watcher(timeout_ms=2000)
                    except wmi.x_wmi_timed_out:
                        continue

                    self._handle_process(new_proc)
            finally:
                pythoncom.CoUninitialize()

        except ImportError:
            log.error("wmi/pythoncom not available - process monitor disabled")
            self._fallback_poll()
        except Exception as e:
            log.error("Process monitor error: %s", e)

    def _fallback_poll(self):
        """Fallback: poll process list if WMI events fail."""
        import time
        try:
            import psutil
        except ImportError:
            log.error("Neither wmi nor psutil available for process monitoring")
            return

        known_pids = {p.pid for p in psutil.process_iter()}
        while self._running:
            try:
                current = {}
                for p in psutil.process_iter(["pid", "name", "exe", "username", "cmdline"]):
                    current[p.pid] = p.info

                new_pids = set(current.keys()) - known_pids
                for pid in new_pids:
                    info = current.get(pid)
                    if info:
                        self._handle_process_info(
                            info.get("name", ""),
                            info.get("exe", ""),
                            pid,
                            info.get("username", ""),
                            " ".join(info.get("cmdline") or [])
                        )
                known_pids = set(current.keys())
            except Exception as e:
                log.error("Process poll error: %s", e)
            time.sleep(3)

    def _handle_process(self, proc):
        """Handle a WMI process creation event."""
        try:
            name = proc.Name or ""
            exe = proc.ExecutablePath or ""
            pid = proc.ProcessId
            cmd = proc.CommandLine or ""

            # Get parent info
            parent_id = proc.ParentProcessId
            owner = ""
            try:
                result = proc.GetOwner()
                if result[0] == 0:
                    owner = f"{result[1]}\\{result[2]}" if result[1] else result[2]
            except Exception:
                pass

            self._handle_process_info(name, exe, pid, owner, cmd, parent_id)
        except Exception as e:
            log.error("Error handling process event: %s", e)

    def _handle_process_info(self, name, exe, pid, owner, cmd, parent_id=None):
        """Evaluate and log/alert on process creation."""
        watchlist = self._config.get("monitors", "process", "watchlist") or []

        name_lower = (name or "").lower()
        is_watched = any(w.lower() == name_lower for w in watchlist)

        # Always log to database
        details = (
            f"Name: {name}\n"
            f"Path: {exe}\n"
            f"PID: {pid}\n"
            f"Owner: {owner}\n"
            f"CommandLine: {cmd}"
        )
        if parent_id:
            details += f"\nParentPID: {parent_id}"

        severity = "warning" if is_watched else "info"
        self._db.log_event(self.CATEGORY, f"Process started: {name}",
                           details, severity, source="WMI",
                           alerted=is_watched)

        if is_watched and self._config.get("monitors", "process", "alert"):
            summary = f"Suspicious process: {name}"
            self._notifier.send_alert(self.CATEGORY, summary, details, severity)
