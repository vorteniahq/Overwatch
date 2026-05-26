"""Monitor file system changes in configured directories."""

import logging
import os
import threading
import time
from pathlib import Path

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.filesystem")


class FileSystemMonitor:
    """Watches configured directories for suspicious file changes."""

    CATEGORY = "filesystem"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._threads = []

    def start(self):
        if not self._config.get("monitors", "filesystem", "enabled"):
            log.info("Filesystem monitor disabled")
            return
        self._running = True

        # Try to use Windows native API first, fallback to polling.
        # Expand env vars (e.g. %USERPROFILE%) so config can use portable defaults.
        raw_paths = self._config.get("monitors", "filesystem", "watch_paths") or []
        watch_paths = [os.path.expandvars(p) for p in raw_paths]

        for path in watch_paths:
            if os.path.isdir(path):
                t = threading.Thread(
                    target=self._watch_directory, args=(path,), daemon=True
                )
                t.start()
                self._threads.append(t)
                log.info("Watching directory: %s", path)
            else:
                log.warning("Watch path does not exist: %s", path)

        log.info("Filesystem monitor started (%d paths)", len(self._threads))

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=5)

    def _watch_directory(self, path):
        """Watch a single directory using ReadDirectoryChangesW or polling."""
        try:
            self._watch_native(path)
        except Exception as e:
            log.warning("Native watch failed for %s: %s. Falling back to polling.", path, e)
            self._watch_polling(path)

    def _watch_native(self, path):
        """Use Win32 ReadDirectoryChangesW for efficient file monitoring."""
        import win32file
        import win32con

        ACTIONS = {
            1: "Created",
            2: "Deleted",
            3: "Modified",
            4: "Renamed (old)",
            5: "Renamed (new)",
        }

        dir_handle = win32file.CreateFile(
            path,
            win32con.FILE_LIST_DIRECTORY,
            (win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE |
             win32con.FILE_SHARE_DELETE),
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )

        while self._running:
            try:
                results = win32file.ReadDirectoryChangesW(
                    dir_handle,
                    8192,   # buffer size
                    True,   # watch subtree
                    (win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
                     win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                     win32con.FILE_NOTIFY_CHANGE_SIZE |
                     win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
                     win32con.FILE_NOTIFY_CHANGE_CREATION),
                    None,
                    None,
                )

                for action, filename in results:
                    action_name = ACTIONS.get(action, f"Unknown({action})")
                    full_path = os.path.join(path, filename)
                    self._handle_change(action_name, full_path, path)

            except Exception as e:
                if self._running:
                    log.error("ReadDirectoryChanges error for %s: %s", path, e)
                    time.sleep(5)

    def _watch_polling(self, path):
        """Fallback: poll directory for changes."""
        snapshot = self._scan_dir(path)

        while self._running:
            try:
                current = self._scan_dir(path)

                # Detect new files
                for fp, mtime in current.items():
                    if fp not in snapshot:
                        self._handle_change("Created", fp, path)
                    elif mtime > snapshot[fp]:
                        self._handle_change("Modified", fp, path)

                # Detect deleted files
                for fp in snapshot:
                    if fp not in current:
                        self._handle_change("Deleted", fp, path)

                snapshot = current
            except Exception as e:
                log.error("Filesystem poll error for %s: %s", path, e)

            time.sleep(10)

    def _scan_dir(self, path):
        """Snapshot a directory tree: {filepath: mtime}."""
        result = {}
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        result[fp] = os.path.getmtime(fp)
                    except OSError:
                        pass
        except OSError:
            pass
        return result

    def _handle_change(self, action, filepath, watch_root):
        """Evaluate and log/alert on a file change."""
        ext = Path(filepath).suffix.lower()
        watched_exts = self._config.get(
            "monitors", "filesystem", "extensions_watchlist"
        ) or []

        is_suspicious = ext in watched_exts
        severity = "warning" if is_suspicious else "info"
        severity, escalated = maybe_escalate(self._config, self.CATEGORY, severity)
        is_suspicious = is_suspicious or escalated

        summary = f"File {action}: {os.path.basename(filepath)}"
        details = (
            f"Action: {action}\n"
            f"Path: {filepath}\n"
            f"WatchRoot: {watch_root}\n"
            f"Extension: {ext}"
        )

        try:
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                details += f"\nSize: {stat.st_size} bytes"
        except OSError:
            pass

        friendly = friendly_summary(self.CATEGORY, summary=summary, details=details)

        self._db.log_event(
            self.CATEGORY, summary, details, severity,
            source="filesystem", alerted=is_suspicious,
            friendly_summary=friendly,
            dedup_key=f"fs:{action}:{filepath}",
        )

        if is_suspicious and self._config.get("monitors", "filesystem", "alert"):
            self._notifier.send_alert(
                self.CATEGORY, friendly or summary, details, severity
            )
