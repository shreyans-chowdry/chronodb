"""
ChronoDB MVP Version Engine — Core Logic

Implements the Git-like version-control operations over the SQLite scaffold:
commit, branch, checkout, rollback, and CRUD operations that go through the
version engine so every mutation is captured as an immutable row_version entry.

Design decisions:
  - rollback() creates a NEW commit (Git revert semantics), never rewrites history
  - branch() is O(1): it creates a pointer to the source branch's HEAD, no data copy
  - Every mutation (insert/update/delete) produces a new row_versions entry tied to
    the active (uncommitted) working state, then materialized into a commit

NOTE: This is throwaway MVP scaffolding — Phase 2 replaces SQLite with the custom
page-based storage engine (see Blueprint §19).
"""

import json
import time
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .schema import _compute_hash, init_db


class VersionEngine:
    """
    Core version engine providing Git-like semantics over relational data.

    Usage:
        engine = VersionEngine(":memory:")  # or a file path
        engine.insert_row("main", "accounts", "acc-1", {"name": "Alice", "balance": 100})
        engine.commit("main", "Add Alice's account", "shreyanschowdry")
        engine.branch("experiment", source_branch="main")
    """

    def __init__(self, db_path: str = ":memory:"):
        self.conn = init_db(db_path)
        self._current_branch = "main"

    def close(self):
        """Close the underlying database connection."""
        self.conn.close()

    # ──────────────────────────────────────────────
    # Branch operations
    # ──────────────────────────────────────────────

    def branch(self, name: str, source_branch: str = "main") -> Dict[str, Any]:
        """
        Create a new branch pointing at the source branch's HEAD commit.

        This is O(1) — it only creates a new pointer, no data is copied.

        Args:
            name: Name for the new branch (must be unique).
            source_branch: Branch to fork from (default: "main").

        Returns:
            Dict with the new branch's id, name, and head_commit_id.

        Raises:
            ValueError: If branch name already exists or source doesn't exist.
        """
        # Check source branch exists
        source = self.conn.execute(
            "SELECT id, head_commit_id FROM branches WHERE name = ?",
            (source_branch,),
        ).fetchone()
        if source is None:
            raise ValueError(f"Source branch '{source_branch}' does not exist")

        # Check target name is unique
        existing = self.conn.execute(
            "SELECT id FROM branches WHERE name = ?", (name,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"Branch '{name}' already exists")

        # Create the branch — just a pointer to source's HEAD (O(1), no data copy)
        self.conn.execute(
            "INSERT INTO branches (name, head_commit_id) VALUES (?, ?)",
            (name, source["head_commit_id"]),
        )
        self.conn.commit()

        new_branch = self.conn.execute(
            "SELECT id, name, head_commit_id FROM branches WHERE name = ?", (name,)
        ).fetchone()

        return dict(new_branch)

    def checkout(self, branch_name: str) -> str:
        """
        Switch the active branch to the given branch name.

        Args:
            branch_name: The branch to check out.

        Returns:
            The name of the branch now checked out.

        Raises:
            ValueError: If the branch does not exist.
        """
        branch = self.conn.execute(
            "SELECT id, name FROM branches WHERE name = ?", (branch_name,)
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        self._current_branch = branch_name
        return branch_name

    def list_branches(self) -> List[Dict[str, Any]]:
        """List all branches with their HEAD commit info."""
        rows = self.conn.execute(
            "SELECT id, name, head_commit_id FROM branches ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_current_branch(self) -> str:
        """Return the name of the currently checked-out branch."""
        return self._current_branch

    # ──────────────────────────────────────────────
    # Commit operations
    # ──────────────────────────────────────────────

    def commit(
        self,
        branch_name: str,
        message: str,
        author: str,
        changes: Optional[List[Dict[str, Any]]] = None,
        second_parent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a new commit on the specified branch.

        If `changes` is provided, each change dict should contain:
          - action: "insert" | "update" | "delete"
          - table_name: str
          - row_id: str
          - data: dict (for insert/update) or None (for delete)

        The commit snapshots the changes as new row_version entries tied to
        this commit (copy-on-write — previous versions are never modified).

        Args:
            branch_name: Branch to commit on.
            message: Commit message.
            author: Author identifier.
            changes: Optional list of row mutations to include in this commit.
            second_parent_id: Optional second parent commit ID (for 3-way merge commits).

        Returns:
            Dict with the new commit's id, hash, message, timestamp.

        Raises:
            ValueError: If the branch does not exist.
        """
        branch = self.conn.execute(
            "SELECT id, head_commit_id FROM branches WHERE name = ?",
            (branch_name,),
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        now = time.time()
        parent_id = branch["head_commit_id"]
        commit_hash = _compute_hash(
            str(parent_id), str(second_parent_id), str(branch["id"]), message, str(now), author
        )

        # Create the commit record
        self.conn.execute(
            """INSERT INTO commits (hash, parent_id, second_parent_id, branch_id, message, timestamp, author)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (commit_hash, parent_id, second_parent_id, branch["id"], message, now, author),
        )
        commit_id = self.conn.execute(
            "SELECT id FROM commits WHERE hash = ?", (commit_hash,)
        ).fetchone()["id"]

        # Apply changes as new row_version entries (copy-on-write)
        if changes:
            for change in changes:
                action = change["action"]
                table_name = change["table_name"]
                row_id = change["row_id"]

                if action == "insert":
                    self.conn.execute(
                        """INSERT INTO row_versions (table_name, row_id, commit_id, data_json, is_deleted)
                           VALUES (?, ?, ?, ?, 0)""",
                        (table_name, row_id, commit_id, json.dumps(change["data"])),
                    )
                elif action == "update":
                    self.conn.execute(
                        """INSERT INTO row_versions (table_name, row_id, commit_id, data_json, is_deleted)
                           VALUES (?, ?, ?, ?, 0)""",
                        (table_name, row_id, commit_id, json.dumps(change["data"])),
                    )
                elif action == "delete":
                    self.conn.execute(
                        """INSERT INTO row_versions (table_name, row_id, commit_id, data_json, is_deleted)
                           VALUES (?, ?, ?, NULL, 1)""",
                        (table_name, row_id, commit_id),
                    )

        # Advance the branch HEAD to this new commit
        self.conn.execute(
            "UPDATE branches SET head_commit_id = ? WHERE id = ?",
            (commit_id, branch["id"]),
        )
        self.conn.commit()

        return {
            "id": commit_id,
            "hash": commit_hash,
            "parent_id": parent_id,
            "second_parent_id": second_parent_id,
            "branch_id": branch["id"],
            "message": message,
            "timestamp": now,
            "author": author,
        }

    def get_commit_history(
        self, branch_name: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Walk the commit chain from the branch HEAD backwards (like `git log`).

        Args:
            branch_name: Branch whose history to retrieve.
            limit: Maximum number of commits to return.

        Returns:
            List of commit dicts, newest first.
        """
        branch = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?", (branch_name,)
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        history = []
        current_id = branch["head_commit_id"]

        while current_id is not None and len(history) < limit:
            commit = self.conn.execute(
                "SELECT id, hash, parent_id, second_parent_id, branch_id, message, timestamp, author FROM commits WHERE id = ?",
                (current_id,),
            ).fetchone()
            if commit is None:
                break
            history.append(dict(commit))
            current_id = commit["parent_id"]

        return history

    # ──────────────────────────────────────────────
    # Rollback
    # ──────────────────────────────────────────────

    def rollback(self, branch_name: str, target_commit_hash: str, author: str) -> Dict[str, Any]:
        """
        Rollback the branch to a prior commit by creating a NEW commit whose
        data matches the target historical state.

        This follows Git 'revert' semantics — history is never rewritten.
        The rolled-back state is preserved, and a new commit is appended.

        Args:
            branch_name: Branch to rollback.
            target_commit_hash: Hash of the commit to rollback to.
            author: Author performing the rollback.

        Returns:
            The new rollback commit dict.

        Raises:
            ValueError: If branch or commit doesn't exist, or commit isn't
                        in the branch's history.
        """
        branch = self.conn.execute(
            "SELECT id, head_commit_id FROM branches WHERE name = ?",
            (branch_name,),
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        target_commit = self.conn.execute(
            "SELECT id, hash FROM commits WHERE hash = ?", (target_commit_hash,)
        ).fetchone()
        if target_commit is None:
            raise ValueError(f"Commit '{target_commit_hash}' does not exist")

        # Verify the target commit is reachable from the branch's history
        target_id = target_commit["id"]
        found = False
        walk_id = branch["head_commit_id"]
        while walk_id is not None:
            if walk_id == target_id:
                found = True
                break
            row = self.conn.execute(
                "SELECT parent_id FROM commits WHERE id = ?", (walk_id,)
            ).fetchone()
            if row is None:
                break
            walk_id = row["parent_id"]

        if not found:
            raise ValueError(
                f"Commit '{target_commit_hash}' is not in branch '{branch_name}' history"
            )

        # Reconstruct the data state at the target commit:
        # Walk backwards from target, collecting the latest row_version per (table, row_id)
        data_at_target = self._resolve_data_at_commit(target_id)

        # Create a new rollback commit with changes that reproduce the target state
        now = time.time()
        parent_id = branch["head_commit_id"]
        rollback_message = f"Rollback to commit {target_commit_hash}"
        rollback_hash = _compute_hash(
            str(parent_id), str(branch["id"]), rollback_message, str(now), author
        )

        self.conn.execute(
            """INSERT INTO commits (hash, parent_id, branch_id, message, timestamp, author)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rollback_hash, parent_id, branch["id"], rollback_message, now, author),
        )
        rollback_commit_id = self.conn.execute(
            "SELECT id FROM commits WHERE hash = ?", (rollback_hash,)
        ).fetchone()["id"]

        # Snapshot the target state into this new rollback commit
        for (table_name, row_id), version_data in data_at_target.items():
            self.conn.execute(
                """INSERT INTO row_versions (table_name, row_id, commit_id, data_json, is_deleted)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    table_name,
                    row_id,
                    rollback_commit_id,
                    version_data["data_json"],
                    version_data["is_deleted"],
                ),
            )

        # Advance branch HEAD
        self.conn.execute(
            "UPDATE branches SET head_commit_id = ? WHERE id = ?",
            (rollback_commit_id, branch["id"]),
        )
        self.conn.commit()

        return {
            "id": rollback_commit_id,
            "hash": rollback_hash,
            "parent_id": parent_id,
            "branch_id": branch["id"],
            "message": rollback_message,
            "timestamp": now,
            "author": author,
        }

    # ──────────────────────────────────────────────
    # Data operations (CRUD through the version engine)
    # ──────────────────────────────────────────────

    def get_data(
        self, branch_name: str, table_name: str
    ) -> List[Dict[str, Any]]:
        """
        Read current data for a table on the specified branch.

        Resolves the latest row_version for each row_id by walking the commit
        chain from the branch HEAD backwards.

        Args:
            branch_name: Branch to read from.
            table_name: Name of the table to read.

        Returns:
            List of dicts, each containing row_id and the parsed data.
        """
        branch = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?", (branch_name,)
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        data_at_head = self._resolve_data_at_commit(branch["head_commit_id"])

        results = []
        for (tbl, row_id), version_data in data_at_head.items():
            if tbl == table_name and not version_data["is_deleted"]:
                row = {"row_id": row_id}
                if version_data["data_json"]:
                    row.update(json.loads(version_data["data_json"]))
                results.append(row)

        return results

    def get_tables(self, branch_name: str) -> List[str]:
        """
        List all table names that have data on the given branch.

        Args:
            branch_name: Branch to inspect.

        Returns:
            Sorted list of distinct table names.
        """
        branch = self.conn.execute(
            "SELECT head_commit_id FROM branches WHERE name = ?", (branch_name,)
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        data_at_head = self._resolve_data_at_commit(branch["head_commit_id"])

        tables = set()
        for (tbl, _), version_data in data_at_head.items():
            if not version_data["is_deleted"]:
                tables.add(tbl)

        return sorted(tables)

    # ──────────────────────────────────────────────
    # Time-Travel Queries (AS OF COMMIT / AS OF timestamp)
    # ──────────────────────────────────────────────

    def query_as_of_commit(
        self, table_name: str, commit_hash: str
    ) -> List[Dict[str, Any]]:
        """
        Query a table 'AS OF COMMIT <hash>'.

        Resolves the exact data state of the database at a target historical commit.

        Args:
            table_name: Table to query.
            commit_hash: The historical commit hash to query 'as of'.

        Returns:
            List of row dicts as they existed at that commit.

        Raises:
            ValueError: If commit_hash does not exist.
        """
        commit = self.conn.execute(
            "SELECT id FROM commits WHERE hash = ?", (commit_hash,)
        ).fetchone()
        if commit is None:
            raise ValueError(f"Commit '{commit_hash}' does not exist")

        data_at_commit = self._resolve_data_at_commit(commit["id"])

        results = []
        for (tbl, row_id), version_data in data_at_commit.items():
            if tbl == table_name and not version_data["is_deleted"]:
                row = {"row_id": row_id}
                if version_data["data_json"]:
                    row.update(json.loads(version_data["data_json"]))
                results.append(row)

        return results

    def query_as_of_timestamp(
        self, table_name: str, timestamp: float
    ) -> List[Dict[str, Any]]:
        """
        Query a table 'AS OF <timestamp>'.

        Finds the latest commit that occurred at or before the given timestamp
        and resolves the table state as of that commit.

        Args:
            table_name: Table to query.
            timestamp: Historical unix timestamp to query 'as of'.

        Returns:
            List of row dicts as they existed at that timestamp.

        Raises:
            ValueError: If no commits exist at or before the given timestamp.
        """
        commit = self.conn.execute(
            "SELECT id FROM commits WHERE timestamp <= ? ORDER BY timestamp DESC, id DESC LIMIT 1",
            (timestamp,),
        ).fetchone()
        if commit is None:
            raise ValueError(f"No commits exist at or before timestamp {timestamp}")

        data_at_commit = self._resolve_data_at_commit(commit["id"])

        results = []
        for (tbl, row_id), version_data in data_at_commit.items():
            if tbl == table_name and not version_data["is_deleted"]:
                row = {"row_id": row_id}
                if version_data["data_json"]:
                    row.update(json.loads(version_data["data_json"]))
                results.append(row)

        return results

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _resolve_data_at_commit(
        self, commit_id: Optional[int]
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """
        Reconstruct the full data state at a given commit by walking backwards
        through the commit chain and collecting the latest row_version per
        (table_name, row_id).

        This is the core version-chain resolution algorithm.

        Args:
            commit_id: The commit ID to resolve data at.

        Returns:
            Dict mapping (table_name, row_id) -> {data_json, is_deleted}
        """
        if commit_id is None:
            return {}

        # Collect all commit IDs in this chain (newest → oldest)
        commit_chain = []
        current_id = commit_id
        while current_id is not None:
            commit_chain.append(current_id)
            row = self.conn.execute(
                "SELECT parent_id FROM commits WHERE id = ?", (current_id,)
            ).fetchone()
            if row is None:
                break
            current_id = row["parent_id"]

        # Resolve: walk oldest → newest so latest version wins
        data: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for cid in reversed(commit_chain):
            versions = self.conn.execute(
                "SELECT table_name, row_id, data_json, is_deleted FROM row_versions WHERE commit_id = ?",
                (cid,),
            ).fetchall()
            for v in versions:
                key = (v["table_name"], v["row_id"])
                data[key] = {
                    "data_json": v["data_json"],
                    "is_deleted": v["is_deleted"],
                }

        return data

    def _get_branch_info(self, branch_name: str) -> Dict[str, Any]:
        """Get branch record or raise ValueError."""
        branch = self.conn.execute(
            "SELECT id, name, head_commit_id FROM branches WHERE name = ?",
            (branch_name,),
        ).fetchone()
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
        return dict(branch)
