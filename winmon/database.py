"""SQLite event storage for Overwatch."""

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


class EventDB:
    """Thread-safe SQLite database for security events."""

    def __init__(self, db_path="winmon_events.db"):
        self._path = str(db_path)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self):
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
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

    def log_event(self, category, summary, details=None, severity="info",
                  source=None, alerted=False):
        """Insert a new security event."""
        now = datetime.now().isoformat()
        cursor = self._conn.execute(
            """INSERT INTO events (timestamp, category, severity, source, summary, details, alerted)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, category, severity, source, summary, details, int(alerted))
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_events(self, category=None, severity=None, since=None, limit=100,
                   offset=0, unacknowledged_only=False):
        """Query events with optional filters."""
        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if unacknowledged_only:
            query += " AND acknowledged = 0"

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_event_count(self, category=None, since=None):
        """Count events with optional filters."""
        query = "SELECT COUNT(*) FROM events WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        return self._conn.execute(query, params).fetchone()[0]

    def get_stats(self):
        """Get summary statistics."""
        today = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()

        stats = {}
        for label, since in [("today", today), ("last_hour", hour_ago), ("total", None)]:
            query = "SELECT category, COUNT(*) as cnt FROM events"
            params = []
            if since:
                query += " WHERE timestamp >= ?"
                params.append(since)
            query += " GROUP BY category"
            rows = self._conn.execute(query, params).fetchall()
            stats[label] = {row["category"]: row["cnt"] for row in rows}

        return stats

    def acknowledge_event(self, event_id):
        """Mark an event as acknowledged."""
        self._conn.execute(
            "UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,)
        )
        self._conn.commit()

    def acknowledge_all(self, category=None):
        """Acknowledge all events, optionally filtered by category."""
        if category:
            self._conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE category = ?",
                (category,)
            )
        else:
            self._conn.execute("UPDATE events SET acknowledged = 1")
        self._conn.commit()

    def cleanup(self, days=30, max_events=100000):
        """Remove old events to manage database size."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self._conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))

        count = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count > max_events:
            self._conn.execute(
                """DELETE FROM events WHERE id IN (
                    SELECT id FROM events ORDER BY timestamp ASC LIMIT ?
                )""",
                (count - max_events,)
            )
        self._conn.commit()
        self._conn.execute("VACUUM")

    def set_state(self, key, value):
        """Store monitor state (for dedup, checkpoints, etc.)."""
        now = datetime.now().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO monitor_state (key, value, updated)
               VALUES (?, ?, ?)""",
            (key, value, now)
        )
        self._conn.commit()

    def get_state(self, key, default=None):
        """Retrieve stored monitor state."""
        row = self._conn.execute(
            "SELECT value FROM monitor_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
