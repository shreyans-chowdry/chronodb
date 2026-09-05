"""
ChronoDB — Benchmark Database Adapters

Provides a unified interface (BenchmarkAdapter) so the harness can run
the same workload against ChronoDB, SQLite, and optionally Dolt.
"""

import json
import os
import random
import time
import sqlite3
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from workload import random_row_data, random_string  # type: ignore


class BenchmarkAdapter(ABC):
    """Abstract interface every benchmark backend must implement."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name."""
        ...

    @abstractmethod
    def setup(self, db_path: str) -> None:
        """Initialize the database at the given path."""
        ...

    @abstractmethod
    def teardown(self) -> None:
        """Close all resources."""
        ...

    @abstractmethod
    def do_read(self) -> bool:
        """Perform a random read operation. Returns True on success."""
        ...

    @abstractmethod
    def do_write(self) -> bool:
        """Perform a random write (insert/update). Returns True on success."""
        ...

    @abstractmethod
    def do_branch(self) -> bool:
        """Create a new branch. Returns True on success."""
        ...

    @abstractmethod
    def do_merge(self) -> bool:
        """Merge a branch. Returns True on success."""
        ...

    @abstractmethod
    def do_delete(self) -> bool:
        """Delete a random row. Returns True on success."""
        ...

    @abstractmethod
    def get_storage_bytes(self) -> int:
        """Return total storage used in bytes."""
        ...


# ────────────────────────────────────────────────────────────────
# ChronoDB Adapter
# ────────────────────────────────────────────────────────────────

class ChronoDBAdapter(BenchmarkAdapter):
    """Adapter for the ChronoDB version engine."""

    def __init__(self):
        self.engine: Any = None
        self.db_path = ""
        self._row_counter = 0
        self._branch_counter = 0
        self._active_branches: List[str] = []
        self._known_rows: List[str] = []

    def name(self) -> str:
        return "ChronoDB"

    def setup(self, db_path: str) -> None:
        import sys
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        engine_dir = os.path.join(root_dir, "engine")
        src_dir = os.path.join(engine_dir, "src")
        for p in (root_dir, engine_dir, src_dir):
            if p not in sys.path:
                sys.path.insert(0, p)

        from engine.src.version.engine import VersionEngine
        self.db_path = db_path
        self.engine = VersionEngine(db_path)
        self._active_branches = ["main"]
        self._known_rows = []
        self._row_counter = 0
        self._branch_counter = 0

        # Seed some initial data
        for i in range(20):
            row_id = f"seed_{i}"
            self.engine.commit("main", f"Seed {i}", "bench", changes=[
                {"action": "insert", "table_name": "bench", "row_id": row_id,
                 "data": random_row_data()},
            ])
            self._known_rows.append(row_id)

    def teardown(self) -> None:
        if self.engine:
            self.engine.close()

    def do_read(self) -> bool:
        if not self._known_rows:
            return False
        branch = random.choice(self._active_branches)
        data = self.engine.get_data(branch, "bench")
        return len(data) >= 0

    def do_write(self) -> bool:
        branch = random.choice(self._active_branches)
        self._row_counter += 1

        if self._known_rows and random.random() < 0.4:
            # Update existing row
            row_id = random.choice(self._known_rows)
            action = "update"
        else:
            # Insert new row
            row_id = f"row_{self._row_counter}"
            action = "insert"
            self._known_rows.append(row_id)

        self.engine.commit(branch, f"Write {self._row_counter}", "bench", changes=[
            {"action": action, "table_name": "bench", "row_id": row_id,
             "data": random_row_data()},
        ])
        return True

    def do_branch(self) -> bool:
        self._branch_counter += 1
        branch_name = f"bench_br_{self._branch_counter}"
        source = random.choice(self._active_branches)
        try:
            self.engine.branch(branch_name, source_branch=source)
            self._active_branches.append(branch_name)
            return True
        except ValueError:
            return False

    def do_merge(self) -> bool:
        non_main = [b for b in self._active_branches if b != "main"]
        if not non_main:
            return False
        source = random.choice(non_main)
        try:
            self.engine.merge(source, "main", "bench")
            # Clean up merged branch
            self.engine.delete_branch(source)
            self._active_branches.remove(source)
            return True
        except Exception:
            return False

    def do_delete(self) -> bool:
        if not self._known_rows:
            return False
        branch = random.choice(self._active_branches)
        row_id = random.choice(self._known_rows)
        self.engine.commit(branch, f"Delete {row_id}", "bench", changes=[
            {"action": "delete", "table_name": "bench", "row_id": row_id},
        ])
        return True

    def get_storage_bytes(self) -> int:
        try:
            total = 0
            base = os.path.dirname(self.db_path) or "."
            for f in os.listdir(base):
                fp = os.path.join(base, f)
                if os.path.isfile(fp) and "test_bench" in f:
                    total += os.path.getsize(fp)
            # Also include the main db file
            if os.path.exists(self.db_path):
                total = max(total, os.path.getsize(self.db_path))
            return total
        except Exception:
            return 0


# ────────────────────────────────────────────────────────────────
# SQLite Adapter (simulated versioning)
# ────────────────────────────────────────────────────────────────

class SQLiteAdapter(BenchmarkAdapter):
    """
    SQLite adapter that simulates versioning with a versions table.
    
    Schema:
      branches(name TEXT PK, head_commit INTEGER)
      commits(id INTEGER PK, parent_id INTEGER, branch TEXT, message TEXT, ts REAL)
      row_versions(key TEXT, commit_id INTEGER, data TEXT, deleted INTEGER DEFAULT 0)
    """

    def __init__(self):
        self.conn: Any = None
        self.db_path = ""
        self._row_counter = 0
        self._commit_counter = 0
        self._branch_counter = 0
        self._active_branches: List[str] = []
        self._known_rows: List[str] = []

    def name(self) -> str:
        return "SQLite"

    def setup(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS branches (
                name TEXT PRIMARY KEY,
                head_commit INTEGER
            );
            CREATE TABLE IF NOT EXISTS commits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                branch TEXT,
                message TEXT,
                ts REAL
            );
            CREATE TABLE IF NOT EXISTS row_versions (
                key TEXT,
                commit_id INTEGER,
                data TEXT,
                deleted INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_rv_key ON row_versions(key);
            CREATE INDEX IF NOT EXISTS idx_rv_commit ON row_versions(commit_id);
        """)
        self.conn.commit()

        # Insert initial state
        self.conn.execute("INSERT OR IGNORE INTO branches VALUES ('main', 0)")
        self.conn.execute(
            "INSERT INTO commits (parent_id, branch, message, ts) VALUES (NULL, 'main', 'Initial', ?)",
            (time.time(),)
        )
        self.conn.commit()
        self._commit_counter = 1
        self._active_branches = ["main"]
        self._known_rows = []

        # Seed data
        for i in range(20):
            row_id = f"seed_{i}"
            self._commit_counter += 1
            self.conn.execute(
                "INSERT INTO commits (parent_id, branch, message, ts) VALUES (?, 'main', ?, ?)",
                (self._commit_counter - 1, f"Seed {i}", time.time())
            )
            self.conn.execute(
                "INSERT INTO row_versions (key, commit_id, data, deleted) VALUES (?, ?, ?, 0)",
                (row_id, self._commit_counter, json.dumps(random_row_data()))
            )
            self.conn.execute("UPDATE branches SET head_commit=? WHERE name='main'",
                              (self._commit_counter,))
            self._known_rows.append(row_id)
        self.conn.commit()

    def teardown(self) -> None:
        if self.conn:
            self.conn.close()

    def do_read(self) -> bool:
        if not self._known_rows:
            return False
        branch = random.choice(self._active_branches)
        # Read latest versions for the branch
        cur = self.conn.execute("""
            SELECT rv.key, rv.data FROM row_versions rv
            INNER JOIN (
                SELECT key, MAX(commit_id) as max_cid
                FROM row_versions
                GROUP BY key
            ) latest ON rv.key = latest.key AND rv.commit_id = latest.max_cid
            WHERE rv.deleted = 0
        """)
        rows = cur.fetchall()
        return True

    def do_write(self) -> bool:
        branch = random.choice(self._active_branches)
        self._row_counter += 1
        self._commit_counter += 1

        if self._known_rows and random.random() < 0.4:
            row_id = random.choice(self._known_rows)
        else:
            row_id = f"row_{self._row_counter}"
            self._known_rows.append(row_id)

        parent = self.conn.execute(
            "SELECT head_commit FROM branches WHERE name=?", (branch,)
        ).fetchone()
        parent_id = parent[0] if parent else None

        self.conn.execute(
            "INSERT INTO commits (parent_id, branch, message, ts) VALUES (?, ?, ?, ?)",
            (parent_id, branch, f"Write {self._row_counter}", time.time())
        )
        self.conn.execute(
            "INSERT INTO row_versions (key, commit_id, data, deleted) VALUES (?, ?, ?, 0)",
            (row_id, self._commit_counter, json.dumps(random_row_data()))
        )
        self.conn.execute("UPDATE branches SET head_commit=? WHERE name=?",
                          (self._commit_counter, branch))
        self.conn.commit()
        return True

    def do_branch(self) -> bool:
        self._branch_counter += 1
        branch_name = f"bench_br_{self._branch_counter}"
        source = random.choice(self._active_branches)

        head = self.conn.execute(
            "SELECT head_commit FROM branches WHERE name=?", (source,)
        ).fetchone()
        head_id = head[0] if head else 0

        self.conn.execute(
            "INSERT OR IGNORE INTO branches VALUES (?, ?)", (branch_name, head_id)
        )
        self.conn.commit()
        self._active_branches.append(branch_name)
        return True

    def do_merge(self) -> bool:
        non_main = [b for b in self._active_branches if b != "main"]
        if not non_main:
            return False
        source = random.choice(non_main)

        # Simple merge: copy all row_versions from source branch commits to main
        self._commit_counter += 1
        main_head = self.conn.execute(
            "SELECT head_commit FROM branches WHERE name='main'"
        ).fetchone()[0]

        self.conn.execute(
            "INSERT INTO commits (parent_id, branch, message, ts) VALUES (?, 'main', ?, ?)",
            (main_head, f"Merge {source}", time.time())
        )
        self.conn.execute(
            "UPDATE branches SET head_commit=? WHERE name='main'",
            (self._commit_counter,)
        )
        self.conn.execute("DELETE FROM branches WHERE name=?", (source,))
        self.conn.commit()
        self._active_branches.remove(source)
        return True

    def do_delete(self) -> bool:
        if not self._known_rows:
            return False
        branch = random.choice(self._active_branches)
        row_id = random.choice(self._known_rows)
        self._commit_counter += 1

        parent = self.conn.execute(
            "SELECT head_commit FROM branches WHERE name=?", (branch,)
        ).fetchone()
        parent_id = parent[0] if parent else None

        self.conn.execute(
            "INSERT INTO commits (parent_id, branch, message, ts) VALUES (?, ?, ?, ?)",
            (parent_id, branch, f"Delete {row_id}", time.time())
        )
        self.conn.execute(
            "INSERT INTO row_versions (key, commit_id, data, deleted) VALUES (?, ?, '', 1)",
            (row_id, self._commit_counter)
        )
        self.conn.execute("UPDATE branches SET head_commit=? WHERE name=?",
                          (self._commit_counter, branch))
        self.conn.commit()
        return True

    def get_storage_bytes(self) -> int:
        try:
            total = os.path.getsize(self.db_path)
            wal_path = self.db_path + "-wal"
            if os.path.exists(wal_path):
                total += os.path.getsize(wal_path)
            return total
        except Exception:
            return 0
