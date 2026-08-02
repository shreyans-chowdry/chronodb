"""
ChronoDB Storage Engine — System Catalog

Manages database metadata (branches and commit DAG) using the Buffer Pool.
To handle metadata larger than a single 4KB page, it implements a simple
linked-list of overflow pages.
"""

import json
from typing import Dict, Any, List, Optional

from ..storage.buffer_pool import BufferPoolManager
from ..storage.page import PAGE_SIZE, INVALID_PAGE_ID


class SystemCatalog:
    """
    Stores system metadata (branches, commits, and known tables/keys)
    in the custom page store starting at a specific root page (usually Page 0).
    """
    def __init__(self, buffer_pool: BufferPoolManager, root_page_id: int):
        self.pool = buffer_pool
        self.root_page_id = root_page_id
        
        self.branches: Dict[str, Dict[str, Any]] = {}
        self.commits: Dict[int, Dict[str, Any]] = {}
        
        # Track active keys per table: table_name -> list of row_ids
        # Used to enable full table scans over the B+ Tree Index
        self.tables: Dict[str, List[str]] = {}
        
        self.load()

    def load(self) -> None:
        """Read and deserialize the catalog from the page store."""
        data_bytes = bytearray()
        curr_page_id = self.root_page_id
        
        while curr_page_id != INVALID_PAGE_ID:
            page = self.pool.fetch_page(curr_page_id)
            if not page:
                break
                
            # Read next_page_id (4 bytes)
            next_page_id = int.from_bytes(page.data[:4], byteorder='big', signed=True)
            
            # Read length of chunk (4 bytes)
            chunk_len = int.from_bytes(page.data[4:8], byteorder='big', signed=False)
            
            if chunk_len == 0 and next_page_id == 0:
                # Page is zero-filled (brand new), stop reading
                self.pool.unpin_page(curr_page_id, is_dirty=False)
                break
                
            # Read chunk data
            if chunk_len > 0:
                data_bytes.extend(page.data[8:8+chunk_len])
                
            self.pool.unpin_page(curr_page_id, is_dirty=False)
            
            if next_page_id == curr_page_id:
                break # prevent infinite loops
                
            curr_page_id = next_page_id
            
        if data_bytes:
            state = json.loads(data_bytes.decode('utf-8'))
            self.branches = state.get("branches", {})
            # JSON keys are always strings, convert commit_ids back to int
            self.commits = {int(k): v for k, v in state.get("commits", {}).items()}
            self.tables = state.get("tables", {})
        else:
            self.branches = {}
            self.commits = {}
            self.tables = {}

    def save(self) -> None:
        """Serialize and write the catalog to the page store."""
        state = {
            "branches": self.branches,
            "commits": self.commits,
            "tables": self.tables
        }
        data_bytes = json.dumps(state).encode('utf-8')
        
        # Write in chunks of (PAGE_SIZE - 8) bytes
        max_chunk = PAGE_SIZE - 8
        
        curr_page_id = self.root_page_id
        offset = 0
        
        while offset < len(data_bytes) or offset == 0:
            chunk = data_bytes[offset:offset+max_chunk]
            offset += max_chunk
            
            page = self.pool.fetch_page(curr_page_id)
            if not page:
                raise RuntimeError(f"Failed to fetch catalog page {curr_page_id}")
                
            # If there's more data but we don't have a next page, allocate one
            next_page_id = INVALID_PAGE_ID
            if offset < len(data_bytes):
                # Read existing next_page_id first to see if we can reuse it
                existing_next = int.from_bytes(page.data[:4], byteorder='big', signed=True)
                if existing_next != INVALID_PAGE_ID:
                    next_page_id = existing_next
                else:
                    new_page = self.pool.new_page()
                    if not new_page:
                        raise RuntimeError("Out of memory extending catalog")
                    next_page_id = new_page.page_id
                    self.pool.unpin_page(next_page_id, is_dirty=True)
            
            # Pack header and chunk
            page.data[:4] = next_page_id.to_bytes(4, byteorder='big', signed=True)
            page.data[4:8] = len(chunk).to_bytes(4, byteorder='big', signed=False)
            page.data[8:8+len(chunk)] = chunk
            
            self.pool.unpin_page(curr_page_id, is_dirty=True)
            curr_page_id = next_page_id

    # ────────────────────────────────────────────────
    # Core Operations
    # ────────────────────────────────────────────────

    def add_commit(self, commit_id: int, commit_data: Dict[str, Any]) -> None:
        self.commits[commit_id] = commit_data
        self.save()

    def add_branch(self, name: str, head_commit_id: int) -> None:
        self.branches[name] = {"name": name, "head_commit_id": head_commit_id}
        self.save()

    def update_branch_head(self, name: str, head_commit_id: int) -> None:
        if name in self.branches:
            self.branches[name]["head_commit_id"] = head_commit_id
            self.save()

    def get_commit(self, commit_id: int) -> Optional[Dict[str, Any]]:
        return self.commits.get(commit_id)

    def get_branch(self, name: str) -> Optional[Dict[str, Any]]:
        return self.branches.get(name)

    def register_row_key(self, table_name: str, row_id: str) -> None:
        """Register a known row_id for a table to allow full table scans."""
        if table_name not in self.tables:
            self.tables[table_name] = []
        if row_id not in self.tables[table_name]:
            self.tables[table_name].append(row_id)
            self.save()

    def is_ancestor(self, ancestor_id: int, target_id: int) -> bool:
        """
        Check if ancestor_id is an ancestor of target_id in the commit DAG.
        Returns True if ancestor_id == target_id.
        """
        if ancestor_id == target_id:
            return True
            
        # Walk up from target_id
        current_id = target_id
        while current_id is not None:
            if current_id == ancestor_id:
                return True
            commit = self.commits.get(current_id)
            if not commit:
                break
            current_id = commit.get("parent_id")
            
        return False
