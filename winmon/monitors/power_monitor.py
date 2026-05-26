"""Laptop mode — power & battery monitor.

Auto-activates only on devices with a battery (laptops). Snoop-detection angle:
- Charger unplugged   -> someone may be picking the laptop up to move/steal it
- Battery draining while you're away -> the laptop is being used
- (Lid open/close is partially covered by SessionMonitor's lock/unlock.)

If Away Mode is on, an unplug becomes a critical alert.
"""

import logging
import threading
import time

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.power")

POLL_INTERVAL = 5.0
LOW_BATTERY_PCT = 20


class PowerMonitor:
    """Tracks AC power and battery state on laptops."""

    CATEGORY = "power"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._thread = None

    @staticmethod
    def is_laptop() -> bool:
        """True if the device has a battery (i.e. is a laptop/tablet)."""
        try:
            import psutil
            return psutil.sensors_battery() is not None
        except Exception:
            return False

    def start(self):
        if not self._config.get("monitors", "power", "enabled"):
            log.info("Power monitor disabled")
            return
        if not self.is_laptop():
            log.info("No battery detected - power monitor idle (desktop)")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop, name="overwatch-power", daemon=True
        )
        self._thread.start()
        log.info("Laptop power monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _watch_loop(self):
        import psutil
        prev = psutil.sensors_battery()
        prev_plugged = prev.power_plugged if prev else True
        low_warned = False

        while self._running:
            try:
                bat = psutil.sensors_battery()
                if bat is not None:
                    # AC plug/unplug transition
                    if bat.power_plugged != prev_plugged:
                        if not bat.power_plugged:
                            self._emit(
                                "Charger unplugged (now on battery)",
                                f"Battery: {int(bat.percent)}%",
                                "warning",
                            )
                        else:
                            self._emit(
                                "Laptop plugged in to power",
                                f"Battery: {int(bat.percent)}%",
                                "info",
                            )
                        prev_plugged = bat.power_plugged

                    # Low battery (once per dip below threshold)
                    if not bat.power_plugged and bat.percent <= LOW_BATTERY_PCT:
                        if not low_warned:
                            self._emit(
                                "Low battery",
                                f"Battery at {int(bat.percent)}%",
                                "info",
                            )
                            low_warned = True
                    elif bat.percent > LOW_BATTERY_PCT:
                        low_warned = False

            except Exception as e:
                log.error("Power monitor error: %s", e)

            for _ in range(int(POLL_INTERVAL * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def _emit(self, summary, details, severity):
        severity, escalated = maybe_escalate(self._config, self.CATEGORY, severity)
        friendly = friendly_summary(self.CATEGORY, summary=summary, details=details)
        is_alert = escalated or severity in ("warning", "critical")
        _id, is_update = self._db.log_event(
            self.CATEGORY, summary, details, severity,
            source="power", alerted=is_alert,
            friendly_summary=friendly,
            dedup_key=f"power:{summary[:20]}",
        )
        if is_alert and not is_update and self._config.get("monitors", "power", "alert"):
            self._notifier.send_alert(self.CATEGORY, friendly or summary, details, severity)
        log.info("Power event: %s (%s)", summary, severity)
