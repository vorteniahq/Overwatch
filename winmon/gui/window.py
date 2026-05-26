"""Native dashboard window powered by PyWebView + WebView2.

The window loads the embedded FastAPI server's URL, so all dashboard HTML/CSS/JS
is reused unchanged. Clicking the close button hides instead of destroys, so the
app stays alive in the tray. The tray's "Open Dashboard" / "Settings" handlers
call show() / navigate() on this object — those methods are thread-safe.
"""

import logging
import os
import threading
from typing import Optional

log = logging.getLogger("winmon.gui.window")


class DashboardWindow:
    """Hidden-on-close native window around the dashboard URL."""

    def __init__(self, url: str, title: str = "Overwatch"):
        self._url = url.rstrip("/") + "/"
        self._title = title
        self._window = None
        self._webview = None
        self._ready = threading.Event()

    @property
    def available(self) -> bool:
        return self._window is not None

    def create(self):
        """Instantiate the window object (does not run the loop)."""
        import webview
        self._webview = webview
        self._window = webview.create_window(
            self._title,
            self._url,
            width=1380,
            height=900,
            min_size=(960, 600),
            hidden=True,
            background_color="#0a0d12",
            confirm_close=False,
        )
        # Hide-on-close: cancel the close event and hide instead
        self._window.events.closing += self._on_closing
        self._window.events.loaded += self._on_loaded
        log.info("Dashboard window created (hidden)")

    def _on_closing(self):
        try:
            self._window.hide()
        except Exception:
            log.exception("Failed to hide window")
        return False  # cancel actual close

    def _on_loaded(self):
        self._ready.set()

    def run_blocking(self):
        """Run the WebView2 event loop on the calling thread (must be main)."""
        if not self._webview:
            raise RuntimeError("create() must be called first")

        storage_path = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "Overwatch", "webview",
        )
        os.makedirs(storage_path, exist_ok=True)

        self._webview.start(
            gui="edgechromium",
            storage_path=storage_path,
            debug=False,
        )

    # ---- Thread-safe controls (called from tray thread) ----------------

    def show(self, path: str = "/"):
        """Show the window and always reload the URL — guarantees fresh assets."""
        if not self._window:
            return
        target = self._url.rstrip("/") + path
        try:
            # Always navigate. Combined with the no-cache headers on /, /settings,
            # and /static/*, this guarantees every open shows the latest UI.
            self._window.load_url(target)
            self._window.show()
            try:
                self._window.restore()
            except Exception:
                pass
        except Exception as e:
            log.error("Failed to show dashboard window: %s", e)

    def hide(self):
        try:
            if self._window:
                self._window.hide()
        except Exception:
            pass

    def destroy(self):
        try:
            if self._window:
                self._window.destroy()
        except Exception:
            pass
