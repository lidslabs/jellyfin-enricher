"""SQLite persistence for permanent skips and download history.

Session-scoped skips (skip-just-this-round) live in memory only and reset
on each rescan; they intentionally do not persist.
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS permanent_skips (
    jellyfin_id  TEXT NOT NULL,
    extras_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    year         INTEGER,
    reason       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (jellyfin_id, extras_type)
);

CREATE TABLE IF NOT EXISTS download_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    jellyfin_id  TEXT NOT NULL,
    extras_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    youtube_id   TEXT NOT NULL,
    target_path  TEXT NOT NULL,
    success      INTEGER NOT NULL,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_history_jellyfin
    ON download_history(jellyfin_id, extras_type);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _db_path() -> str:
    return str(settings.data_dir / "enricher.db")


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_db_path()) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- permanent skips ---

def add_permanent_skip(
    jellyfin_id: str,
    extras_type: str,
    title: str,
    year: int | None,
    reason: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO permanent_skips
               (jellyfin_id, extras_type, title, year, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (jellyfin_id, extras_type, title, year, reason),
        )


def remove_permanent_skip(jellyfin_id: str, extras_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM permanent_skips WHERE jellyfin_id = ? AND extras_type = ?",
            (jellyfin_id, extras_type),
        )


def get_permanent_skip_ids(extras_type: str) -> set[str]:
    """Return the set of jellyfin_ids permanently skipped for this extras_type."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT jellyfin_id FROM permanent_skips WHERE extras_type = ?",
            (extras_type,),
        ).fetchall()
        return {r["jellyfin_id"] for r in rows}


def list_permanent_skips() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT jellyfin_id, extras_type, title, year, reason, created_at
               FROM permanent_skips ORDER BY title"""
        ).fetchall()
        return [dict(r) for r in rows]


# --- history ---

def record_download(
    jellyfin_id: str,
    extras_type: str,
    title: str,
    youtube_id: str,
    target_path: str,
    success: bool,
    error: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO download_history
               (jellyfin_id, extras_type, title, youtube_id, target_path, success, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                jellyfin_id,
                extras_type,
                title,
                youtube_id,
                target_path,
                1 if success else 0,
                error,
            ),
        )


# --- runtime settings (key/value) ---

def get_setting(key: str) -> str | None:
    """Return the DB-stored value for a setting key, or None if absent."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """Insert or replace a setting. Empty string is stored as-is (use
    delete_setting to fall back to env)."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = datetime('now')""",
            (key, value),
        )


def delete_setting(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def list_settings() -> dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
