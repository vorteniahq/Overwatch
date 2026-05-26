"""Process creation monitor with parent-tree, cmdline scoring, and signing analysis."""

import logging
import threading

from winmon.intel import analyse_process, friendly_summary

log = logging.getLogger("winmon.monitors.process")


class ProcessMonitor:
    """Watches new processes and scores each on a 0-100 risk scale."""

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

    # ---- main loop --------------------------------------------------------

    def _watch_loop(self):
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
                    self._handle_wmi_event(new_proc)
            finally:
                pythoncom.CoUninitialize()

        except ImportError:
            log.error("wmi/pythoncom not available — falling back to psutil polling")
            self._fallback_poll()
        except Exception as e:
            log.error("Process monitor error: %s", e)

    def _fallback_poll(self):
        import time
        try:
            import psutil
        except ImportError:
            log.error("Neither wmi nor psutil available — process monitor stopped")
            return

        known_pids = {p.pid for p in psutil.process_iter()}
        while self._running:
            try:
                current = {p.pid: p.info for p in psutil.process_iter(
                    ["pid", "name", "exe", "username", "cmdline"]
                )}
                new_pids = set(current.keys()) - known_pids
                for pid in new_pids:
                    info = current[pid]
                    self._handle(
                        name=info.get("name") or "",
                        exe=info.get("exe") or "",
                        pid=pid,
                        owner=info.get("username") or "",
                        cmd=" ".join(info.get("cmdline") or []),
                        parent_pid=None,
                    )
                known_pids = set(current.keys())
            except Exception as e:
                log.error("Process poll error: %s", e)
            time.sleep(3)

    # ---- event handling ---------------------------------------------------

    def _handle_wmi_event(self, proc):
        try:
            name = proc.Name or ""
            exe = proc.ExecutablePath or ""
            pid = proc.ProcessId
            cmd = proc.CommandLine or ""
            parent_id = proc.ParentProcessId

            # WMI's CommandLine is often empty for shell-launched processes;
            # fall back to psutil so the scoring rules have something to match.
            if not cmd and pid:
                try:
                    import psutil
                    p = psutil.Process(pid)
                    cmd = " ".join(p.cmdline() or [])
                    if not exe:
                        try:
                            exe = p.exe() or ""
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass
                except Exception:
                    pass  # process may have exited already — proceed with WMI fields

            owner = ""
            try:
                result = proc.GetOwner()
                if result and result[0] == 0:
                    owner = f"{result[1]}\\{result[2]}" if result[1] else (result[2] or "")
            except Exception:
                pass

            self._handle(name=name, exe=exe, pid=pid, owner=owner,
                         cmd=cmd, parent_pid=parent_id)
        except Exception as e:
            log.error("Error handling process event: %s", e)

    def _handle(self, *, name: str, exe: str, pid: int, owner: str,
                cmd: str, parent_pid):
        """Score the process and log it (with dedup) — alert on warning+."""
        analysis = analyse_process(
            name=name, exe=exe, cmd=cmd,
            pid=pid, parent_pid=parent_pid, owner=owner,
        )

        friendly = friendly_summary("process", name=name, exe=exe, analysis=analysis)
        summary = f"Process started: {name}"
        details = (
            f"Name: {name}\n"
            f"Path: {exe}\n"
            f"PID: {pid}\n"
            f"Owner: {owner}\n"
            f"Parent PID: {parent_pid}\n"
            f"Parent chain: {' <- '.join(analysis['parent_tree']) or '?'}\n"
            f"Signing: {analysis['signature']}\n"
            f"Confidence: {analysis['confidence']}\n"
            f"Reasons: {', '.join(analysis['reasons']) or '-'}\n"
            f"MITRE: {', '.join(analysis['attack_tags']) or '-'}\n"
            f"Command line: {cmd}"
        )

        is_alert = analysis["severity"] in ("warning", "critical")
        if is_alert and self._config.get("monitors", "process", "alert"):
            alert_summary = friendly or f"Suspicious process: {name}"
            self._notifier.send_alert(self.CATEGORY, alert_summary,
                                      details, analysis["severity"])

        self._db.log_event(
            self.CATEGORY, summary, details,
            severity=analysis["severity"], source="WMI", alerted=is_alert,
            friendly_summary=friendly,
            attack_tags=analysis["attack_tags"],
            parent_tree=analysis["parent_tree"],
            signature=analysis["signature"],
            confidence=analysis["confidence"],
            dedup_key=analysis["dedup_key"],
        )
