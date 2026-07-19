"""Engine-level tests for issue #3 — a monitor that fails to start must be
tracked, surfaced as degraded, and alerted (not silently swallowed).

Needs the web deps (fastapi/uvicorn/psutil) to import winmon.engine; skips
cleanly if they're absent so minimal envs still pass. Run:
    python -m tests.test_engine_degraded
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("APPDATA", tempfile.mkdtemp())

try:
    import winmon.engine as engine_mod
    from winmon.engine import MonitorEngine
except ModuleNotFoundError as e:
    print(f"SKIP test_engine_degraded (missing dep: {e.name})")
    sys.exit(0)


class _FailingMonitor:
    def __init__(self, config, db, notifier):
        pass

    def start(self):
        raise RuntimeError("simulated monitor init failure")

    def stop(self):
        pass


def test_failed_monitor_is_tracked_surfaced_and_alerted():
    engine = MonitorEngine()
    alerts = []
    engine.notifier.send_crash = lambda location, error: alerts.append((location, str(error)))

    orig = engine_mod.MONITOR_CLASSES
    try:
        engine_mod.MONITOR_CLASSES = [_FailingMonitor]
        engine._start_monitors()
    finally:
        engine_mod.MONITOR_CLASSES = orig

    assert engine._failed_monitors == ["_FailingMonitor"], engine._failed_monitors
    st = engine.get_status()
    assert st["degraded"] is True, "status must report degraded"
    assert "_FailingMonitor" in st["failed_monitors"]
    assert len(alerts) == 1, "a start failure must raise exactly one crash alert"
    where, msg = alerts[0]
    assert "_FailingMonitor" in where
    assert "simulated monitor init failure" in msg, "error must be verbatim"
    print("PASS test_failed_monitor_is_tracked_surfaced_and_alerted")


def test_no_failures_means_not_degraded():
    engine = MonitorEngine()
    orig = engine_mod.MONITOR_CLASSES
    try:
        engine_mod.MONITOR_CLASSES = []   # no monitors, none fail
        engine._start_monitors()
    finally:
        engine_mod.MONITOR_CLASSES = orig
    st = engine.get_status()
    assert st["degraded"] is False and st["failed_monitors"] == []
    print("PASS test_no_failures_means_not_degraded")


if __name__ == "__main__":
    test_failed_monitor_is_tracked_surfaced_and_alerted()
    test_no_failures_means_not_degraded()
    print("\nALL TESTS PASSED")
