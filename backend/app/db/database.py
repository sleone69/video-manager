"""SQLite schema init and helper connection factory."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import settings

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS videos (
    video_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    duration_sec REAL NOT NULL DEFAULT 0,
    width       INTEGER,
    height      INTEGER,
    fps         REAL,
    codec       TEXT,
    upload_date TEXT NOT NULL,
    manifest_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stars (
    star_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    image_url  TEXT,
    bio        TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_stars (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    star_id  TEXT NOT NULL REFERENCES stars(star_id)  ON DELETE CASCADE,
    PRIMARY KEY (video_id, star_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id         TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'queued',
    video_id       TEXT,
    message        TEXT NOT NULL DEFAULT '',
    total_chunks   INTEGER NOT NULL DEFAULT 0,
    uploaded_chunks INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    bytes_per_sec  REAL,
    eta_sec        INTEGER,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_checkpoints (
    job_id     TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    phase      TEXT NOT NULL,   -- 'meta', 'video_info', 'chunks_created', 'chunk_N'
    data       TEXT NOT NULL,   -- JSON blob
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, phase)
);

CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
    video_id UNINDEXED,
    name,
    description,
    content='videos',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS videos_ai AFTER INSERT ON videos BEGIN
    INSERT INTO videos_fts(rowid, video_id, name, description)
    VALUES (new.rowid, new.video_id, new.name, new.description);
END;

CREATE TRIGGER IF NOT EXISTS videos_ad AFTER DELETE ON videos BEGIN
    INSERT INTO videos_fts(videos_fts, rowid, video_id, name, description)
    VALUES ('delete', old.rowid, old.video_id, old.name, old.description);
END;

CREATE TRIGGER IF NOT EXISTS videos_au AFTER UPDATE ON videos BEGIN
    INSERT INTO videos_fts(videos_fts, rowid, video_id, name, description)
    VALUES ('delete', old.rowid, old.video_id, old.name, old.description);
    INSERT INTO videos_fts(rowid, video_id, name, description)
    VALUES (new.rowid, new.video_id, new.name, new.description);
END;
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(_DDL)
    # Idempotent migrations for columns added after initial schema deployment
    for col, typedef in [
        ("bytes_per_sec", "REAL"),
        ("eta_sec", "INTEGER"),
    ]:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()
    conn.close()
