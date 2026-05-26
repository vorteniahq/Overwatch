"""System tray icon for Overwatch — opens the web dashboard in the browser."""

import logging
import os
import webbrowser

log = logging.getLogger("winmon.gui.tray")


def _create_icon_image():
    """Render the Overwatch shield icon (matches favicon.svg)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Hexagonal shield matching favicon
    draw.polygon(
        [(32, 6), (52, 16), (52, 40), (32, 54), (12, 40), (12, 16)],
        outline=(94, 234, 212, 255), width=3,
    )
    draw.ellipse([(26, 26), (38, 38)], fill=(94, 234, 212, 255))
    return img


class TrayApp:
    """System tray application — opens the native dashboard window."""

    def __init__(self, engine, dashboard_window=None):
        self.engine = engine
        self._window = dashboard_window  # DashboardWindow or None
        self._icon = None

    def run(self):
        """Run the tray icon (blocking call)."""
        try:
            import pystray
            from pystray import MenuItem, Menu
        except ImportError:
            log.error("pystray not installed — tray disabled. pip install pystray pillow")
            return

        icon_image = _create_icon_image()
        if icon_image is None:
            log.error("Pillow not available — cannot render tray icon")
            return

        menu = Menu(
            MenuItem("Open Dashboard", self._on_dashboard, default=True),
            MenuItem("Settings", self._on_settings),
            Menu.SEPARATOR,
            MenuItem("Send Test Alert", self._on_test_alert),
            MenuItem(
                "Pause Monitoring",
                self._on_pause,
                checked=lambda item: self.engine._paused,
            ),
            MenuItem("Restart Monitors", self._on_restart),
            Menu.SEPARATOR,
            MenuItem("Status", self._on_status),
            MenuItem("Exit", self._on_exit),
        )

        self._icon = pystray.Icon(
            "Overwatch", icon_image, "Overwatch Security Monitor", menu
        )
        self._icon.run()

    def stop(self):
        if self._icon:
            self._icon.stop()

    # ---- menu actions -----------------------------------------------------

    def _open(self, path: str = "/"):
        """Open the dashboard at `path`. Prefer native window; fall back to browser."""
        if self._window and self._window.available:
            self._window.show(path)
            return
        url = self.engine.api.url.rstrip("/") + path
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            log.error("Failed to open browser: %s", e)
            if self._icon:
                self._icon.notify(f"Could not open browser: {url}", "Overwatch")

    def _on_dashboard(self, icon, item):
        self._open("/")

    def _on_settings(self, icon, item):
        self._open("/settings")

    def _on_test_alert(self, icon, item):
        self.engine.notifier.send_test()
        icon.notify("Test alert queued", "Overwatch")

    def _on_pause(self, icon, item):
        if self.engine._paused:
            self.engine.resume()
            icon.notify("Monitoring resumed", "Overwatch")
        else:
            self.engine.pause()
            icon.notify("Monitoring paused", "Overwatch")

    def _on_restart(self, icon, item):
        try:
            self.engine.restart()
            icon.notify("Monitors restarted", "Overwatch")
        except Exception as e:
            log.error("Restart error: %s", e)
            icon.notify(f"Restart failed: {e}", "Overwatch")

    def _on_status(self, icon, item):
        try:
            status = self.engine.get_status()
            today = sum(status.get("stats", {}).get("today", {}).values())
            msg = (
                f"{status['monitors']} monitors active\n"
                f"{today} events today\n"
                f"Dashboard: {self.engine.api.url}"
            )
            icon.notify(msg, "Overwatch")
        except Exception as e:
            icon.notify(f"Error: {e}", "Overwatch")

    def _on_exit(self, icon, item):
        import threading

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
