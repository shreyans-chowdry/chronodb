"""
ChronoDB MVP Version Engine — Core Logic

Implements the Git-like version-control operations over the custom page-backed
storage engine (DiskManager, BufferPoolManager, WALManager, BTreeIndex).

Design decisions:
  - rollback() creates a NEW commit (Git revert semantics), never rewrites history
  - branch() is O(1): it creates a pointer to the source branch's HEAD, no data copy
  - Every mutation (insert/update/delete) produces a new row_versions entry in
    the Buffer Pool and adds a new version to the key's Version Chain in the B+ Tree.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple
import os

from ..storage.disk_manager import DiskManager
from ..storage.buffer_pool import BufferPoolManager
from ..wal.wal_manager import WALManager
from ..index.btree import BTreeIndex
from ..storage.page import INVALID_PAGE_ID, PAGE_SIZE
from .schema import _compute_hash
from .catalog import SystemCatalog


class VersionEngine:
    """
    Core version engine providing Git-like semantics over the custom storage stack.
    """

    def __init__(self, db_path: str = ":memory:"):
        # For tests that pass :memory:, use a local temp dir or something, 
        # but the test suite will be updated to pass a real directory path.
        if db_path == ":memory:":
            db_path = "chronodb.dat"
            
        wal_path = db_path + ".wal"
        
        # Initialize storage components
        self.disk = DiskManager(db_path)
        self.wal = WALManager(wal_path)
        self.pool = BufferPoolManager(pool_size=100, disk_manager=self.disk)
        
        # Initialize or recover metadata
        # If DB is empty, allocate Page 0 for Catalog, Page 1 for BTree Root
        is_new = self.disk.get_num_pages() == 0
        
        if is_new:
            cat_page = self.pool.new_page()
            if not cat_page:
                raise RuntimeError("Failed to allocate initial metadata pages")
            
            cat_page_id = cat_page.page_id
            self.pool.unpin_page(cat_page_id, is_dirty=True)
            
            self.catalog = SystemCatalog(self.pool, cat_page_id)
            self.btree = BTreeIndex(self.pool) # Will allocate Page 1 internally as Leaf
            
            # Setup default "main" branch and initial commit
            initial_txn = self.wal.allocate_txn_id()
            now = time.time()
            commit_hash = _compute_hash(str(None), str(None), "main", "Initial commit", str(now), "system")
            
            self.catalog.add_commit(initial_txn, {
                "id": initial_txn,
                "hash": commit_hash,
                "parent_id": None,
                "second_parent_id": None,
                "branch_id": "main",
                "message": "Initial commit",
                "timestamp": now,
                "author": "system"
            })
            self.catalog.add_branch("main", initial_txn)
            
        else:
            self.catalog = SystemCatalog(self.pool, 0)
            self.btree = BTreeIndex(self.pool, 1)

        self._current_branch = "main"

    def close(self):
        """Close the underlying storage connections."""
        self.pool.flush_all_pages()
        self.disk.close()

    # ──────────────────────────────────────────────
    # Branch operations
    # ──────────────────────────────────────────────

    def branch(self, name: str, source_branch: str = "main") -> Dict[str, Any]:
        source = self.catalog.get_branch(source_branch)
        if source is None:
            raise ValueError(f"Source branch '{source_branch}' does not exist")

        if self.catalog.get_branch(name) is not None:
            raise ValueError(f"Branch '{name}' already exists")

        self.catalog.add_branch(name, source["head_commit_id"])
        
        # Return dict matching old schema
        branch = self.catalog.get_branch(name)
        return {"id": name, "name": branch["name"], "head_commit_id": branch["head_commit_id"]} # type: ignore

    def checkout(self, branch_name: str) -> str:
        if self.catalog.get_branch(branch_name) is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
        self._current_branch = branch_name
        return branch_name

    def list_branches(self) -> List[Dict[str, Any]]:
        return [{"id": name, "name": b["name"], "head_commit_id": b["head_commit_id"]} 
                for name, b in self.catalog.branches.items()]

    def get_current_branch(self) -> str:
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
        branch = self.catalog.get_branch(branch_name)
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        now = time.time()
        parent_id = branch["head_commit_id"]
        
        commit_hash = _compute_hash(
            str(parent_id), str(second_parent_id), branch_name, message, str(now), author
        )
        
        txn_id = self.wal.allocate_txn_id()
        self.wal.begin_txn(txn_id)

        # Apply changes to buffer pool and WAL
        if changes:
            for change in changes:
                action = change["action"]
                table_name = change["table_name"]
                row_id = change["row_id"]
                key = f"{table_name}:{row_id}"
                
                self.catalog.register_row_key(table_name, row_id)
                
                if action in ("insert", "update"):
                    # Serialize data to page
                    page = self.pool.new_page()
                    if not page:
                        raise RuntimeError("Out of memory allocating page for row data")
                        
                    data_bytes = json.dumps(change["data"]).encode('utf-8')
                    page.data[:len(data_bytes)] = data_bytes
                    page_version_id = page.page_id
                    
                    # Write-ahead log
                    self.wal.log_update(txn_id, page_version_id, bytes(page.data))
                    
                    self.pool.unpin_page(page_version_id, is_dirty=True)
                    
                    # Update B+ Tree
                    self.btree.insert(key, txn_id, page_version_id)
                    
                elif action == "delete":
                    # For deletion, we just insert an INVALID_PAGE_ID as a tombstone
                    # There is no page to log in the WAL, so we just log a dummy update
                    # to keep the WAL consistent if needed, but not strictly required
                    # since the B+ tree modifications will be logged when they hit disk.
                    # For this MVP, we consider B+ tree operations as durable via checkpoints.
                    self.btree.insert(key, txn_id, INVALID_PAGE_ID)

        self.wal.commit_txn(txn_id)
        
        # Save commit metadata
        commit_data = {
            "id": txn_id,
            "hash": commit_hash,
            "parent_id": parent_id,
            "second_parent_id": second_parent_id,
            "branch_id": branch_name,
            "message": message,
            "timestamp": now,
            "author": author,
        }
        self.catalog.add_commit(txn_id, commit_data)
        self.catalog.update_branch_head(branch_name, txn_id)
        
        return commit_data

    def get_commit_history(
        self, branch_name: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        branch = self.catalog.get_branch(branch_name)
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        history = []
        current_id = branch["head_commit_id"]

        while current_id is not None and len(history) < limit:
            commit = self.catalog.get_commit(current_id)
            if commit is None:
                break
            history.append(commit)
            current_id = commit["parent_id"]

        return history

    # ──────────────────────────────────────────────
    # Rollback
    # ──────────────────────────────────────────────

    def rollback(self, branch_name: str, target_commit_hash: str, author: str) -> Dict[str, Any]:
        branch = self.catalog.get_branch(branch_name)
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")

        # Find target commit ID from hash
        target_id = None
        for cid, cdata in self.catalog.commits.items():
            if cdata["hash"] == target_commit_hash:
                target_id = cid
                break
                
        if target_id is None:
            raise ValueError(f"Commit '{target_commit_hash}' does not exist")

        if not self.catalog.is_ancestor(target_id, branch["head_commit_id"]):
            raise ValueError(
                f"Commit '{target_commit_hash}' is not in branch '{branch_name}' history"
            )

        # To perform a rollback, we need to reconstruct the data state at `target_id`
        # and create a NEW commit that applies those changes.
        changes = []
        
        # Iterate over all known table keys and resolve their state at target_id
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                
                # Get state at target
                target_page_id = self.btree.resolve_version(key, target_id, self.catalog.is_ancestor)
                
                if target_page_id is not None and target_page_id != INVALID_PAGE_ID:
                    # Row existed at target commit, read its data
                    page = self.pool.fetch_page(target_page_id)
                    if page:
                        null_idx = page.data.find(b'\x00')
                        if null_idx == -1:
                            null_idx = PAGE_SIZE
                        data_json = page.data[:null_idx].decode('utf-8')
                        self.pool.unpin_page(target_page_id, is_dirty=False)
                        
                        changes.append({
                            "action": "update",  # update/insert semantics are same here
                            "table_name": table_name,
                            "row_id": row_id,
                            "data": json.loads(data_json)
                        })
                else:
                    # Row was deleted or didn't exist at target commit
                    changes.append({
                        "action": "delete",
                        "table_name": table_name,
                        "row_id": row_id,
                        "data": None
                    })

        rollback_msg = f"Rollback to commit {target_commit_hash}"
        return self.commit(branch_name, rollback_msg, author, changes=changes)

    # ──────────────────────────────────────────────
    # Diff & Merge
    # ──────────────────────────────────────────────

    def diff(self, commit_hash_a: str, commit_hash_b: str) -> Dict[str, Any]:
        """
        Compare two commits and produce a per-table, per-row diff.

        For each (table, row_id) across both snapshots, classifies as:
          - "added"    — exists only in B
          - "deleted"  — exists only in A
          - "modified" — exists in both but data differs
          (unchanged rows are omitted)

        Args:
            commit_hash_a: The "before" commit hash (left side).
            commit_hash_b: The "after" commit hash (right side).

        Returns:
            { "tables": { table_name: { "rows": [ ...DiffRow ] } } }
        """
        # Resolve commit IDs from hashes
        id_a = self._resolve_commit_id(commit_hash_a)
        id_b = self._resolve_commit_id(commit_hash_b)

        # Collect all known (table_name, row_id) pairs
        all_keys: set[tuple[str, str]] = set()
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                all_keys.add((table_name, row_id))

        # Build per-table diff
        tables_diff: Dict[str, Dict[str, list]] = {}

        for table_name, row_id in all_keys:
            key = f"{table_name}:{row_id}"

            page_a = self.btree.resolve_version(key, id_a, self.catalog.is_ancestor)
            page_b = self.btree.resolve_version(key, id_b, self.catalog.is_ancestor)

            data_a = self._read_page_data(page_a)
            data_b = self._read_page_data(page_b)

            exists_a = data_a is not None
            exists_b = data_b is not None

            if not exists_a and not exists_b:
                continue

            diff_row: Optional[Dict[str, Any]] = None

            if exists_a and not exists_b:
                diff_row = {
                    "row_id": row_id,
                    "status": "deleted",
                    "data_a": data_a,
                    "data_b": None,
                }
            elif not exists_a and exists_b:
                diff_row = {
                    "row_id": row_id,
                    "status": "added",
                    "data_a": None,
                    "data_b": data_b,
                }
            elif data_a != data_b:
                # Find changed fields
                all_fields = set(list(data_a.keys()) + list(data_b.keys()))  # type: ignore
                changed_fields = [
                    f for f in all_fields if data_a.get(f) != data_b.get(f)  # type: ignore
                ]
                diff_row = {
                    "row_id": row_id,
                    "status": "modified",
                    "data_a": data_a,
                    "data_b": data_b,
                    "changed_fields": changed_fields,
                }
            # else: unchanged — skip

            if diff_row:
                if table_name not in tables_diff:
                    tables_diff[table_name] = {"rows": []}
                tables_diff[table_name]["rows"].append(diff_row)

        return {"tables": tables_diff}

    def merge(
        self,
        target_branch: str,
        source_branch: str,
        author: str,
        resolutions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Three-way merge of source_branch into target_branch.

        Finds the common ancestor (fork point), computes what changed on each
        branch relative to it, and auto-merges non-conflicting changes. Rows
        changed on both branches are conflicts and require a resolution.

        Args:
            target_branch: The branch to merge INTO (e.g. "main").
            source_branch: The branch to merge FROM (e.g. "feature/x").
            author: Author performing the merge.
            resolutions: Optional dict of resolved conflicts, keyed by
                         "table_name:row_id", with value being the chosen data
                         dict (or None for deletion).

        Returns:
            On success: { "status": "ok", "commit": <merge commit dict> }
            On conflict: { "status": "conflict", "conflicts": [...], "auto_resolved": [...] }
        """
        if resolutions is None:
            resolutions = {}

        target_info = self.catalog.get_branch(target_branch)
        source_info = self.catalog.get_branch(source_branch)
        if target_info is None:
            raise ValueError(f"Branch '{target_branch}' does not exist")
        if source_info is None:
            raise ValueError(f"Branch '{source_branch}' does not exist")

        target_head = target_info["head_commit_id"]
        source_head = source_info["head_commit_id"]

        # Find common ancestor (fork point)
        ancestor_id = self._find_common_ancestor(target_head, source_head)
        if ancestor_id is None:
            raise ValueError("No common ancestor found between the two branches")

        # Collect all known keys
        all_keys: set[tuple[str, str]] = set()
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                all_keys.add((table_name, row_id))

        conflicts: list[Dict[str, Any]] = []
        auto_resolved: list[Dict[str, Any]] = []
        merge_changes: list[Dict[str, Any]] = []

        for table_name, row_id in all_keys:
            key = f"{table_name}:{row_id}"

            page_anc = self.btree.resolve_version(key, ancestor_id, self.catalog.is_ancestor)
            page_tgt = self.btree.resolve_version(key, target_head, self.catalog.is_ancestor)
            page_src = self.btree.resolve_version(key, source_head, self.catalog.is_ancestor)

            data_anc = self._read_page_data(page_anc)
            data_tgt = self._read_page_data(page_tgt)
            data_src = self._read_page_data(page_src)

            changed_on_target = (data_tgt != data_anc)
            changed_on_source = (data_src != data_anc)

            if not changed_on_target and not changed_on_source:
                # No change on either side — skip
                continue

            if changed_on_source and not changed_on_target:
                # Only source changed — auto-merge (take source)
                if data_src is not None:
                    merge_changes.append({
                        "action": "update",
                        "table_name": table_name,
                        "row_id": row_id,
                        "data": data_src,
                    })
                else:
                    merge_changes.append({
                        "action": "delete",
                        "table_name": table_name,
                        "row_id": row_id,
                        "data": None,
                    })
                auto_resolved.append({
                    "table_name": table_name,
                    "row_id": row_id,
                    "resolution": "take_source",
                    "data": data_src,
                })

            elif changed_on_target and not changed_on_source:
                # Only target changed — already in target, nothing to merge
                auto_resolved.append({
                    "table_name": table_name,
                    "row_id": row_id,
                    "resolution": "keep_target",
                    "data": data_tgt,
                })

            else:
                # Both changed — conflict!
                resolution_key = f"{table_name}:{row_id}"
                if resolution_key in resolutions:
                    # User provided a resolution
                    chosen = resolutions[resolution_key]
                    if chosen is not None:
                        merge_changes.append({
                            "action": "update",
                            "table_name": table_name,
                            "row_id": row_id,
                            "data": chosen,
                        })
                    else:
                        merge_changes.append({
                            "action": "delete",
                            "table_name": table_name,
                            "row_id": row_id,
                            "data": None,
                        })
                else:
                    # Unresolved conflict
                    conflicts.append({
                        "table_name": table_name,
                        "row_id": row_id,
                        "data_ancestor": data_anc,
                        "data_target": data_tgt,
                        "data_source": data_src,
                    })

        if conflicts:
            return {
                "status": "conflict",
                "conflicts": conflicts,
                "auto_resolved": auto_resolved,
            }

        # All clear — create the merge commit
        ancestor_commit = self.catalog.get_commit(ancestor_id)
        source_commit_data = self.catalog.get_commit(source_head)
        merge_message = f"Merge branch '{source_branch}' into '{target_branch}'"

        merge_result = self.commit(
            branch_name=target_branch,
            message=merge_message,
            author=author,
            changes=merge_changes if merge_changes else None,
            second_parent_id=source_head,
        )

        return {"status": "ok", "commit": merge_result}

    def _find_common_ancestor(self, commit_a: int, commit_b: int) -> Optional[int]:
        """
        Find the common ancestor of two commits by collecting the ancestor
        set of commit_a, then walking commit_b's chain until a match is found.
        """
        # Collect all ancestors of commit A (including A itself)
        ancestors_a: set[int] = set()
        current = commit_a
        while current is not None:
            ancestors_a.add(current)
            commit = self.catalog.get_commit(current)
            if commit is None:
                break
            current = commit.get("parent_id")

        # Walk commit B chain until we find a match
        current = commit_b
        while current is not None:
            if current in ancestors_a:
                return current
            commit = self.catalog.get_commit(current)
            if commit is None:
                break
            current = commit.get("parent_id")

        return None

    def _read_page_data(self, page_id: Optional[int]) -> Optional[Dict[str, Any]]:
        """
        Read and parse JSON data from a page. Returns None if page_id is
        invalid or the page is a tombstone (deletion marker).
        """
        if page_id is None or page_id == INVALID_PAGE_ID:
            return None
        page = self.pool.fetch_page(page_id)
        if not page:
            return None
        null_idx = page.data.find(b'\x00')
        if null_idx == -1:
            null_idx = PAGE_SIZE
        if null_idx > 0:
            data_json = page.data[:null_idx].decode('utf-8')
            self.pool.unpin_page(page_id, is_dirty=False)
            return json.loads(data_json)
        self.pool.unpin_page(page_id, is_dirty=False)
        return None

    def _resolve_commit_id(self, commit_hash: str) -> int:
        """Resolve a commit hash to its integer ID, or raise ValueError."""
        for cid, cdata in self.catalog.commits.items():
            if cdata["hash"] == commit_hash:
                return cid
        raise ValueError(f"Commit '{commit_hash}' does not exist")

    # ──────────────────────────────────────────────
    # Data operations (CRUD through the version engine)
    # ──────────────────────────────────────────────

    def get_data(self, branch_name: str, table_name: str) -> List[Dict[str, Any]]:
        branch = self.catalog.get_branch(branch_name)
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
            
        return self._resolve_table_data(table_name, branch["head_commit_id"])

    def get_tables(self, branch_name: str) -> List[str]:
        branch = self.catalog.get_branch(branch_name)
        if branch is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
            
        head_id = branch["head_commit_id"]
        active_tables = set()
        
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                page_id = self.btree.resolve_version(key, head_id, self.catalog.is_ancestor)
                if page_id is not None and page_id != INVALID_PAGE_ID:
                    active_tables.add(table_name)
                    break # Only need one active row to consider table active
                    
        return sorted(active_tables)

    # ──────────────────────────────────────────────
    # Time-Travel Queries (AS OF COMMIT / AS OF timestamp)
    # ──────────────────────────────────────────────

    def query_as_of_commit(self, table_name: str, commit_hash: str) -> List[Dict[str, Any]]:
        target_id = None
        for cid, cdata in self.catalog.commits.items():
            if cdata["hash"] == commit_hash:
                target_id = cid
                break
                
        if target_id is None:
            raise ValueError(f"Commit '{commit_hash}' does not exist")
            
        return self._resolve_table_data(table_name, target_id)

    def query_as_of_timestamp(self, table_name: str, timestamp: float) -> List[Dict[str, Any]]:
        # Find the latest commit that occurred at or before the timestamp
        valid_commits = [c for c in self.catalog.commits.values() if c["timestamp"] <= timestamp]
        if not valid_commits:
            raise ValueError(f"No commits exist at or before timestamp {timestamp}")
            
        # Sort by timestamp DESC, then ID DESC
        valid_commits.sort(key=lambda x: (x["timestamp"], x["id"]), reverse=True)
        target_id = valid_commits[0]["id"]
        
        return self._resolve_table_data(table_name, target_id)

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _resolve_table_data(self, table_name: str, target_commit_id: int) -> List[Dict[str, Any]]:
        results = []
        row_ids = self.catalog.tables.get(table_name, [])
        
        for row_id in row_ids:
            key = f"{table_name}:{row_id}"
            page_version_id = self.btree.resolve_version(
                key, target_commit_id, self.catalog.is_ancestor
            )
            
            if page_version_id is not None and page_version_id != INVALID_PAGE_ID:
                page = self.pool.fetch_page(page_version_id)
                if page:
                    null_idx = page.data.find(b'\x00')
                    if null_idx == -1:
                        null_idx = PAGE_SIZE
                    # Avoid empty string decode issues
                    if null_idx > 0:
                        data_json = page.data[:null_idx].decode('utf-8')
                        row = {"row_id": row_id}
                        row.update(json.loads(data_json))
                        results.append(row)
                    self.pool.unpin_page(page_version_id, is_dirty=False)
                    
        return results
