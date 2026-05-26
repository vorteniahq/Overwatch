"""Monitor RDP and TeamViewer/AnyDesk remote access connections."""

import logging
import threading
import time
import os

from winmon.intel import friendly_summary

log = logging.getLogger("winmon.monitors.rdp")

# Remote access processes to watch for
REMOTE_ACCESS_PROCESSES = {
    "mstsc.exe": "RDP Client",
    "teamviewer.exe": "TeamViewer",
    "teamviewer_service.exe": "TeamViewer Service",
    "tv_w32.exe": "TeamViewer",
    "tv_x64.exe": "TeamViewer",
    "anydesk.exe": "AnyDesk",
    "vnc.exe": "VNC",
    "vncviewer.exe": "VNC Viewer",
    "vncserver.exe": "VNC Server",
    "rustdesk.exe": "RustDesk",
    "splashtop.exe": "Splashtop",
    "logmein.exe": "LogMeIn",
    "bomgar-scc.exe": "BeyondTrust",
}

# RDP-related Windows Event Log IDs
RDP_EVENT_IDS = {
    4624: "Logon (Type 10 = RDP)",
    4625: "Failed Logon",
    21: "RDP Session Connected",
    22: "RDP Shell Started",
    23: "RDP Session Logoff",
    24: "RDP Session Disconnected",
    25: "RDP Session Reconnected",
}


class RDPMonitor:
    """Monitors for remote desktop and remote access tool connections."""

    CATEGORY = "rdp"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._threads = []
        self._known_remote_pids = set()

    def start(self):
        if not self._config.get("monitors", "rdp", "enabled"):
            log.info("RDP monitor disabled")
            return
        self._running = True

        # Thread 1: Watch for remote access processes
        t1 = threading.Thread(target=self._watch_processes, daemon=True)
        t1.start()
        self._threads.append(t1)

        # Thread 2: Watch RDP Event Log
        t2 = threading.Thread(target=self._watch_event_log, daemon=True)
        t2.start()
        self._threads.append(t2)

        # Thread 3: Watch network for RDP port (3389)
        t3 = threading.Thread(target=self._watch_rdp_port, daemon=True)
        t3.start()
        self._threads.append(t3)

        log.info("RDP/Remote access monitor started")

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=5)

    def _watch_processes(self):
        """Poll for remote access tool processes."""
        try:
            import psutil
        except ImportError:
            log.warning("psutil not available, trying WMI for process monitoring")
            self._watch_processes_wmi()
            return

        # Seed known PIDs so processes already running at startup don't trigger alerts
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if (proc.info["name"] or "").lower() in REMOTE_ACCESS_PROCESSES:
                    self._known_remote_pids.add(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        log.info("RDP process scan seeded %d known PIDs", len(self._known_remote_pids))

        while self._running:
            try:
                for proc in psutil.process_iter(["pid", "name", "exe", "username"]):
                    try:
                        name = (proc.info["name"] or "").lower()
                        if name in REMOTE_ACCESS_PROCESSES and proc.pid not in self._known_remote_pids:
                            self._known_remote_pids.add(proc.pid)
                            tool = REMOTE_ACCESS_PROCESSES[name]
                            summary = f"Remote access detected: {tool}"
                            details = (
                                f"Process: {proc.info['name']}\n"
                                f"Path: {proc.info.get('exe', 'N/A')}\n"
                                f"PID: {proc.pid}\n"
                                f"User: {proc.info.get('username', 'N/A')}"
                            )
                            friendly = friendly_summary(
                                self.CATEGORY, summary=summary, details=details
                            )
                            self._db.log_event(
                                self.CATEGORY, summary, details, "critical",
                                source="process_scan", alerted=True,
                                friendly_summary=friendly,
                                attack_tags=["T1219"],
                                dedup_key=f"rdp:tool:{name}",
                            )
                            if self._config.get("monitors", "rdp", "alert"):
                                self._notifier.send_alert(
                                    self.CATEGORY, friendly or summary,
                                    details, "warning"
                                )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Clean up dead PIDs
                active_pids = {p.pid for p in psutil.process_iter()}
                self._known_remote_pids &= active_pids

            except Exception as e:
                log.error("RDP process watch error: %s", e)

            time.sleep(5)

    def _watch_processes_wmi(self):
        """Fallback: use WMI to watch for remote access processes."""
        try:
            import wmi
            c = wmi.WMI()
        except Exception:
            log.error("Neither psutil nor wmi available for RDP process monitoring")
            return

        # Seed known PIDs so processes already running at startup don't trigger alerts
        for name_lower in REMOTE_ACCESS_PROCESSES:
            try:
                for proc in c.Win32_Process(Name=name_lower):
                    self._known_remote_pids.add(proc.ProcessId)
            except Exception:
                pass

        while self._running:
            try:
                for name_lower, tool in REMOTE_ACCESS_PROCESSES.items():
                    results = c.Win32_Process(Name=name_lower)
                    for proc in results:
                        pid = proc.ProcessId
                        if pid not in self._known_remote_pids:
                            self._known_remote_pids.add(pid)
                            summary = f"Remote access detected: {tool}"
                            details = f"Process: {name_lower}\nPID: {pid}"
                            friendly = friendly_summary(
                                self.CATEGORY, summary=summary, details=details
                            )
                            self._db.log_event(
                                self.CATEGORY, summary, details, "critical",
                                source="WMI", alerted=True,
                                friendly_summary=friendly,
                                attack_tags=["T1219"],
                                dedup_key=f"rdp:tool:{name_lower}",
                            )
                            if self._config.get("monitors", "rdp", "alert"):
                                self._notifier.send_alert(
                                    self.CATEGORY, friendly or summary,
                                    details, "warning"
                                )
            except Exception as e:
                log.error("WMI RDP process watch error: %s", e)
            time.sleep(5)

    def _watch_event_log(self):
        """Monitor Windows Event Log for RDP-related events."""
        try:
            import win32evtlog
            import win32con
        except ImportError:
            log.warning("pywin32 not available for event log monitoring")
            return

        server = None  # local
        log_types = [
            ("Security", [4624, 4625]),
            ("Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
             [21, 22, 23, 24, 25]),
        ]

        # Seed last_record to current position so old events don't fire on startup
        last_record = {}
        for log_name, _ in log_types:
            try:
                hand = win32evtlog.OpenEventLog(server, log_name)
                flags = (win32evtlog.EVENTLOG_BACKWARDS_READ |
                         win32evtlog.EVENTLOG_SEQUENTIAL_READ)
                events = win32evtlog.ReadEventLog(hand, flags, 0)
                if events:
                    last_record[log_name] = events[0].RecordNumber
                win32evtlog.CloseEventLog(hand)
            except Exception:
                pass

        while self._running:
            for log_name, event_ids in log_types:
                try:
                    hand = win32evtlog.OpenEventLog(server, log_name)
                    flags = (win32evtlog.EVENTLOG_BACKWARDS_READ |
                             win32evtlog.EVENTLOG_SEQUENTIAL_READ)

                    events = win32evtlog.ReadEventLog(hand, flags, 0)
                    for event in events[:20]:  # Only check recent
                        eid = event.EventID & 0xFFFF
                        record_num = event.RecordNumber

                        if record_num <= last_record.get(log_name, 0):
                            continue

                        if eid in event_ids:
                            # For 4624, only care about logon type 10 (RDP)
                            if eid == 4624:
                                strings = event.StringInserts or []
                                if len(strings) > 8 and strings[8] != "10":
                                    continue

                            desc = RDP_EVENT_IDS.get(eid, f"Event {eid}")
                            strings = event.StringInserts or []
                            summary = f"RDP Event: {desc}"
                            details = (
                                f"EventID: {eid}\n"
                                f"Source: {log_name}\n"
                                f"Time: {event.TimeGenerated}\n"
                                f"Data: {', '.join(strings[:5]) if strings else 'N/A'}"
                            )

                            severity = "warning" if eid in (4625,) else "info"
                            friendly = friendly_summary(
                                self.CATEGORY, summary=summary, details=details
                            )
                            tags = ["T1021.001"]
                            if eid == 4625:
                                tags.append("T1110")
                            self._db.log_event(
                                self.CATEGORY, summary, details, severity,
                                source="EventLog", alerted=(severity != "info"),
                                friendly_summary=friendly,
                                attack_tags=tags,
                                dedup_key=f"rdp:eid:{eid}",
                            )
                            if severity != "info" and self._config.get("monitors", "rdp", "alert"):
                                self._notifier.send_alert(
                                    self.CATEGORY, friendly or summary,
                                    details, severity
                                )

                        last_record[log_name] = max(
                            last_record.get(log_name, 0), record_num
                        )

                    win32evtlog.CloseEventLog(hand)
                except Exception as e:
                    log.debug("Event log '%s' error: %s", log_name, e)

            time.sleep(10)

    def _watch_rdp_port(self):
        """Monitor for active RDP connections on port 3389."""
        try:
            import psutil
        except ImportError:
            return

        known_connections = set()

        while self._running:
            try:
                for conn in psutil.net_connections(kind="tcp"):
                    if conn.laddr.port == 3389 and conn.status == "ESTABLISHED":
                        remote = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "unknown"
                        key = (conn.laddr.port, remote)
                        if key not in known_connections:
                            known_connections.add(key)
                            summary = f"Active RDP connection from {remote}"
                            details = f"Local: {conn.laddr}\nRemote: {conn.raddr}\nPID: {conn.pid}"
                            friendly = friendly_summary(
                                self.CATEGORY, summary=summary, details=details
                            )
                            self._db.log_event(
                                self.CATEGORY, summary, details, "critical",
                                source="netstat", alerted=True,
                                friendly_summary=friendly,
                                attack_tags=["T1021.001", "T1133"],
                                dedup_key=f"rdp:port:{remote}",
                            )
                            if self._config.get("monitors", "rdp", "alert"):
                                self._notifier.send_alert(
                                    self.CATEGORY, friendly or summary,
                                    details, "warning"
                                )

                # Clean stale connections
                active = set()
                for conn in psutil.net_connections(kind="tcp"):
                    if conn.laddr.port == 3389 and conn.status == "ESTABLISHED":
                        remote = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "unknown"
                        active.add((conn.laddr.port, remote))
                known_connections &= active

            except (psutil.AccessDenied, OSError) as e:
                log.debug("RDP port monitoring needs admin: %s", e)
            except Exception as e:
                log.error("RDP port watch error: %s", e)

            time.sleep(10)
