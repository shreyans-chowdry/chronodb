"""
Unit tests for ChronoDB Write-Ahead Log (WAL).

Tests cover the four requirements from the Phase 2 prompt:
  1. Every page mutation is appended to the WAL BEFORE the buffer pool write
  2. Redo-only crash recovery replays committed entries from the last checkpoint
  3. Partially-written (uncommitted) entries are discarded
  4. Fault-injection: simulates crash mid-write and asserts consistent recovery

Additional tests cover log record serialization, WAL append/read, and checkpoint.
"""

import sys
import os
import struct
import pytest

# Path setup for flexible execution
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from engine.src.wal.log_record import LogRecord, LogRecordType
    from engine.src.wal.wal_manager import WALManager
    from engine.src.wal.recovery import RecoveryManager
    from engine.src.storage.page import PAGE_SIZE
    from engine.src.storage.disk_manager import DiskManager
    from engine.src.storage.buffer_pool import BufferPoolManager
except ImportError:
    try:
        from src.wal.log_record import LogRecord, LogRecordType  # type: ignore # pyright: ignore
        from src.wal.wal_manager import WALManager  # type: ignore # pyright: ignore
        from src.wal.recovery import RecoveryManager  # type: ignore # pyright: ignore
        from src.storage.page import PAGE_SIZE  # type: ignore # pyright: ignore
        from src.storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from src.storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore
    except ImportError:
        from wal.log_record import LogRecord, LogRecordType  # type: ignore # pyright: ignore
        from wal.wal_manager import WALManager  # type: ignore # pyright: ignore
        from wal.recovery import RecoveryManager  # type: ignore # pyright: ignore
        from storage.page import PAGE_SIZE  # type: ignore # pyright: ignore
        from storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temp directory for WAL and DB files."""
    return tmp_path


@pytest.fixture
def wal_path(tmp_dir):
    """Path for the WAL file."""
    return str(tmp_dir / "chronodb.wal")


@pytest.fixture
def db_path(tmp_dir):
    """Path for the database file."""
    return str(tmp_dir / "chronodb.dat")


@pytest.fixture
def wal(wal_path):
    """Create a fresh WALManager."""
    return WALManager(wal_path)


@pytest.fixture
def disk(db_path):
    """Create a DiskManager."""
    dm = DiskManager(db_path)
    yield dm
    dm.close()


@pytest.fixture
def pool(disk):
    """Create a 10-frame BufferPoolManager."""
    return BufferPoolManager(pool_size=10, disk_manager=disk)


# ══════════════════════════════════════════════
# Log Record Serialization Tests
# ══════════════════════════════════════════════


class TestLogRecordSerialization:
    """Test binary serialization/deserialization of log records."""

    def test_begin_record_roundtrip(self):
        """BEGIN record should survive serialize → deserialize."""
        original = LogRecord(lsn=1, txn_id=42, record_type=LogRecordType.BEGIN)
        serialized = original.serialize()

        # Skip the 4-byte length prefix
        record_len = struct.unpack(">I", serialized[:4])[0]
        restored = LogRecord.deserialize(serialized[4 : 4 + record_len])

        assert restored.lsn == 1
        assert restored.txn_id == 42
        assert restored.record_type == LogRecordType.BEGIN
        assert restored.after_image is None

    def test_update_record_with_page_data_roundtrip(self):
        """UPDATE record with a full 4KB after-image should roundtrip exactly."""
        page_data = bytearray(PAGE_SIZE)
        page_data[:12] = b"ChronoDB_WAL"

        original = LogRecord(
            lsn=5,
            prev_lsn=3,
            txn_id=7,
            record_type=LogRecordType.UPDATE,
            page_id=42,
            after_image=bytes(page_data),
        )
        serialized = original.serialize()

        record_len = struct.unpack(">I", serialized[:4])[0]
        restored = LogRecord.deserialize(serialized[4 : 4 + record_len])

        assert restored.lsn == 5
        assert restored.txn_id == 7
        assert restored.record_type == LogRecordType.UPDATE
        assert restored.page_id == 42
        assert restored.after_image[:12] == b"ChronoDB_WAL"
        assert len(restored.after_image) == PAGE_SIZE

    def test_corrupted_record_raises_error(self):
        """A record with a bad CRC should raise ValueError."""
        record = LogRecord(lsn=1, txn_id=1, record_type=LogRecordType.COMMIT)
        serialized = record.serialize()

        # Corrupt one byte in the body
        corrupted = bytearray(serialized)
        corrupted[8] ^= 0xFF  # Flip a byte inside the body
        record_len = struct.unpack(">I", corrupted[:4])[0]

        with pytest.raises(ValueError, match="CRC mismatch"):
            LogRecord.deserialize(bytes(corrupted[4 : 4 + record_len]))

    def test_all_record_types_serialize(self):
        """Every LogRecordType should serialize without error."""
        for rt in LogRecordType:
            record = LogRecord(lsn=1, txn_id=1, record_type=rt)
            serialized = record.serialize()
            assert len(serialized) > 0


# ══════════════════════════════════════════════
# WAL Manager Tests
# ══════════════════════════════════════════════


class TestWALManager:
    """Test WAL file I/O operations."""

    def test_append_assigns_sequential_lsns(self, wal):
        """Each append should assign a monotonically increasing LSN."""
        lsn1 = wal.begin_txn(1)
        lsn2 = wal.commit_txn(1)
        lsn3 = wal.begin_txn(2)

        assert lsn1 == 1
        assert lsn2 == 2
        assert lsn3 == 3

    def test_append_and_read_roundtrip(self, wal):
        """Records written to the WAL should be readable back."""
        wal.begin_txn(1)
        wal.log_update(1, page_id=0, after_image=b"A" * PAGE_SIZE)
        wal.commit_txn(1)

        records = wal.read_all()
        assert len(records) == 3
        assert records[0].record_type == LogRecordType.BEGIN
        assert records[1].record_type == LogRecordType.UPDATE
        assert records[1].page_id == 0
        assert records[2].record_type == LogRecordType.COMMIT

    def test_wal_survives_reopen(self, wal_path):
        """Records should persist across WALManager instances (file-backed)."""
        wal1 = WALManager(wal_path)
        wal1.begin_txn(1)
        wal1.commit_txn(1)

        # Simulate process restart
        wal2 = WALManager(wal_path)
        records = wal2.read_all()
        assert len(records) == 2

        # Next LSN should continue from where wal1 left off
        lsn = wal2.begin_txn(2)
        assert lsn == 3

    def test_truncate_clears_wal(self, wal):
        """truncate() should remove all records from the WAL file."""
        wal.begin_txn(1)
        wal.commit_txn(1)
        assert len(wal.read_all()) == 2

        wal.truncate()
        assert len(wal.read_all()) == 0
        assert wal.get_wal_size_bytes() == 0

    def test_checkpoint_record(self, wal):
        """log_checkpoint() should write a CHECKPOINT record."""
        wal.log_checkpoint()
        records = wal.read_all()
        assert len(records) == 1
        assert records[0].record_type == LogRecordType.CHECKPOINT

    def test_allocate_txn_id_is_unique(self, wal):
        """Each call to allocate_txn_id() should return a unique ID."""
        ids = [wal.allocate_txn_id() for _ in range(5)]
        assert len(set(ids)) == 5
        assert ids == sorted(ids)  # monotonically increasing


# ══════════════════════════════════════════════
# Write-Ahead Protocol Tests
# ══════════════════════════════════════════════


class TestWriteAheadProtocol:
    """Test that the WAL-before-write protocol works end-to-end."""

    def test_wal_before_buffer_pool_write(self, wal, pool):
        """
        The correct sequence is:
          1. WAL append (log the after-image)
          2. Modify the buffer pool page
        This test verifies the protocol produces correct WAL + page state.
        """
        # Allocate a page in the buffer pool
        page = pool.new_page()
        page_id = page.page_id

        # Prepare the mutation
        new_data = bytearray(PAGE_SIZE)
        new_data[:5] = b"HELLO"

        # Step 1: WAL FIRST (write-ahead guarantee)
        txn_id = wal.allocate_txn_id()
        wal.begin_txn(txn_id)
        wal.log_update(txn_id, page_id, bytes(new_data))

        # Step 2: THEN modify the buffer pool page
        page.data[:] = new_data
        pool.unpin_page(page_id, is_dirty=True)

        # Step 3: Commit
        wal.commit_txn(txn_id)

        # Verify WAL has the correct records
        records = wal.read_all()
        assert len(records) == 3  # BEGIN + UPDATE + COMMIT
        assert records[1].after_image[:5] == b"HELLO"

        # Verify buffer pool page has the data
        fetched = pool.fetch_page(page_id)
        assert fetched.data[:5] == b"HELLO"
        pool.unpin_page(page_id)


# ══════════════════════════════════════════════
# Crash Recovery Tests
# ══════════════════════════════════════════════


class TestCrashRecovery:
    """Test redo-only crash recovery."""

    def test_recovery_on_clean_wal(self, wal, disk):
        """Recovery with no WAL records should report clean state."""
        recovery = RecoveryManager(wal, disk)
        result = recovery.recover()
        assert result["status"] == "clean"
        assert result["redone"] == 0

    def test_recovery_redoes_committed_transaction(self, wal_path, db_path):
        """
        Committed UPDATE records should be redone during recovery:
        their after-images should appear on disk after recovery.
        """
        # --- PHASE 1: Normal operation (simulate before crash) ---
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        # Allocate page on disk
        page_id = disk1.allocate_page()

        # Write committed transaction to WAL
        committed_data = bytearray(PAGE_SIZE)
        committed_data[:9] = b"COMMITTED"

        wal1.begin_txn(1)
        wal1.log_update(1, page_id, bytes(committed_data))
        wal1.commit_txn(1)

        # Simulate crash: page was NOT flushed to disk
        # (the page on disk still has zeros)
        disk1.close()

        # --- PHASE 2: Recovery after crash ---
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        assert result["status"] == "recovered"
        assert result["redone"] == 1
        assert result["committed_txns"] == 1

        # Verify the committed data is now on disk
        page_data = disk2.read_page(page_id)
        assert page_data[:9] == b"COMMITTED"
        disk2.close()

    def test_recovery_discards_uncommitted_transaction(self, wal_path, db_path):
        """
        Uncommitted UPDATE records (no COMMIT in WAL) must be discarded.
        Their after-images should NOT appear on disk after recovery.
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        # Allocate pages
        committed_page = disk1.allocate_page()
        uncommitted_page = disk1.allocate_page()

        # Transaction 1: committed
        committed_data = bytearray(PAGE_SIZE)
        committed_data[:4] = b"GOOD"
        wal1.begin_txn(1)
        wal1.log_update(1, committed_page, bytes(committed_data))
        wal1.commit_txn(1)

        # Transaction 2: NOT committed (simulates crash before commit)
        bad_data = bytearray(PAGE_SIZE)
        bad_data[:3] = b"BAD"
        wal1.begin_txn(2)
        wal1.log_update(2, uncommitted_page, bytes(bad_data))
        # NO commit for txn 2 → simulates crash

        disk1.close()

        # Recovery
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        assert result["redone"] == 1
        assert result["discarded"] == 1
        assert result["uncommitted_txns"] == 1

        # Committed page should have "GOOD"
        assert disk2.read_page(committed_page)[:4] == b"GOOD"

        # Uncommitted page should still be zeros (never applied)
        assert disk2.read_page(uncommitted_page)[:3] == b"\x00\x00\x00"
        disk2.close()

    def test_recovery_from_checkpoint(self, wal_path, db_path):
        """
        Recovery should start from the last CHECKPOINT, not from the
        beginning of the WAL.
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        # Pre-checkpoint transaction (already flushed to disk)
        pre_page = disk1.allocate_page()
        pre_data = bytearray(PAGE_SIZE)
        pre_data[:3] = b"OLD"
        wal1.begin_txn(1)
        wal1.log_update(1, pre_page, bytes(pre_data))
        wal1.commit_txn(1)

        # Flush to disk and checkpoint
        disk1.write_page(pre_page, pre_data)
        wal1.log_checkpoint()

        # Post-checkpoint transaction (NOT flushed — needs redo)
        post_page = disk1.allocate_page()
        post_data = bytearray(PAGE_SIZE)
        post_data[:3] = b"NEW"
        wal1.begin_txn(2)
        wal1.log_update(2, post_page, bytes(post_data))
        wal1.commit_txn(2)

        disk1.close()

        # Recovery should only redo the post-checkpoint transaction
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        assert result["redone"] == 1  # Only the post-checkpoint update
        assert result["committed_txns"] == 1  # Only txn 2 after checkpoint

        # Post-checkpoint page should have "NEW"
        assert disk2.read_page(post_page)[:3] == b"NEW"
        disk2.close()

    def test_recovery_handles_multiple_committed_txns(self, wal_path, db_path):
        """Recovery should redo ALL committed transactions."""
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        pages = [disk1.allocate_page() for _ in range(3)]

        for i, page_id in enumerate(pages):
            txn_id = i + 1
            data = bytearray(PAGE_SIZE)
            data[0] = 65 + i  # A, B, C
            wal1.begin_txn(txn_id)
            wal1.log_update(txn_id, page_id, bytes(data))
            wal1.commit_txn(txn_id)

        disk1.close()

        # Recovery
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        assert result["redone"] == 3
        assert result["committed_txns"] == 3

        assert disk2.read_page(pages[0])[0:1] == b"A"
        assert disk2.read_page(pages[1])[0:1] == b"B"
        assert disk2.read_page(pages[2])[0:1] == b"C"
        disk2.close()


# ══════════════════════════════════════════════
# Fault-Injection Tests
# ══════════════════════════════════════════════


class TestFaultInjection:
    """
    Simulate crashes mid-write and verify recovery produces consistent state.

    These tests directly manipulate the WAL file bytes to simulate what
    happens when a process is killed during a write() syscall.
    """

    def test_crash_mid_write_truncated_record(self, wal_path, db_path):
        """
        Simulate a crash that truncates the last WAL record mid-write.

        Setup:
          - Txn 1: BEGIN → UPDATE(page 0, "SAFE") → COMMIT  (complete)
          - Txn 2: BEGIN → UPDATE(page 1, "UNSAFE")          (crash before COMMIT)

        Then truncate the WAL file to cut the UPDATE record of txn 2 in half.
        Recovery should redo txn 1 and silently discard the partial txn 2 record.
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        page0 = disk1.allocate_page()
        page1 = disk1.allocate_page()

        # Txn 1: fully committed
        safe_data = bytearray(PAGE_SIZE)
        safe_data[:4] = b"SAFE"
        wal1.begin_txn(1)
        wal1.log_update(1, page0, bytes(safe_data))
        wal1.commit_txn(1)

        # Record the WAL size after txn 1 is fully committed
        wal_size_after_txn1 = wal1.get_wal_size_bytes()

        # Txn 2: write BEGIN and UPDATE but NO commit
        unsafe_data = bytearray(PAGE_SIZE)
        unsafe_data[:6] = b"UNSAFE"
        wal1.begin_txn(2)
        wal1.log_update(2, page1, bytes(unsafe_data))

        disk1.close()

        # ── FAULT INJECTION: Truncate WAL mid-record ──
        # Cut the file somewhere inside the last UPDATE record of txn 2
        full_wal_size = os.path.getsize(wal_path)
        # Truncate to partway through the last record
        crash_point = wal_size_after_txn1 + 50  # Inside txn 2's BEGIN + partial UPDATE
        with open(wal_path, "r+b") as f:
            f.truncate(crash_point)

        # ── RECOVERY ──
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        # Txn 1 should be recovered
        assert result["committed_txns"] >= 1
        assert disk2.read_page(page0)[:4] == b"SAFE"

        # Txn 2's data should NOT be on disk (truncated + uncommitted)
        assert disk2.read_page(page1)[:6] != b"UNSAFE"
        disk2.close()

    def test_crash_mid_write_corrupted_crc(self, wal_path, db_path):
        """
        Simulate a crash that corrupts the last WAL record's CRC.

        This models a partial write where the kernel wrote some bytes but
        not all before the crash. The CRC check should catch this.
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        page0 = disk1.allocate_page()

        # Txn 1: fully committed
        good_data = bytearray(PAGE_SIZE)
        good_data[:9] = b"RECOVERED"
        wal1.begin_txn(1)
        wal1.log_update(1, page0, bytes(good_data))
        wal1.commit_txn(1)

        wal_size_after_good = wal1.get_wal_size_bytes()

        # Txn 2: write a record then corrupt it
        bad_data = bytearray(PAGE_SIZE)
        bad_data[:7] = b"CORRUPT"
        wal1.begin_txn(2)
        wal1.log_update(2, page0, bytes(bad_data))

        disk1.close()

        # ── FAULT INJECTION: Corrupt the last record's CRC ──
        with open(wal_path, "r+b") as f:
            # Flip the last 4 bytes (CRC) of the file
            f.seek(-4, 2)
            crc_bytes = bytearray(f.read(4))
            crc_bytes[0] ^= 0xFF
            f.seek(-4, 2)
            f.write(crc_bytes)

        # ── RECOVERY ──
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        # Txn 1 should be recovered
        assert result["committed_txns"] >= 1
        assert disk2.read_page(page0)[:9] == b"RECOVERED"
        disk2.close()

    def test_crash_kills_process_mid_commit(self, wal_path, db_path):
        """
        Simulate a crash that happens BETWEEN the last UPDATE and the
        COMMIT record. The transaction should be treated as uncommitted.
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        page0 = disk1.allocate_page()

        # Txn 1: committed (control)
        ctrl_data = bytearray(PAGE_SIZE)
        ctrl_data[:7] = b"CONTROL"
        wal1.begin_txn(1)
        wal1.log_update(1, page0, bytes(ctrl_data))
        wal1.commit_txn(1)

        # Txn 2: BEGIN → UPDATE → [CRASH before COMMIT]
        page1 = disk1.allocate_page()
        lost_data = bytearray(PAGE_SIZE)
        lost_data[:4] = b"LOST"
        wal1.begin_txn(2)
        wal1.log_update(2, page1, bytes(lost_data))
        # Process killed here — no COMMIT record

        disk1.close()

        # ── RECOVERY ──
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        recovery = RecoveryManager(wal2, disk2)
        result = recovery.recover()

        assert result["committed_txns"] == 1  # Only txn 1
        assert result["uncommitted_txns"] == 1  # txn 2
        assert result["discarded"] == 1  # txn 2's UPDATE

        # Txn 1's data should be on disk
        assert disk2.read_page(page0)[:7] == b"CONTROL"

        # Txn 2's data should NOT be on disk
        assert disk2.read_page(page1)[:4] == b"\x00\x00\x00\x00"
        disk2.close()

    def test_empty_wal_after_crash(self, wal_path, db_path):
        """
        If the WAL file exists but is empty (crash before any writes),
        recovery should report clean state.
        """
        # Create empty WAL
        with open(wal_path, "wb"):
            pass

        disk = DiskManager(db_path)
        wal = WALManager(wal_path)
        recovery = RecoveryManager(wal, disk)
        result = recovery.recover()

        assert result["status"] == "clean"
        disk.close()

    def test_recovery_is_idempotent(self, wal_path, db_path):
        """
        Running recovery twice should produce the same result
        (idempotent redo).
        """
        disk1 = DiskManager(db_path)
        wal1 = WALManager(wal_path)

        page0 = disk1.allocate_page()
        data = bytearray(PAGE_SIZE)
        data[:10] = b"IDEMPOTENT"

        wal1.begin_txn(1)
        wal1.log_update(1, page0, bytes(data))
        wal1.commit_txn(1)
        disk1.close()

        # First recovery
        disk2 = DiskManager(db_path)
        wal2 = WALManager(wal_path)
        RecoveryManager(wal2, disk2).recover()
        assert disk2.read_page(page0)[:10] == b"IDEMPOTENT"
        disk2.close()

        # Second recovery (should produce same result)
        disk3 = DiskManager(db_path)
        wal3 = WALManager(wal_path)
        result = RecoveryManager(wal3, disk3).recover()
        assert disk3.read_page(page0)[:10] == b"IDEMPOTENT"
        assert result["redone"] == 1  # Same redo count
        disk3.close()
