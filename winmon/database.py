"""SQLite event storage for Overwatch with dedup + live listeners."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


# Columns we expect on the events table — added idempotently by _migrate().
_EVENT_COLUMNS = [
    ("friendly_summary", "TEXT"),
    ("attack_tags", "TEXT"),       # JSON array of MITRE technique IDs
    ("parent_tree", "TEXT"),       # JSON array of ancestor names
    ("signature", "TEXT"),         # signed_ms | signed_3p | unsigned | unknown
    ("confidence", "INTEGER DEFAULT 0"),
    ("dedup_key", "TEXT"),
    ("dedup_count", "INTEGER DEFAULT 1"),
]


class EventDB:
    """Thread-safe SQLite event store with deduplication."""

    def __init__(self, db_path="winmon_events.db", dedup_window_seconds=60):
        self._path = str(db_path)
        self._local = threading.local()
        self._listeners = []
        self._dedup_window = timedelta(seconds=dedup_window_seconds)
        self._write_lock = threading.Lock()  # serialise writes across threads
        self._init_db()
        self._migrate()

    # ---- listener API -----------------------------------------------------

    def add_listener(self, callback):
        """Register a callback fired after each insert/update.

        callback(event_dict) — runs on the DB-writing thread (must be quick).
        event_dict includes 'is_update' (True if dedup updated an existing row).
        """
        self._listeners.append(callback)

    # ---- connection -------------------------------------------------------

    @property
    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                source TEXT,
                summary TEXT NOT NULL,
                details TEXT,
                alerted INTEGER DEFAULT 0,
                acknowledged INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
            CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);

            CREATE TABLE IF NOT EXISTS monitor_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated TEXT
            );
        """)
        self._conn.commit()

    def _migrate(self):
        """Add new columns idempotently."""
        cur = self._conn.execute("PRAGMA table_info(events)")
        existing = {row[1] for row in cur.fetchall()}
        for col_name, col_type in _EVENT_COLUMNS:
            if col_name not in existing:
                self._conn.execute(f"ALTER TABLE events ADD COLUMN {col_name} {col_type}")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_dedup_key ON events(dedup_key)"
        )
        self._conn.commit()

    # ---- write path -------------------------------------------------------

    def log_event(self, category, summary, details=None, severity="info",
                  source=None, alerted=False,
                  friendly_summary=None, attack_tags=None,
                  parent_tree=None, signature=None, confidence=0,
                  dedup_key=None):
        """Insert a new event or dedup against a recent one with the same key.

        Returns the event id. If `dedup_key` matches a row within the dedup
        window, that row is updated (count++, timestamp=now, severity merges
        upward) and its id is returned.
        """
        with self._write_lock:
            now = datetime.now().isoformat()
            attack_tags_json = json.dumps(attack_tags) if attack_tags else None
            parent_tree_json = json.dumps(parent_tree) if parent_tree else None

            is_update = False
            event_id = None
            dedup_count = 1

            if dedup_key:
                cutoff = (datetime.now() - self._dedup_window).isoformat()
                row = self._conn.execute(
                    "SELECT id, severity, dedup_count FROM events "
                    "WHERE dedup_key = ? AND timestamp >= ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (dedup_key, cutoff),
                ).fetchone()
                if row:
                    event_id = row["id"]
                    dedup_count = (row["dedup_count"] or 1) + 1
                    merged_sev = _max_severity(row["severity"], severity)
                    self._conn.execute(
                        "UPDATE events SET timestamp = ?, dedup_count = ?, "
                        "severity = ?, summary = ?, friendly_summary = ?, "
                        "details = ? WHERE id = ?",
                        (now, dedup_count, merged_sev, summary,
                         friendly_summary, details, event_id),
                    )
                    self._conn.commit()
                    is_update = True
                    severity = merged_sev

            if event_id is None:
                cursor = self._conn.execute(
                    """INSERT INTO events (
                           timestamp, category, severity, source, summary,
                           details, alerted, friendly_summary, attack_tags,
                           parent_tree, signature, confidence,
                           dedup_key, dedup_count
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (now, category, severity, source, summary, details,
                     int(alerted), friendly_summary, attack_tags_json,
                     parent_tree_json, signature, int(confidence),
                     dedup_key, 1),
                )
                self._conn.commit()
                event_id = cursor.lastrowid

            if self._listeners:
                event = {
                    "id": event_id, "timestamp": now, "category": category,
                    "severity": severity, "source": source, "summary": summary,
                    "details": details, "alerted": int(alerted),
                    "acknowledged": 0,
                    "friendly_summary": friendly_summary,
                    "attack_tags": attack_tags or [],
                    "parent_tree": parent_tree or [],
                    "signature": signature, "confidence": int(confidence),
                    "dedup_key": dedup_key, "dedup_count": dedup_count,
                    "is_update": is_update,
                }
                for cb in self._listeners:
                    try:
                        cb(event)
                    except Exception:
                        pass

            # Return (id, is_update) so callers can skip duplicate Telegram alerts.
            return event_id, is_update

    # ---- read path --------------------------------------------------------

    def get_events(self, category=None, severity=None, since=None, limit=100,
                   offset=0, unacknowledged_only=False, min_severity=None):
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"; params.append(category)
        if severity:
            query += " AND severity = ?"; params.append(severity)
        if min_severity:
            # ordered: info < warning < critical
            order_clause = "CASE severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END"
            query = query.replace("WHERE 1=1", f"WHERE ({order_clause}) >= ?")
            params.insert(0, _severity_rank(min_severity))
        if since:
            query += " AND timestamp >= ?"; params.append(since)
        if unacknowledged_only:
            query += " AND acknowledged = 0"
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_event_count(self, category=None, since=None):
        query = "SELECT COUNT(*) FROM events WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"; params.append(category)
        if since:
            query += " AND timestamp >= ?"; params.append(since)
        return self._conn.execute(query, params).fetchone()[0]

    def get_stats(self):
        today = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()

        stats = {}
        for label, since in [("today", today), ("last_hour", hour_ago), ("total", None)]:
            query = "SELECT category, COUNT(*) as cnt FROM events"
            params = []
            if since:
                query += " WHERE timestamp >= ?"; params.append(since)
            query += " GROUP BY category"
            rows = self._conn.execute(query, params).fetchall()
            stats[label] = {row["category"]: row["cnt"] for row in rows}

        # severity breakdown for today
        sev_rows = self._conn.execute(
            "SELECT severity, COUNT(*) AS cnt FROM events WHERE timestamp >= ? "
            "GROUP BY severity", (today,),
        ).fetchall()
        stats["severity_today"] = {row["severity"]: row["cnt"] for row in sev_rows}

        return stats

    def acknowledge_event(self, event_id):
        self._conn.execute(
            "UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,))
        self._conn.commit()

    def acknowledge_all(self, category=None):
        if category:
            self._conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE category = ?", (category,))
        else:
            self._conn.execute("UPDATE events SET acknowledged = 1")
        self._conn.commit()

    def cleanup(self, days=30, max_events=100000):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self._conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        count = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count > max_events:
            self._conn.execute(
                "DELETE FROM events WHERE id IN ("
                "SELECT id FROM events ORDER BY timestamp ASC LIMIT ?)",
                (count - max_events,))
        self._conn.commit()
        self._conn.execute("VACUUM")

    def set_state(self, key, value):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO monitor_state (key, value, updated) "
            "VALUES (?, ?, ?)", (key, value, now))
        self._conn.commit()

    def get_state(self, key, default=None):
        row = self._conn.execute(
            "SELECT value FROM monitor_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ---- helpers --------------------------------------------------------------

_SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


def _severity_rank(s):
    return _SEVERITY_RANK.get((s or "info").lower(), 1)


def _max_severity(a, b):
    return a if _severity_rank(a) >= _severity_rank(b) else b


def _row_to_dict(row):
    d = dict(row)
    for k in ("attack_tags", "parent_tree"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = []
        else:
            d[k] = []
    return d
