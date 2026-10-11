"""
ChronoDB Storage Engine — Storage Optimizer

Identifies *cold* versions in each key's version chain and rewrites them as
deltas against a full-snapshot base.

Policy
  * A version is cold when at least ``cold_threshold`` newer versions of the
    same key exist (version age measured in commits to that key). The newest
    ``cold_threshold`` versions always stay as full snapshots, so recent
    history reads need no reconstruction.
  * The base is the oldest live full snapshot in the chain. It is never
    compressed, so every delta is exactly one hop from a snapshot.
  * Deltas are packed into shared heap pages (see heap.py) and the 4 KB
    snapshot page each one replaces is returned to the free list. The
    optimizer therefore reduces both payload bytes and allocated pages.

The report gives two views of the saving:
  * payload bytes of the versions that were compressed (bytes_before → bytes_after),
    the measure used in the original evaluation, and
  * allocated bytes of the whole database file (live pages × 4 KB).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .buffer_pool import BufferPoolManager
from .delta import compute_delta, is_delta_page, decode_delta_page
from .heap import DeltaHeap, is_packed_ref, read_packed, record_size
from .page import PAGE_SIZE, INVALID_PAGE_ID
from .reader import read_row_data

logger = logging.getLogger("chronodb.optimizer")


@dataclass
class OptimizerReport:
    """Statistics produced by a storage optimization run."""
    pages_scanned: int
    pages_compressed: int
    bytes_before: int
    bytes_after: int
    bytes_saved: int
    savings_percent: float
    cold_threshold: int
    keys_scanned: int = 0
    live_bytes_before: int = 0
    live_bytes_after: int = 0
    heap_pages_added: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        live_saved = max(0, self.live_bytes_before - self.live_bytes_after)
        return {
            "pages_scanned": self.pages_scanned,
            "pages_compressed": self.pages_compressed,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_saved": self.bytes_saved,
            "savings_percent": round(self.savings_percent, 2),
            "cold_threshold": self.cold_threshold,
            "keys_scanned": self.keys_scanned,
            "live_bytes_before": self.live_bytes_before,
            "live_bytes_after": self.live_bytes_after,
            "live_bytes_saved": live_saved,
            "live_savings_percent": round(100.0 * live_saved / self.live_bytes_before, 2) if self.live_bytes_before else 0.0,
            "heap_pages_added": self.heap_pages_added,
            "duration_ms": round(self.duration_ms, 2),
        }

    def summary(self) -> str:
        d = self.to_dict()
        return (
            f"Storage Optimizer Summary:\n"
            f"  Cold threshold:      {self.cold_threshold} commits\n"
            f"  Versions scanned:    {self.pages_scanned}\n"
            f"  Versions compressed: {self.pages_compressed}\n"
            f"  Payload bytes:       {self.bytes_before:,} -> {self.bytes_after:,} "
            f"({self.savings_percent:.1f}% reduction)\n"
            f"  Allocated bytes:     {self.live_bytes_before:,} -> {self.live_bytes_after:,} "
            f"({d['live_savings_percent']:.1f}% reduction)\n"
            f"  Duration:            {self.duration_ms:.1f} ms"
        )


def _snapshot_payload(pool: BufferPoolManager, page_id: int) -> Optional[int]:
    """Payload length of a full-snapshot page, or None if it is not one."""
    page = pool.fetch_page(page_id)
    if not page:
        return None
    try:
        if is_delta_page(page.data) or page.data[0] == 0:
            return None
        end = page.data.find(b"\x00")
        return PAGE_SIZE if end == -1 else end
    finally:
        pool.unpin_page(page_id, is_dirty=False)


class StorageOptimizer:
    """Converts cold full-snapshot versions into packed deltas."""

    def __init__(
        self,
        catalog: Any,
        btree: Any,
        pool: BufferPoolManager,
        cold_threshold: int = 5,
        heap: Optional[DeltaHeap] = None,
    ):
        self.catalog = catalog
        self.btree = btree
        self.pool = pool
        self.cold_threshold = max(1, cold_threshold)
        self.heap = heap if heap is not None else DeltaHeap(pool, getattr(catalog, "heap_tail", -1))

    def _keys(self) -> List[str]:
        return [f"{t}:{r}" for t, rows in list(self.catalog.tables.items()) for r in rows]

    def optimize(self, cold_threshold: Optional[int] = None) -> OptimizerReport:
        threshold = max(1, cold_threshold if cold_threshold is not None else self.cold_threshold)
        t0 = time.perf_counter()
        disk = self.pool.disk_manager
        live_before = disk.get_num_live_pages() * PAGE_SIZE
        heap_pages_before = disk.get_num_pages()

        pages_scanned = pages_compressed = bytes_before = bytes_after = keys_scanned = 0
        freed: List[int] = []

        for key in self._keys():
            chain = self.btree.get_chain(key)
            if not chain or len(chain) <= 1:
                continue
            keys_scanned += 1

            base_idx = next((i for i, (_, ref) in enumerate(chain)
                             if ref != INVALID_PAGE_ID and not is_packed_ref(ref)
                             and _snapshot_payload(self.pool, ref) is not None), -1)
            if base_idx == -1:
                continue
            base_ref = chain[base_idx][1]
            base_data = read_row_data(self.pool, base_ref)
            if base_data is None:
                continue

            cold_boundary = len(chain) - threshold
            changed = False
            for i in range(base_idx + 1, cold_boundary):
                cid, ref = chain[i]
                if ref == INVALID_PAGE_ID or ref == base_ref:
                    continue
                pages_scanned += 1
                if is_packed_ref(ref):
                    rec = read_packed(self.pool, ref)
                    sz = record_size(rec[0], rec[1]) if rec else 0
                    bytes_before += sz
                    bytes_after += sz
                    continue
                payload = _snapshot_payload(self.pool, ref)
                if payload is None:
                    # legacy in-place delta page: count as already compressed
                    page = self.pool.fetch_page(ref)
                    used = page._used_bytes() if page else 0
                    if page:
                        self.pool.unpin_page(ref, is_dirty=False)
                    bytes_before += used
                    bytes_after += used
                    continue

                curr = read_row_data(self.pool, ref)
                if curr is None:
                    bytes_before += payload
                    bytes_after += payload
                    continue
                delta = compute_delta(base_data, curr)
                new_ref = self.heap.append(base_ref, delta)
                bytes_before += payload
                bytes_after += record_size(base_ref, delta)
                chain[i] = (cid, new_ref)
                freed.append(ref)
                pages_compressed += 1
                changed = True

            if changed:
                self.btree.set_chain(key, chain)

        for pid in freed:
            self.pool.delete_page(pid)

        if hasattr(self.catalog, "heap_tail"):
            self.catalog.heap_tail = self.heap.tail_page_id
            if hasattr(self.catalog, "mark_dirty"):
                self.catalog.mark_dirty()

        bytes_saved = max(0, bytes_before - bytes_after)
        report = OptimizerReport(
            pages_scanned=pages_scanned,
            pages_compressed=pages_compressed,
            bytes_before=bytes_before,
            bytes_after=bytes_after,
            bytes_saved=bytes_saved,
            savings_percent=(bytes_saved / bytes_before * 100.0) if bytes_before else 0.0,
            cold_threshold=threshold,
            keys_scanned=keys_scanned,
            live_bytes_before=live_before,
            live_bytes_after=disk.get_num_live_pages() * PAGE_SIZE,
            heap_pages_added=max(0, disk.get_num_pages() - heap_pages_before),
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )
        logger.info(report.summary())
        return report

    def get_storage_stats(self) -> Dict[str, Any]:
        """Count versions by representation and sum their payload bytes."""
        total_versions = full_snapshots = deltas = tombstones = 0
        total_used_bytes = 0
        for key in self._keys():
            for _cid, ref in self.btree.get_chain(key) or []:
                if ref == INVALID_PAGE_ID:
                    tombstones += 1
                    continue
                total_versions += 1
                if is_packed_ref(ref):
                    rec = read_packed(self.pool, ref)
                    deltas += 1
                    total_used_bytes += record_size(rec[0], rec[1]) if rec else 0
                    continue
                page = self.pool.fetch_page(ref)
                if not page:
                    continue
                total_used_bytes += page._used_bytes()
                if is_delta_page(page.data):
                    deltas += 1
                else:
                    full_snapshots += 1
                self.pool.unpin_page(ref, is_dirty=False)
        return {
            "total_versions": total_versions,
            "full_snapshots": full_snapshots,
            "deltas": deltas,
            "tombstones": tombstones,
            "total_used_bytes": total_used_bytes,
        }
