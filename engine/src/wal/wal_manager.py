"""
ChronoDB Storage Engine — Write-Ahead Log Manager

Enforces the WAL protocol: every page mutation MUST be appended to the WAL
before it is applied to the in-memory buffer pool page. This guarantees
durability — even if the process crashes, committed data can be recovered by
replaying the WAL.

Key operations:
  - append(record)  — serialize and fsync a log record to the WAL file
  - read_all()      — read all VALID records (skipping truncated/corrupt tails)
  - checkpoint()    — flush dirty pages, write CHECKPOINT record, truncate WAL
  - begin_txn()     — convenience: append BEGIN record
  - commit_txn()    — convenience: append COMMIT record
  - log_update()    — convenience: append UPDATE record with after-image
"""

import os
import struct
import threading
from typing import List, Optional

from .log_record import LogRecord, LogRecordType


class WALManager:
    """
    Append-only Write-Ahead Log backed by a single file.

    Thread-safety: All writes are serialized via a lock.

    Args:
        wal_path: Path to the WAL file. Created if it doesn't exist.
    """

    def __init__(self, wal_path: str):
        self.wal_path = wal_path
        self._lock = threading.Lock()
        self._next_lsn: int = 1
        self._next_txn_id: int = 1

        # Create WAL file if it doesn't exist
        if not os.path.exists(wal_path):
            with open(wal_path, "wb"):
                pass
        else:
            # Recover LSN counter from existing records
            records = self.read_all()
            if records:
                self._next_lsn = records[-1].lsn + 1
                # Recover txn_id counter
                max_txn = max(r.txn_id for r in records)
                self._next_txn_id = max_txn + 1

    # ──────────────────────────────────────────────
    # Core WAL Operations
    # ──────────────────────────────────────────────

    def append(self, record: LogRecord) -> int:
        """
        Append a log record to the WAL file with fsync durability.

        The record is assigned a new LSN before writing. This is the
        fundamental write-ahead operation — it MUST complete before any
        corresponding buffer pool modification.

        Args:
            record: The log record to append.

        Returns:
            The assigned LSN.
        """
        with self._lock:
            record.lsn = self._next_lsn
            self._next_lsn += 1

            serialized = record.serialize()

            with open(self.wal_path, "ab") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())

            return record.lsn

    def read_all(self) -> List[LogRecord]:
        """
        Read all valid log records from the WAL file.

        Stops reading at the first incomplete or corrupted record (which
        indicates a crash mid-write). This is the key safety property:
        partially-written records are silently discarded.

        Returns:
            List of valid LogRecords in LSN order.
        """
        records: List[LogRecord] = []

        if not os.path.exists(self.wal_path):
            return records

        with open(self.wal_path, "rb") as f:
            data = f.read()

        offset = 0
        while offset < len(data):
            # Need at least 4 bytes for the length prefix
            if offset + 4 > len(data):
                break  # Truncated length prefix → crash mid-write

            (record_len,) = struct.unpack(">I", data[offset : offset + 4])

            # Check if the full record is available
            if offset + 4 + record_len > len(data):
                break  # Truncated record body → crash mid-write

            record_data = data[offset + 4 : offset + 4 + record_len]

            try:
                record = LogRecord.deserialize(record_data)
                records.append(record)
            except (ValueError, struct.error):
                # Corrupted record (bad CRC) → stop reading
                break

            offset += 4 + record_len

        return records

    def truncate(self) -> None:
        """
        Truncate the WAL file (discard all records).

        Called after a successful checkpoint when all dirty pages have been
        flushed to disk and a CHECKPOINT record has been written.
        """
        with self._lock:
            with open(self.wal_path, "wb"):
                pass

    # ──────────────────────────────────────────────
    # Convenience Methods (Transaction Lifecycle)
    # ──────────────────────────────────────────────

    def allocate_txn_id(self) -> int:
        """Allocate a new unique transaction ID."""
        with self._lock:
            txn_id = self._next_txn_id
            self._next_txn_id += 1
            return txn_id

    def begin_txn(self, txn_id: int) -> int:
        """Log a BEGIN record for a transaction. Returns LSN."""
        record = LogRecord(
            txn_id=txn_id,
            record_type=LogRecordType.BEGIN,
        )
        return self.append(record)

    def commit_txn(self, txn_id: int) -> int:
        """Log a COMMIT record for a transaction. Returns LSN."""
        record = LogRecord(
            txn_id=txn_id,
            record_type=LogRecordType.COMMIT,
        )
        return self.append(record)

    def abort_txn(self, txn_id: int) -> int:
        """Log an ABORT record for a transaction. Returns LSN."""
        record = LogRecord(
            txn_id=txn_id,
            record_type=LogRecordType.ABORT,
        )
        return self.append(record)

    def log_update(
        self, txn_id: int, page_id: int, after_image: bytes
    ) -> int:
        """
        Log an UPDATE record with the page's after-image.

        This MUST be called BEFORE modifying the buffer pool page
        (write-ahead protocol).

        Args:
            txn_id: Transaction performing the update.
            page_id: Page being modified.
            after_image: The page data AFTER the mutation.

        Returns:
            The assigned LSN.
        """
        record = LogRecord(
            txn_id=txn_id,
            record_type=LogRecordType.UPDATE,
            page_id=page_id,
            after_image=bytes(after_image),
        )
        return self.append(record)

    def log_checkpoint(self) -> int:
        """
        Log a CHECKPOINT record.

        The caller is responsible for flushing all dirty pages to disk
        BEFORE calling this method.

        Returns:
            The assigned LSN.
        """
        record = LogRecord(
            txn_id=0,
            record_type=LogRecordType.CHECKPOINT,
        )
        return self.append(record)

    # ──────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────

    def get_next_lsn(self) -> int:
        """Return the next LSN that will be assigned."""
        return self._next_lsn

    def get_wal_size_bytes(self) -> int:
        """Return the current WAL file size in bytes."""
        if os.path.exists(self.wal_path):
            return os.path.getsize(self.wal_path)
        return 0

    def __repr__(self) -> str:
        return (
            f"WALManager(path='{self.wal_path}', "
            f"next_lsn={self._next_lsn}, "
            f"size={self.get_wal_size_bytes()}B)"
        )
