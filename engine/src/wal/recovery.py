"""
ChronoDB Storage Engine — Redo-Only Crash Recovery

Implements ARIES-inspired redo-only recovery:

  1. ANALYSIS — Read the WAL, find the last CHECKPOINT, identify which
     transactions committed and which were still active (uncommitted) at
     the time of the crash.

  2. REDO — Replay UPDATE records from committed transactions by writing
     their after-images to the corresponding pages on disk.

  3. DISCARD — Uncommitted transactions (no COMMIT record found) are
     simply ignored — their partial writes are never applied.

This guarantees that after recovery the database reflects exactly the set
of committed transactions, regardless of when the crash occurred.
"""

from typing import Any, Dict, Set

from .log_record import LogRecord, LogRecordType
from .wal_manager import WALManager
from ..storage.disk_manager import DiskManager
from ..storage.page import PAGE_SIZE


class RecoveryManager:
    """
    Redo-only crash recovery manager.

    On restart after a crash, call `recover()` to replay committed
    mutations from the WAL and restore the database to a consistent state.

    Args:
        wal_manager: The WALManager to read log records from.
        disk_manager: The DiskManager to write recovered pages to.
    """

    def __init__(self, wal_manager: WALManager, disk_manager: DiskManager):
        self.wal = wal_manager
        self.disk = disk_manager

    def recover(self) -> Dict[str, Any]:
        """
        Execute redo-only crash recovery.

        Steps:
          1. Read all valid WAL records (incomplete records from a crash
             are automatically discarded by WALManager.read_all()).
          2. Find the last CHECKPOINT record.
          3. Scan forward from the checkpoint to determine which
             transactions committed.
          4. Redo all UPDATE records belonging to committed transactions
             by writing their after-images directly to disk pages.
          5. Skip all records from uncommitted transactions.

        Returns:
            A dict summarizing the recovery:
              - status: "clean" (no WAL records) or "recovered"
              - redone: number of page writes replayed
              - discarded: number of uncommitted updates skipped
              - committed_txns: count of committed transactions
              - uncommitted_txns: count of uncommitted transactions
        """
        records = self.wal.read_all()

        if not records:
            return {
                "status": "clean",
                "redone": 0,
                "discarded": 0,
                "committed_txns": 0,
                "uncommitted_txns": 0,
            }

        # ── ANALYSIS PHASE ──
        # Find the last checkpoint
        last_checkpoint_idx = -1
        for i, r in enumerate(records):
            if r.record_type == LogRecordType.CHECKPOINT:
                last_checkpoint_idx = i

        # Start scanning from after the last checkpoint
        start_idx = last_checkpoint_idx + 1 if last_checkpoint_idx >= 0 else 0

        # Determine transaction outcomes
        committed_txns: Set[int] = set()
        aborted_txns: Set[int] = set()
        active_txns: Set[int] = set()

        for r in records[start_idx:]:
            if r.record_type == LogRecordType.BEGIN:
                active_txns.add(r.txn_id)
            elif r.record_type == LogRecordType.COMMIT:
                committed_txns.add(r.txn_id)
                active_txns.discard(r.txn_id)
            elif r.record_type == LogRecordType.ABORT:
                aborted_txns.add(r.txn_id)
                active_txns.discard(r.txn_id)

        # Transactions still active at crash time → uncommitted
        uncommitted_txns = active_txns

        # ── REDO PHASE ──
        redone = 0
        discarded = 0

        for r in records[start_idx:]:
            if r.record_type == LogRecordType.UPDATE and r.after_image is not None:
                if r.txn_id in committed_txns:
                    # Redo: write the after-image to disk
                    self._redo_update(r)
                    redone += 1
                else:
                    # Uncommitted → discard (do NOT apply)
                    discarded += 1

        return {
            "status": "recovered",
            "redone": redone,
            "discarded": discarded,
            "committed_txns": len(committed_txns),
            "uncommitted_txns": len(uncommitted_txns),
        }

    def _redo_update(self, record: LogRecord) -> None:
        """
        Apply a single UPDATE record's after-image to disk.

        Ensures the page exists on disk (extending the file if needed)
        before writing the after-image.
        """
        page_id = record.page_id
        after_image = record.after_image

        if after_image is None:
            return

        # Ensure the page slot exists on disk
        while self.disk.get_num_pages() <= page_id:
            self.disk.allocate_page()

        # Pad or truncate to PAGE_SIZE
        data = bytearray(PAGE_SIZE)
        data[: len(after_image)] = after_image[:PAGE_SIZE]

        self.disk.write_page(page_id, data)

    def __repr__(self) -> str:
        return f"RecoveryManager(wal={self.wal!r})"
