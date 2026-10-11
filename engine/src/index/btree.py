"""
ChronoDB Storage Engine — Version-Aware B+ Tree

A B+ tree over primary keys, backed by the Buffer Pool Manager. Leaf entries
map a key to a *version chain*, a list of (commit_id, page_version_id) pairs
ordered oldest to newest, rather than to a single record pointer.

Long version chains
-------------------
A row that is updated many times would eventually have a chain too large for
a 4 KB leaf page. When a chain grows beyond CHAIN_INLINE_MAX entries, its
oldest CHAIN_SPILL entries are moved to an overflow page and replaced by a
marker entry (OVERFLOW_MARK, overflow_page_id). Overflow pages form a linked
list from newest to oldest, so a version lookup reads the inline (recent)
part first and only touches overflow pages for older versions.

Root tracking
-------------
The root moves when it splits. The tree reports the new root through
``on_root_change`` so that the system catalog can persist it; reopening a
database therefore always starts from the correct root.
"""

import json
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from ..storage.buffer_pool import BufferPoolManager
from ..storage.page import INVALID_PAGE_ID, PAGE_SIZE
from .btree_node import BTreeNode, BTreeInternalNode, BTreeLeafNode

OVERFLOW_MARK = -7          # commit ids are always positive
CHAIN_INLINE_MAX = 48       # inline entries before spilling
CHAIN_SPILL = 32            # entries moved per overflow page

Chain = List[Tuple[int, int]]


def _node_size(node: BTreeNode) -> int:
    return len(json.dumps(node.to_dict()).encode("utf-8"))


class BTreeIndex:
    """Page-backed, version-aware B+ tree."""

    def __init__(
        self,
        buffer_pool: BufferPoolManager,
        root_page_id: int = INVALID_PAGE_ID,
        on_root_change: Optional[Callable[[int], None]] = None,
    ):
        self.buffer_pool = buffer_pool
        self.root_page_id = root_page_id
        self.on_root_change = on_root_change
        # Decoded read-only copies of nodes and overflow chunks. Any write to a
        # page (reported by the buffer pool) drops its entry.
        self._cache: Dict[int, object] = {}
        buffer_pool.write_listeners.append(self._invalidate)

        if self.root_page_id == INVALID_PAGE_ID:
            page = self.buffer_pool.new_page()
            if not page:
                raise RuntimeError("Buffer pool out of memory allocating root page")
            self.root_page_id = page.page_id
            BTreeLeafNode(page_id=self.root_page_id).serialize_to_page(page)
            self.buffer_pool.unpin_page(self.root_page_id, is_dirty=True)
            self._notify_root()

    # ────────────────────────────────────────────────
    # Node I/O helpers
    # ────────────────────────────────────────────────

    def _invalidate(self, page_id: int) -> None:
        self._cache.pop(page_id, None)

    def _read_node(self, page_id: int) -> BTreeNode:
        """Decoded node for read-only use (cached). Callers must not mutate it."""
        node = self._cache.get(page_id)
        if node is None:
            node = self._fetch_node(page_id)
            self._unpin_node_clean(page_id)
            if len(self._cache) > 4096:
                self._cache.clear()
            self._cache[page_id] = node
        return node  # type: ignore[return-value]

    def _leaf_ro(self, key: str) -> BTreeLeafNode:
        pid = self.root_page_id
        node = self._read_node(pid)
        while not node.is_leaf:
            internal: BTreeInternalNode = node  # type: ignore[assignment]
            idx = len(internal.keys)
            for i, k in enumerate(internal.keys):
                if key < k:
                    idx = i
                    break
            node = self._read_node(internal.children[idx])
        return node  # type: ignore[return-value]

    def _notify_root(self) -> None:
        if self.on_root_change:
            self.on_root_change(self.root_page_id)

    def _fetch_node(self, page_id: int) -> BTreeNode:
        """Fetch and deserialize a node. The caller MUST unpin it."""
        page = self.buffer_pool.fetch_page(page_id)
        if not page:
            raise RuntimeError(f"Failed to fetch page {page_id}")
        return BTreeNode.deserialize_from_page(page)

    def _save_node(self, node: BTreeNode) -> None:
        """Serialize a node (fetched earlier with _fetch_node) and unpin it."""
        page = self.buffer_pool.fetch_page(node.page_id)
        if not page:
            raise RuntimeError(f"Failed to fetch page {node.page_id} for saving")
        try:
            node.serialize_to_page(page)
        finally:
            self.buffer_pool.unpin_page(node.page_id, is_dirty=True)
        self.buffer_pool.unpin_page(node.page_id, is_dirty=True)

    def _unpin_node_clean(self, page_id: int) -> None:
        self.buffer_pool.unpin_page(page_id, is_dirty=False)

    def find_leaf(self, key: str) -> BTreeLeafNode:
        """Return the (pinned) leaf that should contain key."""
        curr_page_id = self.root_page_id
        while True:
            node = self._fetch_node(curr_page_id)
            if node.is_leaf:
                return node  # type: ignore[return-value]
            internal: BTreeInternalNode = node  # type: ignore[assignment]
            child_idx = len(internal.keys)
            for i, k in enumerate(internal.keys):
                if key < k:
                    child_idx = i
                    break
            next_page_id = internal.children[child_idx]
            self._unpin_node_clean(curr_page_id)
            curr_page_id = next_page_id

    # ────────────────────────────────────────────────
    # Overflow pages for long version chains
    # ────────────────────────────────────────────────

    def _write_overflow(self, prev_page_id: int, versions: Chain) -> int:
        page = self.buffer_pool.new_page()
        if not page:
            raise RuntimeError("Out of memory allocating chain overflow page")
        payload = json.dumps({"prev": prev_page_id, "v": [list(v) for v in versions]}).encode("utf-8")
        if len(payload) > PAGE_SIZE:
            raise ValueError("Overflow chunk exceeds page size")
        page.data[: len(payload)] = payload
        pid = page.page_id
        self.buffer_pool.unpin_page(pid, is_dirty=True)
        return pid

    def _read_overflow(self, page_id: int) -> Tuple[int, Chain]:
        hit = self._cache.get(page_id)
        if hit is not None:
            return hit  # type: ignore[return-value]
        page = self.buffer_pool.fetch_page(page_id)
        if not page:
            raise RuntimeError(f"Failed to fetch overflow page {page_id}")
        try:
            end = page.data.find(b"\x00")
            raw = bytes(page.data[: end if end != -1 else PAGE_SIZE])
        finally:
            self.buffer_pool.unpin_page(page_id, is_dirty=False)
        d = json.loads(raw.decode("utf-8"))
        res = (d["prev"], [tuple(v) for v in d["v"]])
        self._cache[page_id] = res
        return res  # type: ignore[return-value]

    def _overflow_pages(self, inline: Chain) -> List[int]:
        pages: List[int] = []
        if inline and inline[0][0] == OVERFLOW_MARK:
            pid = inline[0][1]
            while pid != INVALID_PAGE_ID:
                pages.append(pid)
                pid, _ = self._read_overflow(pid)
        return pages

    def _expand(self, inline: Chain) -> Chain:
        """Full chain (oldest → newest) for an inline entry list."""
        if not inline or inline[0][0] != OVERFLOW_MARK:
            return [tuple(v) for v in inline]  # type: ignore[misc]
        chunks: List[Chain] = []
        pid = inline[0][1]
        while pid != INVALID_PAGE_ID:
            pid, versions = self._read_overflow(pid)
            chunks.append(versions)
        full: Chain = []
        for chunk in reversed(chunks):
            full.extend(chunk)
        full.extend(tuple(v) for v in inline[1:])  # type: ignore[misc]
        return full

    def _maybe_spill(self, leaf: BTreeLeafNode, key: str) -> None:
        inline = leaf.entries[key]
        has_mark = bool(inline) and inline[0][0] == OVERFLOW_MARK
        body = inline[1:] if has_mark else inline
        if len(body) <= CHAIN_INLINE_MAX:
            return
        prev = inline[0][1] if has_mark else INVALID_PAGE_ID
        spill, keep = body[:CHAIN_SPILL], body[CHAIN_SPILL:]
        new_ovf = self._write_overflow(prev, spill)
        leaf.entries[key] = [(OVERFLOW_MARK, new_ovf)] + list(keep)

    def _build_inline(self, chain: Chain) -> Chain:
        """Lay out a full chain as overflow pages + inline tail."""
        chain = [tuple(v) for v in chain]  # type: ignore[misc]
        if len(chain) <= CHAIN_INLINE_MAX:
            return chain
        n_spill = len(chain) - CHAIN_INLINE_MAX
        n_spill = ((n_spill + CHAIN_SPILL - 1) // CHAIN_SPILL) * CHAIN_SPILL
        n_spill = min(n_spill, len(chain))
        prev = INVALID_PAGE_ID
        for i in range(0, n_spill, CHAIN_SPILL):
            prev = self._write_overflow(prev, chain[i : min(i + CHAIN_SPILL, n_spill)])
        return [(OVERFLOW_MARK, prev)] + chain[n_spill:]

    # ────────────────────────────────────────────────
    # Insert & split
    # ────────────────────────────────────────────────

    def insert(self, key: str, commit_id: int, page_version_id: int) -> None:
        """Append a version to key's chain, splitting nodes as needed."""
        leaf = self.find_leaf(key)
        leaf.append_version(key, commit_id, page_version_id)
        self._maybe_spill(leaf, key)
        if _node_size(leaf) <= PAGE_SIZE:
            self._save_node(leaf)
        else:
            self._split_leaf(leaf)

    def _split_leaf(self, leaf: BTreeLeafNode) -> None:
        keys = leaf.get_sorted_keys()
        mid_idx = len(keys) // 2
        if mid_idx == 0:
            raise RuntimeError("Cannot split a leaf node holding a single oversized entry")
        split_key = keys[mid_idx]

        new_page = self.buffer_pool.new_page()
        if not new_page:
            raise RuntimeError("Out of memory splitting leaf")
        new_leaf = BTreeLeafNode(page_id=new_page.page_id, parent_id=leaf.parent_id)
        for k in keys[mid_idx:]:
            new_leaf.entries[k] = leaf.entries.pop(k)
        new_leaf.next_page_id = leaf.next_page_id
        leaf.next_page_id = new_leaf.page_id
        new_leaf.serialize_to_page(new_page)
        self.buffer_pool.unpin_page(new_leaf.page_id, is_dirty=True)

        self._insert_into_parent(leaf, split_key, new_leaf.page_id)

    def _insert_into_parent(self, left_node: BTreeNode, key: str, right_page_id: int) -> None:
        if left_node.parent_id == INVALID_PAGE_ID:
            new_root_page = self.buffer_pool.new_page()
            if not new_root_page:
                raise RuntimeError("Out of memory allocating new root")
            new_root = BTreeInternalNode(page_id=new_root_page.page_id)
            new_root.keys = [key]
            new_root.children = [left_node.page_id, right_page_id]
            left_node.parent_id = new_root.page_id

            right_node = self._fetch_node(right_page_id)
            right_node.parent_id = new_root.page_id
            self._save_node(right_node)
            self._save_node(left_node)

            new_root.serialize_to_page(new_root_page)
            self.buffer_pool.unpin_page(new_root.page_id, is_dirty=True)
            self.root_page_id = new_root.page_id
            self._notify_root()
            return

        parent = self._fetch_node(left_node.parent_id)
        assert isinstance(parent, BTreeInternalNode)
        parent.insert_child(key, right_page_id)
        self._save_node(left_node)
        if _node_size(parent) <= PAGE_SIZE:
            self._save_node(parent)
        else:
            self._split_internal(parent)

    def _split_internal(self, node: BTreeInternalNode) -> None:
        mid_idx = len(node.keys) // 2
        push_up_key = node.keys[mid_idx]

        new_page = self.buffer_pool.new_page()
        if not new_page:
            raise RuntimeError("Out of memory splitting internal node")
        new_node = BTreeInternalNode(page_id=new_page.page_id, parent_id=node.parent_id)
        new_node.keys = node.keys[mid_idx + 1:]
        new_node.children = node.children[mid_idx + 1:]
        node.keys = node.keys[:mid_idx]
        node.children = node.children[:mid_idx + 1]

        for child_id in new_node.children:
            child = self._fetch_node(child_id)
            child.parent_id = new_node.page_id
            self._save_node(child)

        new_node.serialize_to_page(new_page)
        self.buffer_pool.unpin_page(new_node.page_id, is_dirty=True)
        self._insert_into_parent(node, push_up_key, new_node.page_id)

    # ────────────────────────────────────────────────
    # Chain access
    # ────────────────────────────────────────────────

    def get_chain(self, key: str) -> Optional[Chain]:
        """Full version chain for key (oldest → newest), or None."""
        inline = self._leaf_ro(key).entries.get(key)
        if inline is None:
            return None
        return self._expand(inline)

    def set_chain(self, key: str, chain: Chain) -> None:
        """Replace key's whole version chain (used by GC and the optimizer)."""
        leaf = self.find_leaf(key)
        if key not in leaf.entries:
            self._unpin_node_clean(leaf.page_id)
            raise KeyError(key)
        old_pages = self._overflow_pages(leaf.entries[key])
        leaf.entries[key] = self._build_inline(chain)
        if _node_size(leaf) <= PAGE_SIZE:
            self._save_node(leaf)
        else:
            self._split_leaf(leaf)
        for pid in old_pages:
            self.buffer_pool.delete_page(pid)

    def iter_keys(self) -> Iterator[str]:
        """Yield every key in sorted order by walking the leaf level."""
        pid = self.root_page_id
        node = self._fetch_node(pid)
        while not node.is_leaf:
            child = node.children[0]  # type: ignore[attr-defined]
            self._unpin_node_clean(pid)
            pid = child
            node = self._fetch_node(pid)
        while True:
            keys = node.get_sorted_keys()  # type: ignore[attr-defined]
            nxt = node.next_page_id  # type: ignore[attr-defined]
            self._unpin_node_clean(pid)
            yield from keys
            if nxt == INVALID_PAGE_ID:
                return
            pid = nxt
            node = self._fetch_node(pid)

    # ────────────────────────────────────────────────
    # Version-chain resolver
    # ────────────────────────────────────────────────

    def resolve_version(
        self,
        key: str,
        target_commit_id: int,
        is_ancestor_fn: Callable[[int, int], bool],
    ) -> Optional[int]:
        """
        Return the page_version_id visible at target_commit_id: the newest
        version whose commit is the target or one of its ancestors. Returns
        None when the key has no visible version (INVALID_PAGE_ID marks a
        delete).
        """
        inline = self._leaf_ro(key).entries.get(key)
        if inline is None:
            return None

        for commit_id, page_version_id in reversed(inline):
            if commit_id == OVERFLOW_MARK:
                break
            if is_ancestor_fn(commit_id, target_commit_id):
                return page_version_id

        if inline and inline[0][0] == OVERFLOW_MARK:
            pid = inline[0][1]
            while pid != INVALID_PAGE_ID:
                pid, versions = self._read_overflow(pid)
                for commit_id, page_version_id in reversed(versions):
                    if is_ancestor_fn(commit_id, target_commit_id):
                        return page_version_id
        return None
