"""Windows service wrapper for Overwatch using pywin32."""

import logging
import os
import sys
import time

log = logging.getLogger("winmon.service")


def setup_logging(log_dir=None):
    """Configure logging to file."""
    if not log_dir:
        app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
        log_dir = os.path.join(app_data, "Overwatch", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "overwatch.log")
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Also add console handler when running interactively
    if sys.stdout and sys.stdout.isatty():
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        root.addHandler(console)


try:
    import logging.handlers
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class OverwatchService(win32serviceutil.ServiceFramework):
        """Windows Service for Overwatch security monitor."""

        _svc_name_ = "Overwatch"
        _svc_display_name_ = "Overwatch Security Monitor"
        _svc_description_ = (
            "Monitors Windows security events including logins, processes, "
            "USB devices, RDP connections, and file system changes. "
            "Sends alerts via Telegram."
        )

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.engine = None

        def SvcStop(self):
            """Called when the service is asked to stop."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            if self.engine:
                self.engine.stop()

        def SvcDoRun(self):
            """Called when the service starts."""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )
            setup_logging()

            try:
                from winmon.config import Config
                from winmon.engine import MonitorEngine

                config = Config()
                self.engine = MonitorEngine(config)
                self.engine.start()

                # Wait for stop signal
                win32event.WaitForSingleObject(
                    self.stop_event, win32event.INFINITE
                )
            except Exception as e:
                log.error("Service error: %s", e)
                servicemanager.LogErrorMsg(str(e))
            finally:
                if self.engine:
                    self.engine.stop()

except ImportError:
    # pywin32 not installed - service mode unavailable
    OverwatchService = None


def run_console():
    """Run Overwatch in console mode (not as a service)."""
    import logging.handlers
    setup_logging()
    log.info("Starting Overwatch in console mode")

    from winmon.config import Config
    from winmon.engine import MonitorEngine

    config = Config()
    engine = MonitorEngine(config)
    engine.start()

    try:
        print("Overwatch running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        engine.stop()


def main():
    """Entry point for service or console mode."""
    if len(sys.argv) > 1 and sys.argv[1] in ("install", "remove", "start",
                                                "stop", "restart", "update"):
        if OverwatchService is None:
            print("Error: pywin32 is required for Windows service mode.")
            print("Install it with: pip install pywin32")
            sys.exit(1)
        win32serviceutil.HandleCommandLine(OverwatchService)
    elif len(sys.argv) > 1 and sys.argv[1] == "console":
        run_console()
    else:
        # If called with no args by the SCM, run as service
        if OverwatchService:
            try:
                servicemanager.Initialize()
                servicemanager.PrepareToHostSingle(OverwatchService)
                servicemanager.StartServiceCtrlDispatcher()
            except Exception:
                # Not running as service - run console mode
                run_console()
        else:
            run_console()


if __name__ == "__main__":
    main()
