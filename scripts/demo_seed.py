"""Build a self-contained DEMO data dir for screenshots and demo videos.

Creates <out>/config.json (all monitors disabled, Telegram off, port 7374,
neutral machine name) and <out>/winmon_events.db seeded with a realistic,
clearly-mock event story: a workday where someone unlocked the machine over
lunch, plugged in a USB stick, and an RDP session appeared in the afternoon.

Timestamps are computed relative to "now" at seed time, so the feed always
reads fresh. Run it, then point scripts/demo_server.py at the same dir.

    python scripts/demo_seed.py [out_dir]     # default: ./demo-data

Pure stdlib + sqlite; runs on any OS. This is DEMO data for marketing
captures, never mixed with a real install's database.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data")
OUT.mkdir(parents=True, exist_ok=True)

# ---- config: monitors off (no real events), API on 7374, no Telegram ----
config = {
    "telegram": {"bot_token": "", "chat_id": "", "enabled": False},
    "silent_hours": {"enabled": False, "start_hour": 7, "start_minute": 0,
                     "end_hour": 17, "end_minute": 0, "days": [0, 1, 2, 3, 4]},
    "monitors": {
        name: {"enabled": False, "alert": False, "description": ""}
        for name in ["session", "login", "process", "usb", "rdp",
                     "network", "power", "filesystem"]
    },
    "database": {"path": "winmon_events.db", "max_events": 100000, "cleanup_days": 30},
    "general": {"machine_name": "FRONT DESK", "display_mode": "basic",
                "log_level": "INFO", "start_minimized": True,
                "autostart": False, "away_mode": False},
    "presence": {"enabled": True, "mode": "auto", "idle_threshold_seconds": 300},
    "api": {"host": "127.0.0.1", "port": 7374},
    "updates": {"enabled": False, "check_url": ""},
}
(OUT / "config.json").write_text(json.dumps(config, indent=2))

# ---- the story, oldest first: (minutes_ago, category, severity, alerted,
#      friendly summary, details, attack_tags) ----
now = datetime.now()
STORY = [
    (492, "login",      "info",     0, "Someone signed in to this computer.",
     "Interactive logon, console session.", None),
    (491, "network",    "info",     0, "Connected to Wi-Fi network SHOP-5G.",
     "New gateway 192.168.1.1.", None),
    (205, "session",    "info",     0, "Workstation locked.",
     "Console session locked.", None),
    (172, "session",    "warning",  1, "Workstation unlocked.",
     "Console session unlocked.", None),
    (171, "usb",        "warning",  1, "A USB drive was plugged in: SanDisk Ultra USB 3.0.",
     "VID_0781 PID_5581, removable storage.", None),
    (168, "filesystem", "warning",  0, "Files changed in Documents: 3 files.",
     "3 files modified under Documents in 2 minutes.", None),
    (166, "usb",        "info",     0, "USB drive removed: SanDisk Ultra USB 3.0.",
     "VID_0781 PID_5581 disconnected.", None),
    (165, "session",    "info",     0, "Workstation locked.",
     "Console session locked.", None),
    (96,  "rdp",        "critical", 1, "Remote desktop session started from 10.0.0.44.",
     "RDP logon type 10, source 10.0.0.44.", ["T1021.001"]),
    (94,  "process",    "warning",  0, "PowerShell started with an encoded command.",
     "powershell.exe -EncodedCommand, parent: svchost.exe.", ["T1059.001"]),
    (82,  "rdp",        "info",     0, "Remote desktop session ended.",
     "Session from 10.0.0.44 disconnected.", None),
    (12,  "session",    "warning",  1, "Workstation unlocked.",
     "Console session unlocked.", None),
    (9,   "usb",        "info",     0, "A USB device was plugged in: Logitech USB Receiver.",
     "VID_046D, HID input device.", None),
]

db_path = OUT / "winmon_events.db"
if db_path.exists():
    db_path.unlink()

conn = sqlite3.connect(db_path)
conn.executescript("""
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        source TEXT,
        summary TEXT NOT NULL,
        details TEXT,
        alerted INTEGER DEFAULT 0,
        acknowledged INTEGER DEFAULT 0,
        friendly_summary TEXT,
        attack_tags TEXT,
        parent_tree TEXT,
        signature TEXT,
        confidence INTEGER DEFAULT 0,
        dedup_key TEXT,
        dedup_count INTEGER DEFAULT 1
    );
    CREATE INDEX idx_events_timestamp ON events(timestamp);
    CREATE INDEX idx_events_category ON events(category);
    CREATE INDEX idx_events_severity ON events(severity);
    CREATE INDEX idx_events_dedup_key ON events(dedup_key);
    CREATE TABLE monitor_state (key TEXT PRIMARY KEY, value TEXT, updated TEXT);
""")
for minutes_ago, cat, sev, alerted, friendly, details, tags in STORY:
    ts = (now - timedelta(minutes=minutes_ago)).isoformat()
    conn.execute(
        "INSERT INTO events (timestamp, category, severity, source, summary,"
        " details, alerted, friendly_summary, attack_tags)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, cat, sev, f"{cat}_monitor", friendly, details, alerted, friendly,
         json.dumps(tags) if tags else None),
    )
conn.commit()
conn.close()

print(f"Seeded {len(STORY)} demo events into {db_path}")
print(f"Config written to {OUT / 'config.json'} (port 7374, machine 'FRONT DESK')")
