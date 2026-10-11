"""
ChronoDB Storage Engine — System Catalog

Persists database metadata in the page store.

Layout (format version 2)
-------------------------
* Header (page chain starting at the catalog root, normally page 0): a small
  JSON document holding branches, tags, the B+ tree root, the free-page list,
  the packed-delta heap tail and the heads/tails of two append-only logs.
* Commit log: an append-only chain of pages, one JSON line per commit.
* Key log:    an append-only chain of pages, one JSON line per (table, row_id)
  registration.

Earlier versions rewrote the whole catalog, including every commit, on each
change, which made every commit O(history). With append-only logs a commit
appends one line and rewrites only the small header.

Databases written by the original single-document format (version 1) are
migrated transparently the first time they are opened.

Header and log changes are made in the buffer pool; ``flush()`` writes a
dirty header. The version engine calls ``flush()`` once per operation and
then logs the dirty pages to the WAL, so metadata is recovered together with
row data after a crash.
"""

import json
from collections import OrderedDict
from typing import Any, Dict, FrozenSet, List, Optional, Set

from ..storage.buffer_pool import BufferPoolManager
from ..storage.page import PAGE_SIZE, INVALID_PAGE_ID

_HDR = 8  # next_page_id (4) + used_len (4)
_ANC_CACHE_SIZE = 64


class _PageChain:
    """Helpers for linked page chains: [next:int32][len:uint32][payload]."""

    def __init__(self, pool: BufferPoolManager):
        self.pool = pool

    def read(self, head: int) -> bytes:
        out = bytearray()
        pid = head
        seen = set()
        while pid != INVALID_PAGE_ID and pid not in seen:
            seen.add(pid)
            page = self.pool.fetch_page(pid)
            if not page:
                break
            nxt = int.from_bytes(page.data[:4], "big", signed=True)
            ln = int.from_bytes(page.data[4:8], "big", signed=False)
            if ln == 0 and nxt == 0:
                self.pool.unpin_page(pid, is_dirty=False)
                break
            out.extend(page.data[_HDR:_HDR + ln])
            self.pool.unpin_page(pid, is_dirty=False)
            pid = nxt
        return bytes(out)

    def pages(self, head: int) -> List[int]:
        res = []
        pid = head
        while pid != INVALID_PAGE_ID and pid not in res:
            page = self.pool.fetch_page(pid)
            if not page:
                break
            nxt = int.from_bytes(page.data[:4], "big", signed=True)
            ln = int.from_bytes(page.data[4:8], "big", signed=False)
            self.pool.unpin_page(pid, is_dirty=False)
            res.append(pid)
            if ln == 0 and nxt == 0:
                break
            pid = nxt
        return res

    def write(self, head: int, data: bytes) -> None:
        """Overwrite a chain starting at head, reusing / extending / freeing pages."""
        cap = PAGE_SIZE - _HDR
        existing = self.pages(head)
        n_needed = max(1, (len(data) + cap - 1) // cap)
        pids = existing[:n_needed]
        while len(pids) < n_needed:
            p = self.pool.new_page()
            if not p:
                raise RuntimeError("Out of memory extending catalog chain")
            pids.append(p.page_id)
            self.pool.unpin_page(p.page_id, is_dirty=True)
        for i, pid in enumerate(pids):
            chunk = data[i * cap:(i + 1) * cap]
            nxt = pids[i + 1] if i + 1 < len(pids) else INVALID_PAGE_ID
            page = self.pool.fetch_page(pid)
            if not page:
                raise RuntimeError(f"Failed to fetch catalog page {pid}")
            page.data[:] = b"\x00" * PAGE_SIZE
            page.data[:4] = nxt.to_bytes(4, "big", signed=True)
            page.data[4:8] = len(chunk).to_bytes(4, "big", signed=False)
            page.data[_HDR:_HDR + len(chunk)] = chunk
            self.pool.unpin_page(pid, is_dirty=True)
        for pid in existing[n_needed:]:
            self.pool.delete_page(pid)


class _AppendLog:
    """Append-only log of JSON lines stored in a page chain."""

    def __init__(self, pool: BufferPoolManager, head: int = INVALID_PAGE_ID, tail: int = INVALID_PAGE_ID):
        self.pool = pool
        self.head = head
        self.tail = tail

    def _new_page(self) -> int:
        p = self.pool.new_page()
        if not p:
            raise RuntimeError("Out of memory extending catalog log")
        p.data[:4] = INVALID_PAGE_ID.to_bytes(4, "big", signed=True)
        p.data[4:8] = (0).to_bytes(4, "big")
        pid = p.page_id
        self.pool.unpin_page(pid, is_dirty=True)
        return pid

    def append(self, record: Any) -> None:
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        cap = PAGE_SIZE - _HDR
        if len(line) > cap:
            raise ValueError("Catalog record larger than a page")
        if self.head == INVALID_PAGE_ID:
            self.head = self.tail = self._new_page()
        page = self.pool.fetch_page(self.tail)
        if not page:
            raise RuntimeError("Failed to fetch catalog log tail")
        used = int.from_bytes(page.data[4:8], "big")
        if used + len(line) > cap:
            new_pid = self._new_page()
            page.data[:4] = new_pid.to_bytes(4, "big", signed=True)
            self.pool.unpin_page(self.tail, is_dirty=True)
            self.tail = new_pid
            page = self.pool.fetch_page(self.tail)
            if not page:
                raise RuntimeError("Failed to fetch catalog log tail")
            used = 0
        page.data[_HDR + used:_HDR + used + len(line)] = line
        page.data[4:8] = (used + len(line)).to_bytes(4, "big")
        self.pool.unpin_page(self.tail, is_dirty=True)

    def read_all(self) -> List[Any]:
        if self.head == INVALID_PAGE_ID:
            return []
        raw = _PageChain(self.pool).read(self.head)
        return [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]

    def page_ids(self) -> List[int]:
        if self.head == INVALID_PAGE_ID:
            return []
        return _PageChain(self.pool).pages(self.head)

    def rewrite(self, records: List[Any]) -> None:
        old = self.page_ids()
        self.head = self.tail = INVALID_PAGE_ID
        for r in records:
            self.append(r)
        for pid in old:
            self.pool.delete_page(pid)


class SystemCatalog:
    """Branches, tags, the commit DAG and the table → row-key directory."""

    FORMAT_VERSION = 2

    def __init__(self, buffer_pool: BufferPoolManager, root_page_id: int):
        self.pool = buffer_pool
        self.root_page_id = root_page_id
        self._chain = _PageChain(buffer_pool)

        self.branches: Dict[str, Dict[str, Any]] = {}
        self.tags: Dict[str, Dict[str, Any]] = {}
        self.commits: Dict[int, Dict[str, Any]] = {}
        self.tables: Dict[str, List[str]] = {}
        self._table_sets: Dict[str, Set[str]] = {}
        self._hash_index: Dict[str, int] = {}
        self.btree_root: int = INVALID_PAGE_ID
        self.heap_tail: int = INVALID_PAGE_ID
        self.next_txn_id: int = 1
        self.extra: Dict[str, Any] = {}

        self.commit_log = _AppendLog(buffer_pool)
        self.key_log = _AppendLog(buffer_pool)
        self._dirty = False
        self._anc_cache: "OrderedDict[int, FrozenSet[int]]" = OrderedDict()
        self.migrated_from_v1 = False

        self.load()

    # ────────────────────────────────────────────────
    # Persistence
    # ────────────────────────────────────────────────

    def load(self) -> None:
        raw = self._chain.read(self.root_page_id)
        if not raw:
            return
        state = json.loads(raw.decode("utf-8"))

        if state.get("v") != self.FORMAT_VERSION:
            self._load_v1(state)
            return

        self.branches = state.get("branches", {})
        self.tags = state.get("tags", {})
        self.btree_root = state.get("btree_root", INVALID_PAGE_ID)
        self.heap_tail = state.get("heap_tail", INVALID_PAGE_ID)
        self.next_txn_id = state.get("next_txn_id", 1)
        self.extra = state.get("extra", {})
        self.pool.disk_manager.free_pages = list(state.get("free_pages", []))
        cl, kl = state.get("commit_log", {}), state.get("key_log", {})
        self.commit_log = _AppendLog(self.pool, cl.get("head", -1), cl.get("tail", -1))
        self.key_log = _AppendLog(self.pool, kl.get("head", -1), kl.get("tail", -1))

        for c in self.commit_log.read_all():
            if c.get("_removed"):
                for cid in c["_removed"]:
                    self.commits.pop(cid, None)
                continue
            self.commits[c["id"]] = c
        for t, r in self.key_log.read_all():
            self._add_key_mem(t, r)
        self._rebuild_hash_index()

    def _load_v1(self, state: Dict[str, Any]) -> None:
        """Migrate the original single-JSON-document catalog."""
        self.branches = state.get("branches", {})
        self.commits = {int(k): v for k, v in state.get("commits", {}).items()}
        for t, rows in state.get("tables", {}).items():
            for r in rows:
                self._add_key_mem(t, r)
        self.btree_root = 1  # v1 always created the B+ tree root at page 1
        self.next_txn_id = (max(self.commits) + 1) if self.commits else 1
        for cid in sorted(self.commits):
            self.commit_log.append(self.commits[cid])
        for t, rows in self.tables.items():
            for r in rows:
                self.key_log.append([t, r])
        self._rebuild_hash_index()
        self.migrated_from_v1 = True
        self._dirty = True
        self.flush()

    def flush(self) -> None:
        """Write the header if anything in it changed."""
        if not self._dirty:
            return
        state = {
            "v": self.FORMAT_VERSION,
            "branches": self.branches,
            "tags": self.tags,
            "btree_root": self.btree_root,
            "heap_tail": self.heap_tail,
            "next_txn_id": self.next_txn_id,
            "free_pages": sorted(self.pool.disk_manager.free_pages),
            "commit_log": {"head": self.commit_log.head, "tail": self.commit_log.tail},
            "key_log": {"head": self.key_log.head, "tail": self.key_log.tail},
            "extra": self.extra,
        }
        self._chain.write(self.root_page_id, json.dumps(state, separators=(",", ":")).encode("utf-8"))
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    # Backwards-compatible name used by older callers
    def save(self) -> None:
        self._dirty = True
        self.flush()

    # ────────────────────────────────────────────────
    # Commits
    # ────────────────────────────────────────────────

    def add_commit(self, commit_id: int, commit_data: Dict[str, Any]) -> None:
        self.commits[commit_id] = commit_data
        self._hash_index[commit_data["hash"]] = commit_id
        self.commit_log.append(commit_data)
        if commit_id >= self.next_txn_id:
            self.next_txn_id = commit_id + 1
        self._dirty = True

    def get_commit(self, commit_id: int) -> Optional[Dict[str, Any]]:
        return self.commits.get(commit_id)

    def commit_id_for_hash(self, commit_hash: str) -> Optional[int]:
        cid = self._hash_index.get(commit_hash)
        if cid is not None:
            return cid
        # Allow unambiguous short prefixes, like Git
        if len(commit_hash) >= 4:
            matches = [c for h, c in self._hash_index.items() if h.startswith(commit_hash)]
            if len(matches) == 1:
                return matches[0]
        return None

    def _rebuild_hash_index(self) -> None:
        self._hash_index = {c["hash"]: cid for cid, c in self.commits.items()}

    def remove_commits(self, commit_ids: set) -> int:
        removed = [cid for cid in commit_ids if cid in self.commits]
        for cid in removed:
            del self.commits[cid]
        if removed:
            self._rebuild_hash_index()
            self._anc_cache.clear()
            self.commit_log.rewrite([self.commits[c] for c in sorted(self.commits)])
            self._dirty = True
        return len(removed)

    # ────────────────────────────────────────────────
    # Branches & tags
    # ────────────────────────────────────────────────

    def add_branch(self, name: str, head_commit_id: int, **meta: Any) -> None:
        self.branches[name] = {"name": name, "head_commit_id": head_commit_id, **meta}
        self._dirty = True

    def update_branch_head(self, name: str, head_commit_id: int) -> None:
        if name in self.branches:
            self.branches[name]["head_commit_id"] = head_commit_id
            self._dirty = True

    def get_branch(self, name: str) -> Optional[Dict[str, Any]]:
        return self.branches.get(name)

    def delete_branch(self, name: str) -> bool:
        if name == "main":
            raise ValueError("Cannot delete the 'main' branch")
        if name not in self.branches:
            return False
        del self.branches[name]
        self._dirty = True
        return True

    def add_tag(self, name: str, commit_id: int, **meta: Any) -> None:
        self.tags[name] = {"name": name, "commit_id": commit_id, **meta}
        self._dirty = True

    def delete_tag(self, name: str) -> bool:
        if self.tags.pop(name, None) is None:
            return False
        self._dirty = True
        return True

    # ────────────────────────────────────────────────
    # Table directory
    # ────────────────────────────────────────────────

    def _add_key_mem(self, table_name: str, row_id: str) -> bool:
        s = self._table_sets.setdefault(table_name, set())
        if row_id in s:
            return False
        s.add(row_id)
        self.tables.setdefault(table_name, []).append(row_id)
        return True

    def register_row_key(self, table_name: str, row_id: str) -> None:
        if self._add_key_mem(table_name, row_id):
            self.key_log.append([table_name, row_id])
            self._dirty = True

    def has_row_key(self, table_name: str, row_id: str) -> bool:
        return row_id in self._table_sets.get(table_name, ())

    # ────────────────────────────────────────────────
    # DAG queries
    # ────────────────────────────────────────────────

    def ancestors(self, commit_id: int) -> FrozenSet[int]:
        """All ancestors of commit_id, including itself (cached; commits are immutable)."""
        cached = self._anc_cache.get(commit_id)
        if cached is not None:
            self._anc_cache.move_to_end(commit_id)
            return cached

        commit = self.commits.get(commit_id)
        if commit is None:
            return frozenset()
        parents = [p for p in (commit.get("parent_id"), commit.get("second_parent_id")) if p is not None]
        if parents and all(p in self._anc_cache for p in parents):
            acc: Set[int] = set(self._anc_cache[parents[0]])
            for p in parents[1:]:
                acc |= self._anc_cache[p]
            acc.add(commit_id)
        else:
            acc = set()
            stack = [commit_id]
            while stack:
                cid = stack.pop()
                if cid in acc:
                    continue
                if cid in self._anc_cache and cid != commit_id:
                    acc |= self._anc_cache[cid]
                    continue
                acc.add(cid)
                c = self.commits.get(cid)
                if c:
                    for p in (c.get("parent_id"), c.get("second_parent_id")):
                        if p is not None and p not in acc:
                            stack.append(p)
        result = frozenset(acc)
        self._anc_cache[commit_id] = result
        if len(self._anc_cache) > _ANC_CACHE_SIZE:
            self._anc_cache.popitem(last=False)
        return result

    def is_ancestor(self, ancestor_id: int, target_id: int) -> bool:
        """True if ancestor_id is target_id or one of its ancestors."""
        if ancestor_id == target_id:
            return True
        return ancestor_id in self.ancestors(target_id)

    def find_lca(self, commit_id_a: int, commit_id_b: int) -> Optional[int]:
        """
        Lowest common ancestor: a common ancestor that is not an ancestor of
        any other common ancestor. If several exist (criss-cross merges), the
        most recent one (highest commit id) is returned.
        """
        if commit_id_a == commit_id_b:
            return commit_id_a
        common = self.ancestors(commit_id_a) & self.ancestors(commit_id_b)
        if not common:
            return None
        # A common ancestor that is the parent of another common ancestor is
        # not "lowest"; the set of ancestors is closed under parents, so this
        # single pass finds the frontier.
        has_child: Set[int] = set()
        for c in common:
            commit = self.commits.get(c)
            if commit:
                for p in (commit.get("parent_id"), commit.get("second_parent_id")):
                    if p is not None:
                        has_child.add(p)
        best = [c for c in common if c not in has_child]
        return max(best) if best else max(common)
