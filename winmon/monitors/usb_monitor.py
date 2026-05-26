"""Monitor USB device insertion and removal events."""

import logging
import threading
import time

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.usb")


class USBMonitor:
    """Watches for USB device connect/disconnect events via WMI."""

    CATEGORY = "usb"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._threads = []

    def start(self):
        if not self._config.get("monitors", "usb", "enabled"):
            log.info("USB monitor disabled")
            return
        self._running = True

        for event_type in ("creation", "deletion"):
            t = threading.Thread(
                target=self._watch_usb, args=(event_type,), daemon=True
            )
            t.start()
            self._threads.append(t)

        log.info("USB monitor started")

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=5)

    def _watch_usb(self, event_type):
        """Watch for USB device events via WMI."""
        try:
            import wmi
            import pythoncom

            pythoncom.CoInitialize()
            try:
                c = wmi.WMI()
                watcher = c.Win32_USBControllerDevice.watch_for(event_type)

                while self._running:
                    try:
                        event = watcher(timeout_ms=2000)
                    except wmi.x_wmi_timed_out:
                        continue

                    self._handle_event(event, event_type)
            finally:
                pythoncom.CoUninitialize()

        except ImportError:
            log.error("wmi module not available - USB monitor using fallback")
            self._fallback_poll()
        except Exception as e:
            log.error("USB monitor error: %s", e)

    def _fallback_poll(self):
        """Fallback polling mode for USB devices."""
        try:
            import wmi
            c = wmi.WMI()
        except Exception:
            log.error("Cannot initialize WMI for USB polling")
            return

        known = set()
        try:
            for dev in c.Win32_USBHub():
                known.add(dev.DeviceID)
        except Exception:
            pass

        while self._running:
            try:
                current = {}
                for dev in c.Win32_USBHub():
                    current[dev.DeviceID] = dev

                current_ids = set(current.keys())
                added = current_ids - known
                removed = known - current_ids

                for dev_id in added:
                    dev = current[dev_id]
                    self._log_device("connected", dev_id,
                                     getattr(dev, "Name", "Unknown USB Device"))

                for dev_id in removed:
                    self._log_device("disconnected", dev_id, "USB Device")

                known = current_ids
            except Exception as e:
                log.error("USB poll error: %s", e)

            time.sleep(5)

    def _handle_event(self, event, event_type):
        """Process a WMI USB event."""
        action = "connected" if event_type == "creation" else "disconnected"
        try:
            dependent = event.Dependent
            dev_name = getattr(dependent, "Name", None) or getattr(dependent, "Caption", "Unknown")
            dev_id = getattr(dependent, "DeviceID", "Unknown")
        except Exception:
            dev_name = "USB Device"
            dev_id = str(event)

        self._log_device(action, dev_id, dev_name)

    def _log_device(self, action, dev_id, dev_name):
        """Log and alert for a USB device event."""
        summary = f"USB {action}: {dev_name}"
        details = f"DeviceID: {dev_id}\nName: {dev_name}"

        severity = "warning" if action == "connected" else "info"
        severity, escalated = maybe_escalate(self._config, self.CATEGORY, severity)
        friendly = friendly_summary(self.CATEGORY, summary=summary, details=details)

        is_alert = escalated or (action == "connected")
        # Coarse dedup key — one physical plug-in often fires many sub-device
        # events. Bucket them all into one row + one alert per 60s window.
        _id, is_update = self._db.log_event(
            self.CATEGORY, summary, details, severity,
            source="WMI", alerted=is_alert,
            friendly_summary=friendly,
            dedup_key=f"usb:{action}",
        )

        # Only Telegram-ping the first event in the window, not the dedup hits.
        if is_alert and not is_update and self._config.get("monitors", "usb", "alert"):
            self._notifier.send_alert(
                self.CATEGORY, friendly or summary, details, severity
            )
