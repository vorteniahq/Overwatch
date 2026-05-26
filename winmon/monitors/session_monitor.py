"""Monitor workstation lock / unlock events — the key signal for snoop-detection.

On modern Windows, LogonUI.exe is the process that hosts the lock screen.
It starts when the screen locks and exits when the user unlocks. We poll
for its presence every 2 seconds and emit events on transitions.

This is non-admin (no Security event-log read needed) and works on Win 10/11.
"""

import logging
import os
import threading
import time

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.session")

LOCK_SCREEN_PROCESS = "logonui.exe"
POLL_INTERVAL = 2.0


class SessionMonitor:
    """Tracks workstation lock/unlock transitions."""

    CATEGORY = "session"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._thread = None
        self._username = os.environ.get("USERNAME") or "user"

    def start(self):
        if not self._config.get("monitors", "session", "enabled"):
            log.info("Session monitor disabled")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop, name="overwatch-session", daemon=True
        )
        self._thread.start()
        log.info("Session lock/unlock monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _is_locked(self) -> bool:
        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                try:
                    if (p.info["name"] or "").lower() == LOCK_SCREEN_PROCESS:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            log.error("psutil unavailable — session monitor cannot run")
        return False

    def _watch_loop(self):
        # Seed initial state so the first poll doesn't emit a spurious transition.
        prev_locked = self._is_locked()
        log.info("Session monitor initial state: %s",
                 "locked" if prev_locked else "active")

        while self._running:
            try:
                now_locked = self._is_locked()
                if now_locked != prev_locked:
                    self._emit("locked" if now_locked else "unlocked")
                    prev_locked = now_locked
            except Exception as e:
                log.error("Session monitor poll error: %s", e)

            for _ in range(int(POLL_INTERVAL * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def _emit(self, action: str):
        summary = f"Workstation {action}"
        details = (
            f"Action: {action}\n"
            f"User: {self._username}\n"
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # Unlocks are higher signal than locks (someone touched the machine).
        severity = "warning" if action == "unlocked" else "info"
        severity, escalated = maybe_escalate(self._config, self.CATEGORY, severity)
        friendly = friendly_summary(
            self.CATEGORY, summary=summary,
            analysis={"username": self._username},
        )

        is_alert = escalated or (severity != "info")
        if is_alert and self._config.get("monitors", "session", "alert"):
            self._notifier.send_alert(
                self.CATEGORY, friendly or summary, details, severity
            )

        self._db.log_event(
            self.CATEGORY, summary, details, severity,
            source="logonui_poll",
            alerted=is_alert,
            friendly_summary=friendly,
            dedup_key=f"session:{action}",
        )
        log.info("Session %s emitted", action)
