"""Monitor network changes — Wi-Fi, IP/gateway, and outbound connections.

Snoop-detection angle:
- Wi-Fi network changed  -> laptop may have been moved, or a rogue AP appeared
- New IP / gateway       -> joined a different network (ethernet, tether, dock, VPN)
- Wi-Fi connect/disconnect
- New outbound public connection -> possible exfiltration / phone-home (advanced)
"""

import ipaddress
import logging
import socket
import subprocess
import threading
import time

from winmon.intel import friendly_summary, maybe_escalate

log = logging.getLogger("winmon.monitors.network")

POLL_INTERVAL = 8.0
# Hide the console window when shelling out to netsh under pythonw.exe
_NO_WINDOW = 0x08000000


class NetworkMonitor:
    """Tracks Wi-Fi SSID, local IPs, and new outbound connections."""

    CATEGORY = "network"

    def __init__(self, config, database, notifier):
        self._config = config
        self._db = database
        self._notifier = notifier
        self._running = False
        self._thread = None
        self._seen_outbound = set()  # remote public IPs already reported this run

    def start(self):
        if not self._config.get("monitors", "network", "enabled"):
            log.info("Network monitor disabled")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop, name="overwatch-network", daemon=True
        )
        self._thread.start()
        log.info("Network monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ---- state probes -----------------------------------------------------

    def _get_ssid(self):
        """Current Wi-Fi SSID via netsh, or None if not on Wi-Fi."""
        try:
            out = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=8,
                creationflags=_NO_WINDOW,
            )
            for line in out.stdout.splitlines():
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0].strip().lower() == "ssid":
                    return parts[1].strip() or None
        except Exception:
            pass
        return None

    def _get_ipv4s(self):
        try:
            import psutil
            ips = set()
            for _, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == socket.AF_INET and not a.address.startswith("127."):
                        ips.add(a.address)
            return frozenset(ips)
        except Exception:
            return frozenset()

    @staticmethod
    def _is_public(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
            return not (addr.is_private or addr.is_loopback or
                        addr.is_link_local or addr.is_multicast or addr.is_reserved)
        except ValueError:
            return False

    def _get_outbound_public(self):
        """Set of public remote IPs we currently have ESTABLISHED connections to."""
        try:
            import psutil
            remotes = set()
            for c in psutil.net_connections(kind="inet"):
                if c.status == "ESTABLISHED" and c.raddr:
                    ip = c.raddr.ip
                    if self._is_public(ip):
                        remotes.add(ip)
            return remotes
        except Exception:
            return set()

    # ---- main loop --------------------------------------------------------

    def _watch_loop(self):
        prev_ssid = self._get_ssid()
        prev_ips = self._get_ipv4s()
        self._seen_outbound = self._get_outbound_public()  # baseline, don't alert
        log.info("Network monitor baseline: ssid=%s ips=%d outbound=%d",
                 prev_ssid, len(prev_ips), len(self._seen_outbound))

        while self._running:
            try:
                ssid = self._get_ssid()
                ips = self._get_ipv4s()

                # Wi-Fi connect / disconnect / change
                if ssid != prev_ssid:
                    if prev_ssid and not ssid:
                        self._emit("wifi_disconnect", f"Wi-Fi disconnected from {prev_ssid}",
                                   f"Previous SSID: {prev_ssid}", "info")
                    elif ssid and not prev_ssid:
                        self._emit("wifi_connect", f"Wi-Fi connected to {ssid}",
                                   f"SSID: {ssid}", "warning")
                    else:
                        self._emit("wifi_change", f"Wi-Fi network changed to {ssid}",
                                   f"Previous: {prev_ssid}\nNow: {ssid}", "warning")
                    prev_ssid = ssid

                # New IP addresses (joined a different network)
                new_ips = ips - prev_ips
                if new_ips and prev_ips:  # ignore the very first population
                    self._emit("ip_change", "This computer joined a new network",
                               f"New address(es): {', '.join(sorted(new_ips))}", "warning")
                prev_ips = ips

                # New outbound public connections (advanced; conservative)
                if self._config.get("monitors", "network", "watch_outbound"):
                    current = self._get_outbound_public()
                    fresh = current - self._seen_outbound
                    for ip in list(fresh)[:5]:  # cap to avoid floods
                        self._emit("outbound", f"New outbound connection to {ip}",
                                   f"Remote IP: {ip}", "info", dedup=f"net:out:{ip}",
                                   alert=False)
                    self._seen_outbound |= current

            except Exception as e:
                log.error("Network monitor error: %s", e)

            for _ in range(int(POLL_INTERVAL * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    # ---- emit -------------------------------------------------------------

    def _emit(self, kind, summary, details, severity, dedup=None, alert=True):
        severity, escalated = maybe_escalate(self._config, self.CATEGORY, severity)
        friendly = friendly_summary(self.CATEGORY, summary=summary, details=details,
                                    analysis={"kind": kind})
        is_alert = alert and (escalated or severity in ("warning", "critical"))
        _id, is_update = self._db.log_event(
            self.CATEGORY, summary, details, severity,
            source="netmon", alerted=is_alert,
            friendly_summary=friendly,
            dedup_key=dedup or f"net:{kind}",
        )
        if is_alert and not is_update and self._config.get("monitors", "network", "alert"):
            self._notifier.send_alert(self.CATEGORY, friendly or summary, details, severity)
        log.info("Network event: %s (%s)", kind, severity)
