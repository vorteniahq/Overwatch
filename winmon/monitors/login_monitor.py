"""Monitor user login and logout events via WMI and Windows Event Log."""

import logging
import threading
import time
from datetime import datetime

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.login")


class LoginMonitor:
    """Watches for user logon/logoff events using WMI Win32_LogonSession tracking."""

    CATEGORY = "login"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._thread = None
        self._known_sessions = set()

    def start(self):
        if not self._config.get("monitors", "login", "enabled"):
            log.info("Login monitor disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        log.info("Login monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _watch_loop(self):
        """Poll WMI for logon session changes."""
        try:
            import wmi
            c = wmi.WMI()
        except ImportError:
            log.error("wmi module not available - login monitor disabled")
            return
        except Exception as e:
            log.error("Cannot connect to WMI: %s", e)
            return

        # Snapshot current sessions on startup
        try:
            for session in c.Win32_LogonSession():
                self._known_sessions.add(session.LogonId)
        except Exception as e:
            log.error("Failed to snapshot sessions: %s", e)

        while self._running:
            try:
                current_sessions = {}
                for session in c.Win32_LogonSession():
                    current_sessions[session.LogonId] = session

                current_ids = set(current_sessions.keys())
                new_ids = current_ids - self._known_sessions
                gone_ids = self._known_sessions - current_ids

                for sid in new_ids:
                    session = current_sessions[sid]
                    logon_type = int(session.LogonType or 0)

                    # Only care about interactive (2), remote (10), cached (11)
                    if logon_type not in (2, 10, 11):
                        continue

                    type_name = {2: "Interactive", 10: "Remote (RDP)", 11: "Cached"}.get(
                        logon_type, f"Type {logon_type}"
                    )

                    # Try to find associated user
                    username = self._get_session_user(c, sid)
                    summary = f"New logon: {username} ({type_name})"
                    details = (
                        f"LogonId: {sid}\n"
                        f"LogonType: {logon_type} ({type_name})\n"
                        f"AuthPackage: {session.AuthenticationPackage}\n"
                        f"StartTime: {session.StartTime}"
                    )

                    # Snoop-detection priority: every interactive login is worth knowing about.
                    # RDP (type 10) is critical because it means someone connected remotely.
                    severity = "critical" if logon_type == 10 else "warning"
                    severity, _escalated = maybe_escalate(self._config, self.CATEGORY, severity)
                    friendly = friendly_summary(
                        self.CATEGORY, summary=summary, details=details,
                        analysis={"logon_type": logon_type, "username": username}
                    )
                    dedup_key = f"login:new:{username}:{logon_type}"
                    self._db.log_event(
                        self.CATEGORY, summary, details, severity,
                        source="WMI", alerted=True,
                        friendly_summary=friendly,
                        dedup_key=dedup_key,
                    )
                    if self._config.get("monitors", "login", "alert"):
                        self._notifier.send_alert(
                            self.CATEGORY, friendly or summary, details, severity
                        )

                for sid in gone_ids:
                    # Logoff — quieter; dedup so we don't spam on every poll cycle
                    self._db.log_event(
                        self.CATEGORY, f"Session ended: {sid}",
                        severity="info", source="WMI",
                        dedup_key=f"login:end:{sid}",
                    )

                self._known_sessions = current_ids

            except Exception as e:
                log.error("Login monitor error: %s", e)

            time.sleep(5)

    def _get_session_user(self, wmi_conn, logon_id):
        """Resolve session logon ID to username."""
        try:
            results = wmi_conn.query(
                f"ASSOCIATORS OF {{Win32_LogonSession.LogonId='{logon_id}'}} "
                "WHERE AssocClass=Win32_LoggedOnUser Role=Dependent"
            )
            for user in results:
                return f"{user.Domain}\\{user.Name}"
        except Exception:
            pass
        return "UNKNOWN"
