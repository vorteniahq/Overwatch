"""System tray icon for Overwatch with status and quick actions."""

import logging
import os
import threading

log = logging.getLogger("winmon.gui.tray")


def create_icon_image():
    """Create a shield icon for the tray."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Shield shape
        draw.polygon(
            [(32, 4), (58, 16), (54, 44), (32, 60), (10, 44), (6, 16)],
            fill=(0, 120, 215, 255),
            outline=(255, 255, 255, 255),
        )
        # Checkmark
        draw.line([(22, 32), (30, 42), (44, 22)], fill="white", width=3)
        return img
    except ImportError:
        return None


class TrayApp:
    """System tray application for Overwatch."""

    def __init__(self, engine):
        self.engine = engine
        self._icon = None

    def run(self):
        """Run the tray icon (blocking call)."""
        try:
            import pystray
            from pystray import MenuItem, Menu
        except ImportError:
            log.error("pystray not installed - system tray disabled")
            log.error("Install with: pip install pystray pillow")
            return

        icon_image = create_icon_image()
        if icon_image is None:
            log.error("Cannot create tray icon (Pillow not available)")
            return

        menu = Menu(
            MenuItem("Status", self._on_status),
            MenuItem("Open Dashboard", self._on_dashboard),
            MenuItem("Settings", self._on_settings),
            Menu.SEPARATOR,
            MenuItem("Test Alert", self._on_test_alert),
            Menu.SEPARATOR,
            MenuItem("Pause Monitoring", self._on_pause, checked=lambda item: not self.engine._running),
            MenuItem("Restart", self._on_restart),
            MenuItem("Exit", self._on_exit),
        )

        self._icon = pystray.Icon("Overwatch", icon_image, "Overwatch Security Monitor", menu)
        self._icon.run()

    def stop(self):
        """Stop the tray icon."""
        if self._icon:
            self._icon.stop()

    def _on_status(self, icon, item):
        """Show engine status."""
        try:
            status = self.engine.get_status()
            msg = (
                f"Running: {status['running']}\n"
                f"Active monitors: {status['monitors']}\n"
                f"Monitors: {', '.join(status['monitor_names'])}"
            )
            icon.notify(msg, "Overwatch Status")
        except Exception as e:
            icon.notify(f"Error: {e}", "Overwatch")

    def _on_dashboard(self, icon, item):
        """Open the configuration GUI."""
        try:
            threading.Thread(target=self._launch_gui, daemon=True).start()
        except Exception as e:
            log.error("Failed to open dashboard: %s", e)

    def _on_settings(self, icon, item):
        """Open settings panel."""
        try:
            threading.Thread(target=self._launch_settings, daemon=True).start()
        except Exception as e:
            log.error("Failed to open settings: %s", e)

    def _on_test_alert(self, icon, item):
        """Send a test Telegram alert."""
        self.engine.notifier.send_test()
        icon.notify("Test alert sent!", "Overwatch")

    def _on_pause(self, icon, item):
        """Toggle monitoring pause."""
        if self.engine._running:
            self.engine.stop()
            icon.notify("Monitoring paused", "Overwatch")
        else:
            self.engine.start()
            icon.notify("Monitoring resumed", "Overwatch")

    def _on_restart(self, icon, item):
        """Restart the monitoring engine."""
        try:
            self.engine.stop()
            self.engine = self.engine.__class__(self.engine.config)
            self.engine.start()
            icon.notify("Overwatch restarted", "Overwatch")
        except Exception as e:
            log.error("Restart error: %s", e)
            icon.notify(f"Restart failed: {e}", "Overwatch")

    def _on_exit(self, icon, item):
        """Exit the application cleanly."""
        def _shutdown():
            try:
                self.engine.stop()
            except Exception as e:
                log.error("Engine stop error on exit: %s", e)
            finally:
                os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        try:
            icon.stop()
        except Exception:
            os._exit(0)

    def _launch_gui(self):
        """Launch the main GUI."""
        from winmon.gui.dashboard import DashboardGUI
        gui = DashboardGUI(self.engine)
        gui.run()

    def _launch_settings(self):
        """Launch settings window."""
        from winmon.gui.settings import SettingsGUI
        gui = SettingsGUI(self.engine.config)
        gui.run()

