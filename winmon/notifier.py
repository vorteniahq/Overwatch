"""Telegram notification system with silent hours support."""

import logging
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import json
from datetime import datetime
from queue import Queue, Empty

log = logging.getLogger("winmon.notifier")


class TelegramNotifier:
    """Sends alerts via Telegram Bot API with silent hours and rate limiting."""

    API_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, config):
        self._config = config
        self._queue = Queue()
        self._running = False
        self._thread = None
        self._rate_limit_interval = 1.0  # seconds between messages

    def start(self):
        """Start the notification dispatch thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()
        log.info("Telegram notifier started")

    def stop(self):
        """Stop the dispatch thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Telegram notifier stopped")

    def send_alert(self, category, summary, details=None, severity="info"):
        """Queue an alert for sending (respects silent hours)."""
        if not self._config.get("telegram", "enabled"):
            return

        if self._is_silent():
            log.debug("Silent hours active, suppressing alert: %s", summary)
            return

        emoji = {"critical": "!!", "warning": "!", "info": "i"}.get(severity, "i")

        text = f"[{emoji}] Overwatch Alert\n"
        text += f"Category: {category}\n"
        text += f"Severity: {severity.upper()}\n"
        text += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        text += summary
        if details:
            text += f"\n\n{details[:500]}"

        self._queue.put(text)

    def send_test(self):
        """Send a test message immediately (ignoring silent hours)."""
        self._queue.put("Overwatch Test - Telegram notifications are working!")

    def _is_silent(self):
        """Check if current time falls within silent hours."""
        silent = self._config.get("silent_hours")
        if not silent or not silent.get("enabled"):
            return False

        now = datetime.now()
        weekday = now.weekday()  # 0=Monday

        if weekday not in silent.get("days", []):
            return False

        start = now.replace(
            hour=silent.get("start_hour", 7),
            minute=silent.get("start_minute", 0),
            second=0, microsecond=0
        )
        end = now.replace(
            hour=silent.get("end_hour", 17),
            minute=silent.get("end_minute", 0),
            second=0, microsecond=0
        )

        return start <= now < end

    def _dispatch_loop(self):
        """Process queued messages with rate limiting."""
        while self._running:
            try:
                text = self._queue.get(timeout=1)
            except Empty:
                continue

            try:
                self._send_telegram(text)
            except Exception as e:
                log.error("Failed to send Telegram message: %s", e)

            time.sleep(self._rate_limit_interval)

    def _send_telegram(self, text):
        """Actually send via Telegram API."""
        token = self._config.get("telegram", "bot_token")
        chat_id = self._config.get("telegram", "chat_id")

        if not token or not chat_id:
            log.warning("Telegram not configured (missing token or chat_id)")
            return

        url = self.API_URL.format(token=token, method="sendMessage")
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if not result.get("ok"):
                    log.error("Telegram API error: %s", result)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error("Telegram HTTP %d: %s", e.code, body)
        except urllib.error.URLError as e:
            log.error("Telegram connection error: %s", e.reason)

