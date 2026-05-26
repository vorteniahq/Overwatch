"""Plain-English summary generation for the basic display mode.

Tone goal: snoop-detection. Every summary should answer "who/what touched
my computer, and when" — not "what did this process do." Examples:
- "Someone signed in to this computer" (not "Logon session created, type 2")
- "A USB drive was plugged in" (not "USB device CONNECTED: VID/PID")
- "Someone connected to this computer remotely" (not "RDP session established")
"""

import os
from datetime import datetime
from typing import Optional

# ---- format helpers -------------------------------------------------------

def _short_path(path: Optional[str]) -> str:
    """Return a user-friendly version of a path (no drive prefix, max 2 segments)."""
    if not path:
        return ""
    parts = path.replace("/", "\\").rstrip("\\").split("\\")
    if len(parts) <= 2:
        return path
    return "…\\" + "\\".join(parts[-2:])


def _friendly_app_name(exe_name: str) -> str:
    """Map exe filename to a recognisable label."""
    n = (exe_name or "").lower()
    return {
        "powershell.exe": "PowerShell",
        "pwsh.exe": "PowerShell",
        "cmd.exe": "Command Prompt",
        "explorer.exe": "Windows Explorer",
        "winword.exe": "Microsoft Word",
        "excel.exe": "Microsoft Excel",
        "outlook.exe": "Outlook",
        "powerpnt.exe": "PowerPoint",
        "chrome.exe": "Chrome",
        "msedge.exe": "Microsoft Edge",
        "firefox.exe": "Firefox",
        "wscript.exe": "Windows Script Host",
        "cscript.exe": "Windows Script Host",
        "mshta.exe": "Microsoft HTML Application Host",
        "regsvr32.exe": "regsvr32",
        "rundll32.exe": "rundll32",
        "certutil.exe": "certutil",
        "teamviewer.exe": "TeamViewer",
        "anydesk.exe": "AnyDesk",
        "mstsc.exe": "Remote Desktop",
    }.get(n, exe_name)


def _origin_phrase(parent_tree: list) -> str:
    """Build a human phrase describing what launched this process."""
    if not parent_tree:
        return "by an unknown program"
    immediate = _friendly_app_name(parent_tree[0])
    # If the chain shows an Office app, name it explicitly — it's a classic vector
    office_apps = {"WINWORD.EXE", "EXCEL.EXE", "OUTLOOK.EXE", "POWERPNT.EXE"}
    for name in parent_tree:
        if name.upper() in office_apps:
            return f"by {_friendly_app_name(name)} (this is unusual)"
    return f"by {immediate}"


# ---- per-category generators ---------------------------------------------

def _friendly_process(*, name: str, exe: Optional[str], analysis: dict) -> Optional[str]:
    """Plain-English description for a process event. Returns None for benign noise."""
    pretty = _friendly_app_name(name)
    origin = _origin_phrase(analysis.get("parent_tree", []))
    confidence = analysis.get("confidence", 0)
    top_reason = analysis.get("top_reason") or ""
    signing = analysis.get("signature", "unknown")

    if confidence >= 70:
        if top_reason:
            return f"Suspicious activity - {pretty} ran with {top_reason}, started {origin}."
        return f"Suspicious {pretty} activity detected, started {origin}."

    if confidence >= 30:
        if top_reason:
            return f"{pretty} ran with {top_reason} ({origin})."
        if signing == "unsigned_or_unknown" and exe:
            return f"Unsigned program {pretty} ({_short_path(exe)}) ran, started {origin}."
        return f"{pretty} ran ({origin})."

    # Below the warning threshold: not interesting for basic mode
    return None


def _friendly_login(*, summary: str, details: Optional[str], analysis: Optional[dict] = None) -> str:
    s = summary.lower()
    analysis = analysis or {}
    logon_type = analysis.get("logon_type")
    user = analysis.get("username")

    if "fail" in s or "failed" in s:
        return "Someone tried to sign in and failed."

    if "logon" in s or "logged on" in s or "login" in s:
        # Pull username from analysis or details
        if not user and details:
            for line in details.splitlines():
                if line.lower().startswith("user"):
                    user = line.split(":", 1)[-1].strip()
                    break
        # Logon-type-specific phrasing
        if logon_type == 10:
            return f"Someone connected remotely as {user or 'an unknown user'}."
        if logon_type == 11:
            return f"{user or 'A cached account'} signed in (offline credentials)."
        if user and user != "UNKNOWN":
            return f"{user} signed in to this computer."
        return "Someone signed in to this computer."

    if "logoff" in s or "logout" in s or "session ended" in s:
        return "Someone signed out."
    return summary


def _friendly_usb(*, summary: str) -> str:
    s = summary.lower()
    if "insert" in s or "added" in s or "connect" in s:
        return "A USB device was plugged in to this computer."
    if "remov" in s or "disconnect" in s:
        return "A USB device was unplugged."
    return summary


def _friendly_rdp(*, summary: str, details: Optional[str]) -> str:
    s = summary.lower()
    if "teamviewer" in s:
        return "Someone may be controlling this computer with TeamViewer."
    if "anydesk" in s:
        return "Someone may be controlling this computer with AnyDesk."
    if "vnc" in s or "rustdesk" in s or "splashtop" in s or "logmein" in s:
        return "A remote-control program is running on this computer."
    if "remote access detected" in s:
        return "Remote-control software started running."
    if "active rdp connection" in s:
        return "Someone is connected to this computer via Remote Desktop right now."
    if "rdp" in s and ("connection" in s or "session" in s):
        return "Someone connected to this computer via Remote Desktop."
    if "fail" in s:
        return "Someone tried to connect remotely and failed."
    return summary


def _friendly_filesystem(*, summary: str, details: Optional[str]) -> str:
    s = summary.lower()
    # Try to identify which user folder was touched
    folder = ""
    if details:
        for line in details.splitlines():
            low = line.lower()
            if "documents" in low: folder = "Documents"; break
            if "desktop"   in low: folder = "Desktop";   break
            if "downloads" in low: folder = "Downloads"; break
            if "pictures"  in low: folder = "Pictures";  break
    where = f" in {folder}" if folder else " in a watched folder"

    if "created" in s or "new file" in s:
        return f"A new file appeared{where}."
    if "modified" in s:
        return f"A file was modified{where}."
    if "deleted" in s:
        return f"A file was deleted{where}."
    return summary


def _friendly_system(*, summary: str) -> str:
    s = summary.lower()
    if "started" in s:
        return "Overwatch is now monitoring this computer."
    if "stopped" in s:
        return "Overwatch monitoring has stopped."
    if "paused" in s:
        return "Monitoring is paused."
    if "resumed" in s:
        return "Monitoring resumed."
    if "restart" in s:
        return "Monitors were restarted."
    return summary


# ---- top-level dispatch --------------------------------------------------

def friendly_summary(category: str, *, summary: str = "", details: Optional[str] = None,
                     name: Optional[str] = None, exe: Optional[str] = None,
                     analysis: Optional[dict] = None) -> Optional[str]:
    """Generate the plain-English summary for an event.

    Returns None for events too benign to surface in basic mode.
    """
    cat = (category or "").lower()
    if cat == "process":
        return _friendly_process(name=name or "", exe=exe, analysis=analysis or {})
    if cat == "login":
        return _friendly_login(summary=summary, details=details, analysis=analysis)
    if cat == "usb":
        return _friendly_usb(summary=summary)
    if cat == "rdp":
        return _friendly_rdp(summary=summary, details=details)
    if cat == "filesystem":
        return _friendly_filesystem(summary=summary, details=details)
    if cat == "session":
        return _friendly_session(summary=summary, analysis=analysis or {})
    if cat == "network":
        return _friendly_network(summary=summary, analysis=analysis or {})
    if cat == "power":
        return _friendly_power(summary=summary, analysis=analysis or {})
    if cat == "system":
        return _friendly_system(summary=summary)
    return summary


def _friendly_network(*, summary: str, analysis: dict) -> str:
    kind = analysis.get("kind", "")
    s = summary.lower()
    if kind == "wifi_change" or "network changed" in s:
        net = summary.split("to", 1)[-1].strip() if "to" in summary else ""
        return f"This computer switched to a different Wi-Fi network{(' (' + net + ')') if net else ''}."
    if kind == "wifi_connect" or "connected to" in s:
        net = summary.split("to", 1)[-1].strip() if "to" in summary else ""
        return f"This computer connected to Wi-Fi{(' (' + net + ')') if net else ''}."
    if kind == "wifi_disconnect" or "disconnected" in s:
        return "This computer disconnected from Wi-Fi."
    if kind == "ip_change" or "joined a new network" in s:
        return "This computer joined a different network."
    if kind == "outbound":
        return summary  # advanced-only, leave technical
    return summary


def _friendly_power(*, summary: str, analysis: dict) -> str:
    s = summary.lower()
    if "unplugged" in s or "on battery" in s:
        return "The charger was unplugged - the laptop may be on the move."
    if "plugged in" in s or "on ac" in s or "charging" in s:
        return "The laptop was plugged in to power."
    if "lid open" in s or "opened" in s:
        return "The laptop lid was opened."
    if "lid clos" in s or "closed" in s:
        return "The laptop lid was closed."
    if "low battery" in s:
        return "The laptop battery is running low."
    return summary


def _friendly_session(*, summary: str, analysis: dict) -> str:
    s = summary.lower()
    user = analysis.get("username") or ""
    user_suffix = f" by {user}" if user and user != "UNKNOWN" else ""
    if "unlock" in s:
        return f"The computer was unlocked{user_suffix}."
    if "lock" in s:
        return f"The computer was locked{user_suffix}."
    return summary
