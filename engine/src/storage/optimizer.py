"""
ChronoDB Storage Engine — Adaptive Storage Optimizer

Background job & on-demand optimizer that identifies "cold" page versions in
version chains (versions superseded by N or more commits) and converts them
from full 4KB snapshots to compact delta-encoded pages relative to base snapshots.
"""

from dataclasses import dataclass
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .buffer_pool import BufferPoolManager
from .page import PAGE_SIZE, INVALID_PAGE_ID
from .delta import is_delta_page, encode_delta_page
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages_scanned": self.pages_scanned,
            "pages_compressed": self.pages_compressed,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_saved": self.bytes_saved,
            "savings_percent": round(self.savings_percent, 2),
            "cold_threshold": self.cold_threshold,
        }

    def summary(self) -> str:
        return (
            f"Storage Optimizer Summary:\n"
            f"  Cold threshold:      {self.cold_threshold} commits\n"
            f"  Pages scanned:       {self.pages_scanned}\n"
            f"  Pages compressed:    {self.pages_compressed}\n"
            f"  Storage before:      {self.bytes_before:,} bytes\n"
            f"  Storage after:       {self.bytes_after:,} bytes\n"
            f"  Storage saved:       {self.bytes_saved:,} bytes ({self.savings_percent:.1f}% reduction)"
        )


class StorageOptimizer:
    """
    Adaptive Storage Optimizer for ChronoDB.
    
    Identifies cold versions in primary key version chains and compresses them
    into forward deltas encoded against their nearest non-cold base ancestor.
    """

    def __init__(
        self,
        catalog: Any,
        btree: Any,
        pool: BufferPoolManager,
        cold_threshold: int = 5,
    ):
        self.catalog = catalog
        self.btree = btree
        self.pool = pool
        self.cold_threshold = max(1, cold_threshold)

    def optimize(self, cold_threshold: Optional[int] = None) -> OptimizerReport:
        """
        Run the storage optimization pass across all registered tables and rows.
        
        Args:
            cold_threshold: Override the default commit age threshold for cold versions.
            
        Returns:
            An OptimizerReport detailing bytes saved and pages compressed.
        """
        threshold = cold_threshold if cold_threshold is not None else self.cold_threshold

        pages_scanned = 0
        pages_compressed = 0
        bytes_before = 0
        bytes_after = 0

        for table_name, row_ids in list(self.catalog.tables.items()):
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                leaf = self.btree.find_leaf(key)
                
                if key not in leaf.entries:
                    self.btree._unpin_node_clean(leaf.page_id)
                    continue

                version_chain = list(leaf.entries[key])
                self.btree._unpin_node_clean(leaf.page_id)

                # Need at least 2 versions to have a base + delta candidate
                if len(version_chain) <= 1:
                    continue

                # Identify base ancestor (first non-tombstone version in chain)
                base_idx = -1
                for idx, (commit_id, page_id) in enumerate(version_chain):
                    if page_id != INVALID_PAGE_ID:
                        base_idx = idx
                        break

                if base_idx == -1:
                    continue

                base_commit_id, base_page_id = version_chain[base_idx]

                # Any version at index i < len(version_chain) - threshold is cold
                cold_boundary = len(version_chain) - threshold

                for i in range(base_idx + 1, cold_boundary):
                    curr_commit_id, curr_page_id = version_chain[i]

                    if curr_page_id == INVALID_PAGE_ID or curr_page_id == base_page_id:
                        continue

                    # Fetch page to examine
                    page = self.pool.fetch_page(curr_page_id)
                    if not page:
                        continue

                    pages_scanned += 1
                    page_used = page._used_bytes()
                    bytes_before += page_used

                    if is_delta_page(page.data):
                        # Already compressed
                        bytes_after += page_used
                        self.pool.unpin_page(curr_page_id, is_dirty=False)
                        continue

                    # Unpin page before reading row data to avoid pin deadlocks
                    self.pool.unpin_page(curr_page_id, is_dirty=False)

                    # Read full row data for base and current version
                    base_data = read_row_data(self.pool, base_page_id)
                    curr_data = read_row_data(self.pool, curr_page_id)

                    if base_data is None or curr_data is None:
                        bytes_after += page_used
                        continue

                    # Compute and encode delta
                    delta_bytes = encode_delta_page(base_data, curr_data, base_page_id)

                    # Write delta to page
                    page = self.pool.fetch_page(curr_page_id)
                    if page:
                        page.data[:] = b"\x00" * PAGE_SIZE
                        page.data[:len(delta_bytes)] = delta_bytes
                        new_used = len(delta_bytes)
                        bytes_after += new_used
                        pages_compressed += 1
                        self.pool.unpin_page(curr_page_id, is_dirty=True)
                    else:
                        bytes_after += page_used

        # Flush modified pages to disk
        self.pool.flush_all_pages()

        bytes_saved = max(0, bytes_before - bytes_after)
        savings_percent = (bytes_saved / bytes_before * 100.0) if bytes_before > 0 else 0.0

        report = OptimizerReport(
            pages_scanned=pages_scanned,
            pages_compressed=pages_compressed,
            bytes_before=bytes_before,
            bytes_after=bytes_after,
            bytes_saved=bytes_saved,
            savings_percent=savings_percent,
            cold_threshold=threshold,
        )

        logger.info(report.summary())
        return report

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Scan all version chains and return storage statistics.
        """
        total_versions = 0
        full_snapshots = 0
        deltas = 0
        total_used_bytes = 0

        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                leaf = self.btree.find_leaf(key)
                if key not in leaf.entries:
                    self.btree._unpin_node_clean(leaf.page_id)
                    continue

                for commit_id, page_id in leaf.entries[key]:
                    if page_id == INVALID_PAGE_ID:
                        continue
                    total_versions += 1
                    page = self.pool.fetch_page(page_id)
                    if page:
                        used = page._used_bytes()
                        total_used_bytes += used
                        if is_delta_page(page.data):
                            deltas += 1
                        else:
                            full_snapshots += 1
                        self.pool.unpin_page(page_id, is_dirty=False)

                self.btree._unpin_node_clean(leaf.page_id)

        return {
            "total_versions": total_versions,
            "full_snapshots": full_snapshots,
            "deltas": deltas,
            "total_used_bytes": total_used_bytes,
        }
