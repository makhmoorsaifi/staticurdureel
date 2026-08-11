"""
database.py
-----------
SQLite persistence layer. This is the single source of truth for
every reel's state. The app can be killed at any point and, on
restart, queue_manager.py resumes purely from what's in this DB —
never from position #1, never re-publishing anything with a
media_id already recorded.

Run this file directly to (re)create the schema:
    python database.py
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Iterable, Any

from config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    filename            TEXT NOT NULL,
    filepath            TEXT NOT NULL,
    file_hash           TEXT NOT NULL UNIQUE,   -- duplicate-protection fingerprint

    caption             TEXT DEFAULT '',
    hashtags            TEXT DEFAULT '',         -- space-separated

    scheduled_at        TEXT,                    -- ISO8601 datetime, assigned by scheduler.py
    status              TEXT NOT NULL DEFAULT 'pending',
                        -- pending | validated | hosted | container_created |
                        -- scheduled | publishing | published | failed | skipped

    public_video_url    TEXT,                    -- set once uploader.py hosts the file
    ig_container_id     TEXT,                    -- creation_id from /media
    ig_media_id         TEXT,                    -- final published media id

    error_message       TEXT,
    attempt_count        INTEGER NOT NULL DEFAULT 0,

    created_at          TEXT NOT NULL,
    upload_timestamp    TEXT,                    -- when container was created
    publish_timestamp   TEXT                     -- when media_publish succeeded
);

CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(status);
CREATE INDEX IF NOT EXISTS idx_reels_scheduled_at ON reels(scheduled_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reels_hash ON reels(file_hash);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    level       TEXT NOT NULL,      -- INFO | WARNING | ERROR
    reel_id     INTEGER,
    message     TEXT NOT NULL,
    FOREIGN KEY (reel_id) REFERENCES reels(id)
);

CREATE TABLE IF NOT EXISTS app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""

VALID_STATUSES = {
    "pending", "validated", "hosted", "container_created",
    "scheduled", "publishing", "published", "failed", "skipped",
}


@contextmanager
def get_connection(db_path: Optional[str] = None):
    path = db_path or load_config().database_path
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # crash-safer, allows concurrent GUI reads
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_reel(conn, filename: str, filepath: str, file_hash: str,
                 caption: str = "", hashtags: str = "") -> Optional[int]:
    """Insert a new reel row. Returns None (no insert) if file_hash already
    exists — this IS the duplicate-protection check, enforced at the DB
    level via the unique index, not just in application code."""
    cur = conn.execute(
        "SELECT id FROM reels WHERE file_hash = ?", (file_hash,)
    )
    existing = cur.fetchone()
    if existing:
        return None
    cur = conn.execute(
        """INSERT INTO reels (filename, filepath, file_hash, caption, hashtags,
                               status, created_at, attempt_count)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, 0)""",
        (filename, filepath, file_hash, caption, hashtags, datetime.utcnow().isoformat()),
    )
    return cur.lastrowid


def update_status(conn, reel_id: int, status: str, error_message: Optional[str] = None,
                   **extra_fields: Any) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    fields = {"status": status}
    if error_message is not None:
        fields["error_message"] = error_message
    fields.update(extra_fields)

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [reel_id]
    conn.execute(f"UPDATE reels SET {set_clause} WHERE id = ?", values)


def get_reels_by_status(conn, status: str) -> Iterable[sqlite3.Row]:
    return conn.execute("SELECT * FROM reels WHERE status = ? ORDER BY id", (status,)).fetchall()


def get_next_due(conn, now_iso: str) -> Optional[sqlite3.Row]:
    """The next scheduled reel whose time has arrived — this is what
    the publisher polls for, so a crash mid-queue never causes a skip
    or a duplicate."""
    return conn.execute(
        """SELECT * FROM reels
           WHERE status = 'scheduled' AND scheduled_at <= ?
           ORDER BY scheduled_at ASC LIMIT 1""",
        (now_iso,),
    ).fetchone()


def log_event(conn, level: str, message: str, reel_id: Optional[int] = None) -> None:
    conn.execute(
        "INSERT INTO run_log (timestamp, level, reel_id, message) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), level, reel_id, message),
    )


def counts_by_status(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) as n FROM reels GROUP BY status").fetchall()
    return {row["status"]: row["n"] for row in rows}


if __name__ == "__main__":
    init_db()
    print("Database initialized / verified at:", load_config().database_path)
