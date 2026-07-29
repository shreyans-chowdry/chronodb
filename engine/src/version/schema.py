"""
ChronoDB MVP Version Engine — SQLite-backed Schema

This module initializes the SQLite database with the version-control metadata
tables required for the MVP: commits, branches, and row_versions.

NOTE: This SQLite scaffold is explicitly throwaway infrastructure — it will be
replaced by the custom page-based storage engine in Phase 2 (see Blueprint §19).
"""

import sqlite3
import hashlib
import time
from typing import Optional


# Default database path (can be overridden or use ":memory:" for tests)
DEFAULT_DB_PATH = "chronodb.sqlite"


def _compute_hash(*parts: str) -> str:
    """Compute a SHA-256 hash from concatenated string parts (Git-style content addressing)."""
    payload = "|".join(str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Initialize the ChronoDB SQLite scaffold database.

    Creates the metadata tables (commits, branches, row_versions) if they don't
    exist, and seeds the 'main' branch with an initial empty commit.

    Args:
        db_path: Path to the SQLite database file, or ":memory:" for in-memory.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # --- Schema Creation ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            head_commit_id INTEGER,
            created_at  REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS commits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hash        TEXT    NOT NULL UNIQUE,
            parent_id   INTEGER,
            branch_id   INTEGER NOT NULL,
            message     TEXT    NOT NULL,
            timestamp   REAL    NOT NULL,
            author      TEXT    NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES commits(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        );

        CREATE TABLE IF NOT EXISTS row_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name  TEXT    NOT NULL,
            row_id      TEXT    NOT NULL,
            commit_id   INTEGER NOT NULL,
            data_json   TEXT,
            is_deleted  INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (commit_id) REFERENCES commits(id)
        );

        CREATE INDEX IF NOT EXISTS idx_row_versions_commit
            ON row_versions(commit_id);
        CREATE INDEX IF NOT EXISTS idx_row_versions_table_row
            ON row_versions(table_name, row_id);
        CREATE INDEX IF NOT EXISTS idx_commits_branch
            ON commits(branch_id);
        CREATE INDEX IF NOT EXISTS idx_commits_hash
            ON commits(hash);
    """)

    # --- Seed: create 'main' branch + initial empty commit if not present ---
    cursor = conn.execute("SELECT id FROM branches WHERE name = 'main'")
    if cursor.fetchone() is None:
        now = time.time()
        initial_hash = _compute_hash("init", str(now))

        conn.execute(
            "INSERT INTO branches (name, head_commit_id) VALUES ('main', NULL)"
        )
        branch_id = conn.execute(
            "SELECT id FROM branches WHERE name = 'main'"
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO commits (hash, parent_id, branch_id, message, timestamp, author)
               VALUES (?, NULL, ?, 'Initial commit', ?, 'system')""",
            (initial_hash, branch_id, now),
        )
        commit_id = conn.execute(
            "SELECT id FROM commits WHERE hash = ?", (initial_hash,)
        ).fetchone()["id"]

        conn.execute(
            "UPDATE branches SET head_commit_id = ? WHERE id = ?",
            (commit_id, branch_id),
        )
        conn.commit()

    return conn
