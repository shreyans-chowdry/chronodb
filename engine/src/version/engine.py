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
from ..storage.page import INVALID_PAGE_ID
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
