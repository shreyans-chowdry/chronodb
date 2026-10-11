"""
ChronoDB Storage Engine — Packed Delta Heap

Cold row versions that the storage optimizer converts to deltas are small
(often a few dozen bytes). Storing each one in its own 4 KB page would save
payload bytes but not disk pages, so deltas are packed many-to-a-page in
"heap" pages instead, and the 4 KB snapshot page they replace is returned to
the free list.

A packed delta is addressed by a negative *record reference* stored in the
B+ tree version chain in place of a page id:

    ref = -2 - (heap_page_id * SLOTS_PER_PAGE + slot)

so that  -1 (INVALID_PAGE_ID) keeps meaning "tombstone"
and any value <= -2 means "packed delta record".

Heap page layout (4 KB):
    byte 0       : HEAP_MAGIC (0xDA)
    bytes 1..n   : UTF-8 JSON {"r": [record | null, ...]}
    remainder    : zero padding
Each record is [base_page_id, {"set": {...}, "del": [...]}].
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .page import PAGE_SIZE

HEAP_MAGIC = 0xDA
SLOTS_PER_PAGE = 4096


def is_packed_ref(ref: Optional[int]) -> bool:
    return ref is not None and ref <= -2


def make_ref(page_id: int, slot: int) -> int:
    return -2 - (page_id * SLOTS_PER_PAGE + slot)


def split_ref(ref: int) -> Tuple[int, int]:
    x = -2 - ref
    return x // SLOTS_PER_PAGE, x % SLOTS_PER_PAGE


def is_heap_page(data: bytearray) -> bool:
    return len(data) > 0 and data[0] == HEAP_MAGIC


def _decode(data: bytearray) -> List[Any]:
    end = data.find(b"\x00", 1)
    if end == -1:
        end = PAGE_SIZE
    if end <= 1:
        return []
    return json.loads(bytes(data[1:end]).decode("utf-8"))["r"]


def _encode(records: List[Any]) -> bytes:
    return bytes([HEAP_MAGIC]) + json.dumps({"r": records}, separators=(",", ":")).encode("utf-8")


def record_size(base_page_id: int, delta: Dict[str, Any]) -> int:
    """Bytes a record occupies inside a heap page (its JSON encoding plus separator)."""
    return len(json.dumps([base_page_id, delta], separators=(",", ":"))) + 1


def read_packed(pool: Any, ref: int) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Return (base_page_id, delta) for a packed record, or None if it is gone."""
    page_id, slot = split_ref(ref)
    page = pool.fetch_page(page_id)
    if not page:
        return None
    try:
        if not is_heap_page(page.data):
            return None
        records = _decode(page.data)
    finally:
        pool.unpin_page(page_id, is_dirty=False)
    if slot >= len(records) or records[slot] is None:
        return None
    base_page_id, delta = records[slot]
    return base_page_id, delta


class DeltaHeap:
    """Append-only allocator for packed delta records."""

    def __init__(self, pool: Any, tail_page_id: int = -1):
        self.pool = pool
        self.tail_page_id = tail_page_id

    def append(self, base_page_id: int, delta: Dict[str, Any]) -> int:
        rec = [base_page_id, delta]
        if self.tail_page_id >= 0:
            page = self.pool.fetch_page(self.tail_page_id)
            if page and is_heap_page(page.data):
                records = _decode(page.data)
                records.append(rec)
                encoded = _encode(records)
                if len(encoded) <= PAGE_SIZE and len(records) <= SLOTS_PER_PAGE:
                    page.data[:] = b"\x00" * PAGE_SIZE
                    page.data[: len(encoded)] = encoded
                    self.pool.unpin_page(self.tail_page_id, is_dirty=True)
                    return make_ref(self.tail_page_id, len(records) - 1)
            if page:
                self.pool.unpin_page(self.tail_page_id, is_dirty=False)

        page = self.pool.new_page()
        if not page:
            raise RuntimeError("Buffer pool exhausted allocating heap page")
        encoded = _encode([rec])
        if len(encoded) > PAGE_SIZE:
            self.pool.unpin_page(page.page_id, is_dirty=False)
            self.pool.delete_page(page.page_id)
            raise ValueError("Delta record larger than a page")
        page.data[: len(encoded)] = encoded
        self.tail_page_id = page.page_id
        self.pool.unpin_page(page.page_id, is_dirty=True)
        return make_ref(page.page_id, 0)

    def free(self, ref: int) -> bool:
        """Mark a record dead. Frees the page when every record on it is dead.
        Returns True if a whole page was released."""
        page_id, slot = split_ref(ref)
        page = self.pool.fetch_page(page_id)
        if not page:
            return False
        if not is_heap_page(page.data):
            self.pool.unpin_page(page_id, is_dirty=False)
            return False
        records = _decode(page.data)
        if slot < len(records):
            records[slot] = None
        if all(r is None for r in records) and page_id != self.tail_page_id:
            self.pool.unpin_page(page_id, is_dirty=False)
            self.pool.delete_page(page_id)
            return True
        encoded = _encode(records)
        page.data[:] = b"\x00" * PAGE_SIZE
        page.data[: len(encoded)] = encoded
        self.pool.unpin_page(page_id, is_dirty=True)
        return False
