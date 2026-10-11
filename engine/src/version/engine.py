"""
ChronoDB Version Engine

Git-like version control over the custom page-based storage stack
(DiskManager → BufferPoolManager → WAL → version-aware B+ tree).

Design decisions
  * Every mutation writes a new row version; nothing is updated in place.
  * branch() is O(1): a branch is a name → commit pointer.
  * rollback() adds a new commit (Git revert semantics) and never rewrites history.
  * Each public mutating operation is made durable as one WAL transaction:
    the after-images of every page it dirtied (row data, B+ tree nodes,
    catalog) are appended with a single fsync, followed by a COMMIT record.
    On open, committed transactions found in the WAL are replayed (redo).
"""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..index.btree import BTreeIndex
from ..merge.three_way import ThreeWayMerge
from ..storage.buffer_pool import BufferPoolManager
from ..storage.disk_manager import DiskManager
from ..storage.heap import DeltaHeap, is_packed_ref
from ..storage.optimizer import OptimizerReport, StorageOptimizer
from ..storage.page import INVALID_PAGE_ID, PAGE_SIZE
from ..storage.reader import read_row_data
from ..wal.log_record import LogRecord, LogRecordType
from ..wal.recovery import RecoveryManager
from ..wal.wal_manager import WALManager
from .catalog import SystemCatalog
from .gc import GarbageCollector, GCReport
from .schema import _compute_hash

DEFAULT_POOL_PAGES = 1024           # 4 MB of page frames
CHECKPOINT_WAL_BYTES = 16 * 1024 * 1024
VALID_ACTIONS = ("insert", "update", "upsert", "delete")
MAX_ROW_BYTES = PAGE_SIZE


def _changes_digest(changes: Optional[List[Dict[str, Any]]]) -> str:
    if not changes:
        return "-"
    canon = json.dumps(
        [[c.get("action"), c.get("table_name"), str(c.get("row_id")), c.get("data")] for c in changes],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


class VersionEngine:
    """Git-like semantics over the page-based storage engine."""

    def __init__(self, db_path: str = ":memory:", pool_size: int = DEFAULT_POOL_PAGES):
        if db_path == ":memory:":
            db_path = "chronodb.dat"
        self.db_path = db_path
        wal_path = db_path + ".wal"

        fresh_file = not os.path.exists(db_path) or os.path.getsize(db_path) == 0
        self.disk = DiskManager(db_path)
        self.wal = WALManager(wal_path)
        if fresh_file and self.wal.get_wal_size_bytes() > 0:
            # A WAL without its data file belongs to a database that was
            # deleted; replaying it into a new file would resurrect stale pages.
            self.wal.truncate()

        # ── Crash recovery: redo committed transactions still in the WAL ──
        self.last_recovery: Dict[str, Any] = {"status": "clean"}
        if self.wal.get_wal_size_bytes() > 0:
            self.last_recovery = RecoveryManager(self.wal, self.disk).recover()
            self.disk.sync()
            self.wal.truncate()

        self.pool = BufferPoolManager(pool_size=pool_size, disk_manager=self.disk)
        is_new = self.disk.get_num_pages() == 0

        if is_new:
            cat_page = self.pool.new_page()
            if not cat_page:
                raise RuntimeError("Failed to allocate catalog page")
            self.pool.unpin_page(cat_page.page_id, is_dirty=True)
            self.catalog = SystemCatalog(self.pool, cat_page.page_id)
            self.btree = BTreeIndex(self.pool, on_root_change=self._on_root_change)

            cid = self._alloc_id()
            now = time.time()
            self.catalog.add_commit(cid, {
                "id": cid,
                "hash": _compute_hash("None", "None", "main", "Initial commit", str(now), "system"),
                "parent_id": None,
                "second_parent_id": None,
                "branch_id": "main",
                "message": "Initial commit",
                "timestamp": now,
                "author": "system",
                "stats": {"insert": 0, "update": 0, "delete": 0},
            })
            self.catalog.add_branch("main", cid, created_at=now, created_from=None, base_commit_id=None)
            self._make_durable(cid)
        else:
            self.catalog = SystemCatalog(self.pool, 0)
            root = self.catalog.btree_root if self.catalog.btree_root != INVALID_PAGE_ID else 1
            self.btree = BTreeIndex(self.pool, root, on_root_change=self._on_root_change)
            if self.catalog.commits and self.catalog.next_txn_id <= max(self.catalog.commits):
                self.catalog.next_txn_id = max(self.catalog.commits) + 1
            if self.catalog.migrated_from_v1:
                self._make_durable(self._alloc_id())

        self.heap = DeltaHeap(self.pool, self.catalog.heap_tail)
        self._current_branch = "main"

    # ──────────────────────────────────────────────
    # Durability plumbing
    # ──────────────────────────────────────────────

    def _on_root_change(self, root_page_id: int) -> None:
        if hasattr(self, "catalog"):
            self.catalog.btree_root = root_page_id
            self.catalog.mark_dirty()

    def _alloc_id(self) -> int:
        cid = self.catalog.next_txn_id if hasattr(self, "catalog") else 1
        self.catalog.next_txn_id = cid + 1
        self.catalog.mark_dirty()
        return cid

    def _make_durable(self, txn_id: Optional[int] = None) -> None:
        """Group-commit every page dirtied since the last call."""
        if self.heap_tail_changed():
            self.catalog.heap_tail = self.heap.tail_page_id
            self.catalog.mark_dirty()
        self.catalog.flush()
        dirty = sorted(self.pool.txn_dirty)
        if not dirty:
            return
        if txn_id is None:
            txn_id = self._alloc_id()
            self.catalog.flush()
            dirty = sorted(self.pool.txn_dirty)
        records = [LogRecord(txn_id=txn_id, record_type=LogRecordType.BEGIN)]
        for pid in dirty:
            img = self.pool.page_bytes(pid)
            if img is not None:
                records.append(LogRecord(txn_id=txn_id, record_type=LogRecordType.UPDATE,
                                         page_id=pid, after_image=img))
        records.append(LogRecord(txn_id=txn_id, record_type=LogRecordType.COMMIT))
        self.wal.append_batch(records)
        self.pool.clear_txn_tracking()
        if self.wal.get_wal_size_bytes() > CHECKPOINT_WAL_BYTES:
            self.checkpoint()

    def heap_tail_changed(self) -> bool:
        return hasattr(self, "heap") and self.heap.tail_page_id != self.catalog.heap_tail

    @contextmanager
    def _operation(self, txn_id: Optional[int] = None) -> Iterator[None]:
        yield
        self._make_durable(txn_id)

    def checkpoint(self) -> Dict[str, Any]:
        """Flush all pages, fsync the data file and truncate the WAL."""
        self.catalog.flush()
        flushed = self.pool.flush_all_pages()
        self.disk.sync()
        self.wal.truncate()
        self.pool.clear_txn_tracking()
        return {"pages_flushed": flushed}

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._make_durable()
        self.checkpoint()
        self.disk.close()
        self._closed = True

    # ──────────────────────────────────────────────
    # Lookup helpers
    # ──────────────────────────────────────────────

    def _resolve_commit_id(self, commit_hash: str) -> int:
        cid = self.catalog.commit_id_for_hash(commit_hash)
        if cid is None:
            raise ValueError(f"Commit '{commit_hash}' does not exist")
        return cid

    def resolve_ref(self, ref: str) -> int:
        """Resolve a branch name, tag name or (short) commit hash to a commit id."""
        b = self.catalog.get_branch(ref)
        if b is not None:
            return b["head_commit_id"]
        t = self.catalog.tags.get(ref)
        if t is not None:
            return t["commit_id"]
        return self._resolve_commit_id(ref)

    def _head(self, branch_name: str) -> int:
        b = self.catalog.get_branch(branch_name)
        if b is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
        return b["head_commit_id"]

    def _read_key(self, key: str, commit_id: int) -> Optional[Dict[str, Any]]:
        anc = self.catalog.ancestors(commit_id)
        pid = self.btree.resolve_version(key, commit_id, lambda a, _t: a in anc)
        if pid is None or pid == INVALID_PAGE_ID:
            return None
        return read_row_data(self.pool, pid)

    def _resolve_table_data(self, table_name: str, target_commit_id: int) -> List[Dict[str, Any]]:
        anc = self.catalog.ancestors(target_commit_id)
        fn = lambda a, _t: a in anc  # noqa: E731
        results = []
        for row_id in self.catalog.tables.get(table_name, []):
            pid = self.btree.resolve_version(f"{table_name}:{row_id}", target_commit_id, fn)
            if pid is not None and pid != INVALID_PAGE_ID:
                data = read_row_data(self.pool, pid)
                if data is not None:
                    row = {"row_id": row_id}
                    row.update(data)
                    results.append(row)
        return results

    # ──────────────────────────────────────────────
    # Branches & tags
    # ──────────────────────────────────────────────

    def branch(self, name: str, source_branch: Optional[str] = "main", pull_from_main: bool = True) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("Branch name cannot be empty")
        if any(ch in name for ch in " ~^:?*[\\"):
            raise ValueError("Branch name contains invalid characters")
        if self.catalog.get_branch(name) is not None:
            raise ValueError(f"Branch '{name}' already exists")

        now = time.time()
        if pull_from_main and source_branch:
            source = self.catalog.get_branch(source_branch)
            if source is None:
                raise ValueError(f"Source branch '{source_branch}' does not exist")
            base = source["head_commit_id"]
            self.catalog.add_branch(name, base, created_at=now, created_from=source_branch, base_commit_id=base)
            # Marker commit so the branch's own history starts with its origin
            self.commit(branch_name=name, message=f"Pulled state from {source_branch}",
                        author="system", changes=None)
        else:
            cid = self._alloc_id()
            with self._operation(cid):
                self.catalog.add_commit(cid, {
                    "id": cid,
                    "hash": _compute_hash("None", "None", name, f"Initial commit for {name}", str(now), "system"),
                    "parent_id": None,
                    "second_parent_id": None,
                    "branch_id": name,
                    "message": f"Initial commit for {name}",
                    "timestamp": now,
                    "author": "system",
                    "stats": {"insert": 0, "update": 0, "delete": 0},
                })
                self.catalog.add_branch(name, cid, created_at=now, created_from=None, base_commit_id=None)

        b = self.catalog.get_branch(name)
        return {"id": name, "name": b["name"], "head_commit_id": b["head_commit_id"]}  # type: ignore[index]

    def checkout(self, branch_name: str) -> str:
        if self.catalog.get_branch(branch_name) is None:
            raise ValueError(f"Branch '{branch_name}' does not exist")
        self._current_branch = branch_name
        return branch_name

    def get_current_branch(self) -> str:
        return self._current_branch

    def list_branches(self, detailed: bool = False) -> List[Dict[str, Any]]:
        out = []
        main_anc = self.catalog.ancestors(self.catalog.branches["main"]["head_commit_id"]) if detailed and "main" in self.catalog.branches else None
        for name, b in self.catalog.branches.items():
            item: Dict[str, Any] = {"id": name, "name": b["name"], "head_commit_id": b["head_commit_id"]}
            if detailed:
                head = self.catalog.get_commit(b["head_commit_id"]) or {}
                anc = self.catalog.ancestors(b["head_commit_id"])
                item.update({
                    "head_hash": head.get("hash"),
                    "head_message": head.get("message"),
                    "head_author": head.get("author"),
                    "updated_at": head.get("timestamp"),
                    "created_at": b.get("created_at"),
                    "created_from": b.get("created_from"),
                    "commit_count": len(anc),
                    "ahead": len(anc - main_anc) if main_anc is not None else 0,
                    "behind": len(main_anc - anc) if main_anc is not None else 0,
                    "is_current": name == self._current_branch,
                })
            out.append(item)
        return out

    def delete_branch(self, name: str) -> bool:
        with self._operation():
            if name == self._current_branch:
                self._current_branch = "main"
            return self.catalog.delete_branch(name)

    def rename_branch(self, old: str, new: str) -> Dict[str, Any]:
        if old == "main":
            raise ValueError("Cannot rename the 'main' branch")
        b = self.catalog.get_branch(old)
        if b is None:
            raise ValueError(f"Branch '{old}' does not exist")
        if self.catalog.get_branch(new) is not None:
            raise ValueError(f"Branch '{new}' already exists")
        with self._operation():
            meta = {k: v for k, v in b.items() if k not in ("name", "head_commit_id")}
            self.catalog.delete_branch(old)
            self.catalog.add_branch(new, b["head_commit_id"], **meta)
            if self._current_branch == old:
                self._current_branch = new
        return {"id": new, "name": new, "head_commit_id": b["head_commit_id"]}

    def create_tag(self, name: str, ref: str, message: str = "", author: str = "user") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("Tag name cannot be empty")
        if name in self.catalog.tags:
            raise ValueError(f"Tag '{name}' already exists")
        cid = self.resolve_ref(ref)
        with self._operation():
            self.catalog.add_tag(name, cid, message=message, author=author, created_at=time.time())
        return self.list_tags_by_name(name)

    def list_tags_by_name(self, name: str) -> Dict[str, Any]:
        t = self.catalog.tags[name]
        c = self.catalog.get_commit(t["commit_id"]) or {}
        return {**t, "hash": c.get("hash"), "commit_message": c.get("message")}

    def list_tags(self) -> List[Dict[str, Any]]:
        return [self.list_tags_by_name(n) for n in sorted(self.catalog.tags)]

    def delete_tag(self, name: str) -> bool:
        with self._operation():
            return self.catalog.delete_tag(name)

    # ──────────────────────────────────────────────
    # Commits
    # ──────────────────────────────────────────────

    def _validate_changes(self, changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        clean = []
        for i, ch in enumerate(changes):
            action = ch.get("action")
            if action not in VALID_ACTIONS:
                raise ValueError(f"Change {i}: unknown action '{action}'")
            table = str(ch.get("table_name") or "").strip()
            if not table or ":" in table:
                raise ValueError(f"Change {i}: invalid table name")
            row_id = ch.get("row_id")
            if row_id is None or str(row_id).strip() == "":
                raise ValueError(f"Change {i}: row_id is required")
            row_id = str(row_id).strip()
            data = ch.get("data")
            if action != "delete":
                if not isinstance(data, dict):
                    raise ValueError(f"Change {i}: data must be an object")
                data = {k: v for k, v in data.items() if k != "row_id"}
                size = len(json.dumps(data).encode("utf-8"))
                if size >= MAX_ROW_BYTES:
                    raise ValueError(f"Change {i}: row is {size} bytes; the limit is {MAX_ROW_BYTES - 1}")
            clean.append({"action": "update" if action == "upsert" else action,
                          "table_name": table, "row_id": row_id, "data": data})
        return clean

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
        message = (message or "").strip() or "(no message)"
        if len(message) > 1000:
            message = message[:1000]
        author = (author or "").strip() or "anonymous"
        changes = self._validate_changes(changes or [])

        now = time.time()
        parent_id = branch["head_commit_id"]
        txn_id = self._alloc_id()
        stats = {"insert": 0, "update": 0, "delete": 0}

        with self._operation(txn_id):
            for change in changes:
                table_name, row_id, action = change["table_name"], change["row_id"], change["action"]
                key = f"{table_name}:{row_id}"
                self.catalog.register_row_key(table_name, row_id)
                if action in ("insert", "update"):
                    page = self.pool.new_page()
                    if not page:
                        raise RuntimeError("Buffer pool exhausted allocating row page")
                    data_bytes = json.dumps(change["data"]).encode("utf-8")
                    page.data[: len(data_bytes)] = data_bytes
                    pid = page.page_id
                    self.pool.unpin_page(pid, is_dirty=True)
                    self.btree.insert(key, txn_id, pid)
                else:
                    self.btree.insert(key, txn_id, INVALID_PAGE_ID)  # tombstone
                stats[action] += 1

            commit_data = {
                "id": txn_id,
                "hash": _compute_hash(str(parent_id), str(second_parent_id), branch_name,
                                      message, str(now), author, _changes_digest(changes)),
                "parent_id": parent_id,
                "second_parent_id": second_parent_id,
                "branch_id": branch_name,
                "message": message,
                "timestamp": now,
                "author": author,
                "stats": stats,
            }
            self.catalog.add_commit(txn_id, commit_data)
            self.catalog.update_branch_head(branch_name, txn_id)
        return commit_data

    def get_commit_history(self, branch_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Commits made on this branch itself, newest first (first-parent walk)."""
        current_id: Optional[int] = self._head(branch_name)
        history = []
        while current_id is not None and len(history) < limit:
            c = self.catalog.get_commit(current_id)
            if c is None:
                break
            if c["branch_id"] == branch_name:
                history.append(c)
            current_id = c["parent_id"]
        return history

    def get_log(self, ref: str, limit: int = 200, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Every commit reachable from ref (like `git log`), newest first, with refs attached."""
        anc = self.catalog.ancestors(self.resolve_ref(ref))
        ids = sorted(anc, reverse=True)
        heads: Dict[int, List[str]] = {}
        for n, b in self.catalog.branches.items():
            heads.setdefault(b["head_commit_id"], []).append(n)
        tags: Dict[int, List[str]] = {}
        for n, t in self.catalog.tags.items():
            tags.setdefault(t["commit_id"], []).append(n)
        page = []
        for cid in ids[offset: offset + limit]:
            c = dict(self.catalog.commits[cid])
            c["branch_heads"] = heads.get(cid, [])
            c["tags"] = tags.get(cid, [])
            page.append(c)
        return page, len(ids)

    def get_all_commits(self) -> List[Dict[str, Any]]:
        return [self.catalog.commits[c] for c in sorted(self.catalog.commits)]

    def get_commit(self, ref: str) -> Dict[str, Any]:
        """Commit metadata plus the row changes it introduced (vs. its first parent)."""
        cid = self.resolve_ref(ref)
        c = dict(self.catalog.commits[cid])
        parent = c.get("parent_id")
        if parent is None:
            c["changes"] = {"tables": {}}
        else:
            c["changes"] = self._diff_ids(parent, cid)
        c["parent_hash"] = (self.catalog.get_commit(parent) or {}).get("hash") if parent else None
        sp = c.get("second_parent_id")
        c["second_parent_hash"] = (self.catalog.get_commit(sp) or {}).get("hash") if sp else None
        return c

    # ──────────────────────────────────────────────
    # Rollback
    # ──────────────────────────────────────────────

    def rollback(self, branch_name: str, target_commit_hash: str, author: str) -> Dict[str, Any]:
        head = self._head(branch_name)
        target_id = self._resolve_commit_id(target_commit_hash)
        if not self.catalog.is_ancestor(target_id, head):
            raise ValueError(f"Commit '{target_commit_hash}' is not in branch '{branch_name}' history")

        changes = []
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                at_target = self._read_key(key, target_id)
                at_head = self._read_key(key, head)
                if at_target == at_head:
                    continue  # only rows that differ need a new version
                if at_target is None:
                    changes.append({"action": "delete", "table_name": table_name, "row_id": row_id, "data": None})
                else:
                    changes.append({"action": "update", "table_name": table_name, "row_id": row_id, "data": at_target})

        short = self.catalog.commits[target_id]["hash"]
        return self.commit(branch_name, f"Rollback to commit {short}", author, changes=changes)

    def revert_commit(self, branch_name: str, commit_hash: str, author: str) -> Dict[str, Any]:
        """
        Undo the changes of a single commit on top of the branch head (like
        `git revert <commit>`). Rows that changed again after that commit are
        reported as conflicts instead of being overwritten.
        """
        head = self._head(branch_name)
        cid = self._resolve_commit_id(commit_hash)
        if not self.catalog.is_ancestor(cid, head):
            raise ValueError("Commit is not in this branch's history")
        c = self.catalog.commits[cid]
        parent = c.get("parent_id")
        if parent is None:
            raise ValueError("Cannot revert the root commit")
        diff = self._diff_ids(parent, cid)
        changes, conflicts = [], []
        for table, t in diff["tables"].items():
            for r in t["rows"]:
                key = f"{table}:{r['row_id']}"
                now_val = self._read_key(key, head)
                if now_val != r["data_b"]:
                    conflicts.append({"table_name": table, "row_id": r["row_id"]})
                    continue
                if r["data_a"] is None:
                    changes.append({"action": "delete", "table_name": table, "row_id": r["row_id"]})
                else:
                    changes.append({"action": "update", "table_name": table, "row_id": r["row_id"], "data": r["data_a"]})
        if conflicts:
            return {"reverted": False, "conflicts": conflicts}
        commit = self.commit(branch_name, f"Revert \"{c['message']}\" ({c['hash'][:8]})", author, changes=changes)
        return {"reverted": True, "commit": commit}

    # ──────────────────────────────────────────────
    # Reads
    # ──────────────────────────────────────────────

    def get_data(self, branch_name: str, table_name: str) -> List[Dict[str, Any]]:
        return self._resolve_table_data(table_name, self._head(branch_name))

    def get_row(self, branch_name: str, table_name: str, row_id: str) -> Optional[Dict[str, Any]]:
        data = self._read_key(f"{table_name}:{row_id}", self._head(branch_name))
        return None if data is None else {"row_id": row_id, **data}

    def read_table_at(self, table_name: str, commit_id: int) -> List[Dict[str, Any]]:
        return self._resolve_table_data(table_name, commit_id)

    def tables_at(self, commit_id: int) -> List[str]:
        anc = self.catalog.ancestors(commit_id)
        fn = lambda a, _t: a in anc  # noqa: E731
        active = []
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                pid = self.btree.resolve_version(f"{table_name}:{row_id}", commit_id, fn)
                if pid is not None and pid != INVALID_PAGE_ID:
                    active.append(table_name)
                    break
        return sorted(active)

    def get_tables(self, branch_name: str) -> List[str]:
        return self.tables_at(self._head(branch_name))

    def table_schema(self, table_name: str, commit_id: int) -> Dict[str, Any]:
        rows = self._resolve_table_data(table_name, commit_id)
        cols: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            for k, v in r.items():
                if k == "row_id":
                    continue
                t = "null" if v is None else "boolean" if isinstance(v, bool) else \
                    "integer" if isinstance(v, int) else "number" if isinstance(v, float) else \
                    "object" if isinstance(v, (dict, list)) else "text"
                info = cols.setdefault(k, {"name": k, "types": set(), "non_null": 0})
                info["types"].add(t)
                if v is not None:
                    info["non_null"] += 1
        columns = []
        for k, info in cols.items():
            types = sorted(info["types"] - {"null"}) or ["null"]
            columns.append({"name": k, "type": types[0] if len(types) == 1 else "mixed",
                            "nullable": info["non_null"] < len(rows)})
        return {"table": table_name, "row_count": len(rows), "columns": columns}

    def row_history(self, table_name: str, row_id: str, ref: str = "main") -> List[Dict[str, Any]]:
        """Versions of one row visible in ref's history, newest first (a row-level `git blame`)."""
        key = f"{table_name}:{row_id}"
        chain = self.btree.get_chain(key) or []
        anc = self.catalog.ancestors(self.resolve_ref(ref))
        out = []
        for cid, pid in reversed(chain):
            if cid not in anc:
                continue
            c = self.catalog.commits.get(cid, {})
            data = None if pid == INVALID_PAGE_ID else read_row_data(self.pool, pid)
            out.append({
                "commit_id": cid, "hash": c.get("hash"), "message": c.get("message"),
                "author": c.get("author"), "timestamp": c.get("timestamp"),
                "branch_id": c.get("branch_id"),
                "deleted": pid == INVALID_PAGE_ID, "data": data,
                "storage": "tombstone" if pid == INVALID_PAGE_ID else "delta" if is_packed_ref(pid) else "snapshot",
            })
        return out

    # ── Time travel ──

    def query_as_of_commit(self, table_name: str, commit_hash: str) -> List[Dict[str, Any]]:
        return self._resolve_table_data(table_name, self._resolve_commit_id(commit_hash))

    def commit_at_timestamp(self, timestamp: float, branch_name: str = "main") -> int:
        """Newest commit in branch_name's history made at or before timestamp."""
        anc = self.catalog.ancestors(self._head(branch_name))
        best = None
        for cid in anc:
            c = self.catalog.commits.get(cid)
            if c and c["timestamp"] <= timestamp:
                if best is None or (c["timestamp"], cid) > best[0]:
                    best = ((c["timestamp"], cid), cid)
        if best is None:
            raise ValueError(f"No commits exist at or before timestamp {timestamp}")
        return best[1]

    def query_as_of_timestamp(self, table_name: str, timestamp: float, branch_name: str = "main") -> List[Dict[str, Any]]:
        return self._resolve_table_data(table_name, self.commit_at_timestamp(timestamp, branch_name))

    # ──────────────────────────────────────────────
    # Diff & merge
    # ──────────────────────────────────────────────

    def _diff_ids(self, id_a: int, id_b: int) -> Dict[str, Any]:
        anc_a, anc_b = self.catalog.ancestors(id_a), self.catalog.ancestors(id_b)
        fa = lambda a, _t: a in anc_a  # noqa: E731
        fb = lambda a, _t: a in anc_b  # noqa: E731
        tables_diff: Dict[str, Dict[str, list]] = {}
        summary = {"added": 0, "deleted": 0, "modified": 0}
        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                pa = self.btree.resolve_version(key, id_a, fa)
                pb = self.btree.resolve_version(key, id_b, fb)
                if pa == pb:
                    continue  # same version object → identical
                da = read_row_data(self.pool, pa) if pa not in (None, INVALID_PAGE_ID) else None
                db = read_row_data(self.pool, pb) if pb not in (None, INVALID_PAGE_ID) else None
                if da == db:
                    continue
                if da is not None and db is None:
                    row = {"row_id": row_id, "status": "deleted", "data_a": da, "data_b": None}
                elif da is None and db is not None:
                    row = {"row_id": row_id, "status": "added", "data_a": None, "data_b": db}
                else:
                    fields = sorted(set(da) | set(db))  # type: ignore[arg-type]
                    row = {"row_id": row_id, "status": "modified", "data_a": da, "data_b": db,
                           "changed_fields": [f for f in fields if da.get(f) != db.get(f)]}  # type: ignore[union-attr]
                summary[row["status"]] += 1
                tables_diff.setdefault(table_name, {"rows": []})["rows"].append(row)
        return {"tables": tables_diff, "summary": summary}

    def diff(self, commit_hash_a: str, commit_hash_b: str) -> Dict[str, Any]:
        """Per-table, per-row diff between two refs (commit hashes, branches or tags)."""
        return self._diff_ids(self.resolve_ref(commit_hash_a), self.resolve_ref(commit_hash_b))

    def merge(
        self,
        source_branch: str,
        target_branch: str,
        author: str,
        resolutions: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
        dry_run: bool = False,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Three-way merge of source_branch into target_branch.

        Returns {"merged": True, "commit": ..., "strategy": ...} on success,
        {"merged": False, "conflicting_rows": [...]} on conflict. With
        dry_run=True nothing is written and a preview is returned.
        """
        if source_branch == target_branch:
            raise ValueError("Cannot merge a branch into itself")
        merger = ThreeWayMerge(self.catalog, self.btree, self.pool)
        result = merger.merge(source_branch, target_branch, author, resolutions, dry_run=dry_run)

        if dry_run or not result["merged"]:
            return result
        if result.get("strategy") in ("fast-forward", "up-to-date"):
            if result.get("strategy") == "fast-forward":
                with self._operation():
                    self.catalog.update_branch_head(target_branch, result["source_head"])
                result["commit"] = self.catalog.get_commit(result["source_head"])
            return result

        merge_commit = self.commit(
            branch_name=target_branch,
            message=message or result["message"],
            author=result["author"],
            changes=result.get("changes"),
            second_parent_id=result["source_head"],
        )
        return {"merged": True, "commit": merge_commit, "strategy": "three-way",
                "applied_changes": result.get("rows_changed_on_target", len(result.get("changes") or [])),
                "auto_merged_rows": result.get("auto_merged_rows", [])}

    # ──────────────────────────────────────────────
    # Maintenance
    # ──────────────────────────────────────────────

    def gc(self) -> GCReport:
        """Mark-and-sweep: reclaim versions only reachable from deleted branches."""
        with self._operation():
            report = GarbageCollector(self.catalog, self.btree, self.pool, self.heap).collect()
        return report

    def optimize_storage(self, cold_threshold: int = 5) -> OptimizerReport:
        """Delta-encode versions older than cold_threshold commits into the packed heap."""
        with self._operation():
            report = StorageOptimizer(self.catalog, self.btree, self.pool,
                                      cold_threshold=cold_threshold, heap=self.heap).optimize()
        return report

    def get_storage_stats(self) -> Dict[str, Any]:
        stats = StorageOptimizer(self.catalog, self.btree, self.pool, heap=self.heap).get_storage_stats()
        stats.update(self.get_file_stats())
        return stats

    def get_file_stats(self) -> Dict[str, Any]:
        total = self.disk.get_num_pages()
        free = len(self.disk.free_pages)
        return {
            "pages_total": total,
            "pages_free": free,
            "pages_live": total - free,
            "file_bytes": total * PAGE_SIZE,
            "live_bytes": (total - free) * PAGE_SIZE,
            "wal_bytes": self.wal.get_wal_size_bytes(),
        }

    def get_overview(self) -> Dict[str, Any]:
        row_keys = sum(len(v) for v in self.catalog.tables.values())
        return {
            "commits": len(self.catalog.commits),
            "branches": len(self.catalog.branches),
            "tags": len(self.catalog.tags),
            "tables": len(self.catalog.tables),
            "row_keys": row_keys,
            "current_branch": self._current_branch,
            "last_recovery": self.last_recovery,
            **self.get_file_stats(),
        }
