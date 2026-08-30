"""
Unit tests for ChronoDB Adaptive Storage Optimizer & Delta Encoding.

Covers:
  1. Delta compute, apply, and binary page encode/decode roundtrips
  2. Cold version identification based on commit threshold
  3. Conversion of cold snapshots to deltas and byte savings verification
  4. Data integrity: AS OF commit queries across all historical versions before & after
  5. Idempotency: multiple optimizer passes produce consistent, safe results
  6. Integration: rollback and three-way merge across branches with delta-compressed pages
  7. HEAD version and single-version preservation as full snapshots
"""

import os
import sys
import pytest

# Ensure parent directories are on sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine.src.version.engine import VersionEngine
from engine.src.storage.delta import (
    compute_delta,
    apply_delta,
    encode_delta_page,
    decode_delta_page,
    is_delta_page,
    DELTA_MAGIC,
)
from engine.src.storage.page import PAGE_SIZE, Page
from engine.src.storage.reader import read_row_data


@pytest.fixture
def engine(tmp_path):
    """Create a fresh VersionEngine in a temporary directory."""
    db_path = str(tmp_path / "test_optimizer.dat")
    e = VersionEngine(db_path)
    yield e
    e.close()


class TestDeltaEncoding:
    """Test delta computation, reconstruction, and binary page packing."""

    def test_compute_and_apply_delta(self):
        base = {"name": "Alice", "age": 30, "city": "NYC", "active": True}
        current = {"name": "Alice", "age": 31, "city": "LA", "role": "admin"}
        # 'active' deleted, 'age' & 'city' modified, 'role' added

        delta = compute_delta(base, current)
        assert delta["set"] == {"age": 31, "city": "LA", "role": "admin"}
        assert "active" in delta["del"]

        reconstructed = apply_delta(base, delta)
        assert reconstructed == current

    def test_encode_decode_roundtrip(self):
        base = {"id": 1, "title": "Database Systems", "price": 50}
        current = {"id": 1, "title": "Database Systems 2nd Ed", "price": 75}
        base_page_id = 42

        delta_bytes = encode_delta_page(base, current, base_page_id)
        assert delta_bytes[0] == DELTA_MAGIC

        page_buffer = bytearray(PAGE_SIZE)
        page_buffer[:len(delta_bytes)] = delta_bytes

        assert is_delta_page(page_buffer) is True

        decoded_base_id, delta = decode_delta_page(page_buffer)
        assert decoded_base_id == base_page_id

        reconstructed = apply_delta(base, delta)
        assert reconstructed == current

    def test_is_delta_page_negative(self):
        # Full snapshot starts with '{' (0x7B)
        json_page = bytearray(b'{"name": "Alice"}' + b'\x00' * (PAGE_SIZE - 17))
        assert is_delta_page(json_page) is False

        empty_page = bytearray(PAGE_SIZE)
        assert is_delta_page(empty_page) is False


class TestAdaptiveStorageOptimizer:
    """Test the storage optimizer on version chains."""

    def test_cold_versions_compressed_into_deltas(self, engine):
        """
        Create 10 versions of a row. With cold_threshold=3:
        Versions 0..6 should become deltas (except base V0), V7..V9 remain full snapshots.
        """
        row_id = "user-101"
        commits = []

        # Create 10 commits modifying user-101
        for i in range(10):
            c = engine.commit("main", f"Update {i}", "author", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "users",
                 "row_id": row_id,
                 "data": {
                     "name": "Alice",
                     "email": "alice@example.com",
                     "department": "Engineering",
                     "counter": i,
                     "status": "active" if i % 2 == 0 else "pending",
                 }},
            ])
            commits.append(c)

        stats_before = engine.get_storage_stats()
        assert stats_before["total_versions"] == 10
        assert stats_before["deltas"] == 0
        assert stats_before["full_snapshots"] == 10

        # Run optimizer with cold_threshold=3
        report = engine.optimize_storage(cold_threshold=3)

        assert report.pages_compressed > 0
        assert report.bytes_saved > 0
        assert report.savings_percent > 0

        stats_after = engine.get_storage_stats()
        assert stats_after["deltas"] == report.pages_compressed
        assert stats_after["total_used_bytes"] < stats_before["total_used_bytes"]

    def test_data_integrity_after_optimization(self, engine):
        """
        Verify that all time-travel queries (query_as_of_commit) and get_data()
        return exact data identical to pre-optimization.
        """
        row_id = "item-1"
        expected_data_by_commit = {}

        # 12 commits modifying different fields
        for i in range(12):
            data = {
                "name": "Widget",
                "sku": "WIDGET-001",
                "price": 10.0 + i * 2.5,
                "stock": 100 - i * 5,
                "notes": f"Revision note {i} with some descriptive metadata text",
            }
            c = engine.commit("main", f"Rev {i}", "author", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "inventory",
                 "row_id": row_id,
                 "data": data},
            ])
            expected_data_by_commit[c["hash"]] = data

        # Optimize storage
        report = engine.optimize_storage(cold_threshold=4)
        assert report.pages_compressed > 0

        # Verify active HEAD data
        current_data = engine.get_data("main", "inventory")
        assert len(current_data) == 1
        assert current_data[0]["price"] == 10.0 + 11 * 2.5
        assert current_data[0]["stock"] == 100 - 11 * 5

        # Verify time-travel queries across every historical commit
        for commit_hash, expected in expected_data_by_commit.items():
            historical_data = engine.query_as_of_commit("inventory", commit_hash)
            assert len(historical_data) == 1
            for k, v in expected.items():
                assert historical_data[0][k] == v

    def test_optimizer_idempotency(self, engine):
        """Running optimizer multiple times should be safe and idempotent."""
        for i in range(8):
            engine.commit("main", f"Commit {i}", "author", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "logs",
                 "row_id": "log-1",
                 "data": {"entry": i, "timestamp": 1000 + i}},
            ])

        report1 = engine.optimize_storage(cold_threshold=2)
        assert report1.pages_compressed > 0

        # Second pass: already-compressed pages should not be double-compressed
        report2 = engine.optimize_storage(cold_threshold=2)
        assert report2.pages_compressed == 0
        assert report2.bytes_saved == 0

        # Data remains 100% intact
        data = engine.get_data("main", "logs")
        assert data[0]["entry"] == 7

    def test_single_version_never_compressed(self, engine):
        """Rows with only 1 version must remain full snapshots."""
        engine.commit("main", "Insert single row", "author", changes=[
            {"action": "insert", "table_name": "singleton", "row_id": "s1",
             "data": {"config": "val"}},
        ])

        report = engine.optimize_storage(cold_threshold=1)
        assert report.pages_compressed == 0

        stats = engine.get_storage_stats()
        assert stats["full_snapshots"] == 1
        assert stats["deltas"] == 0

    def test_rollback_compatible_with_deltas(self, engine):
        """Rollback to a commit that is delta-compressed must succeed perfectly."""
        commits = []
        for i in range(8):
            c = engine.commit("main", f"Step {i}", "author", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "state",
                 "row_id": "s1",
                 "data": {"step": i, "state": f"status_{i}"}},
            ])
            commits.append(c)

        # Optimize storage with threshold=2 (commits 1..5 will be delta-compressed)
        engine.optimize_storage(cold_threshold=2)

        # Rollback to commit 2 (which is delta-compressed)
        target_commit = commits[2]
        engine.rollback("main", target_commit["hash"], "author")

        # Verify state after rollback matches step 2
        data = engine.get_data("main", "state")
        assert len(data) == 1
        assert data[0]["step"] == 2
        assert data[0]["state"] == "status_2"

    def test_three_way_merge_compatible_with_deltas(self, engine):
        """Three-way merge across branches with delta-compressed pages must work."""
        # Common ancestor: 6 commits to create cold versions
        for i in range(6):
            engine.commit("main", f"Base {i}", "system", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "records",
                 "row_id": "r1",
                 "data": {"name": "Record 1", "val": i, "tag": "base"}},
            ])

        # Branch off
        engine.branch("feature", source_branch="main")

        # Feature updates r1 and adds r2
        engine.commit("feature", "Feature update", "alice", changes=[
            {"action": "update", "table_name": "records", "row_id": "r1",
             "data": {"name": "Record 1", "val": 100, "tag": "base"}},
            {"action": "insert", "table_name": "records", "row_id": "r2",
             "data": {"name": "Record 2", "val": 200, "tag": "feature"}},
        ])

        # Main updates r1 non-conflicting tag
        engine.commit("main", "Main update", "bob", changes=[
            {"action": "update", "table_name": "records", "row_id": "r1",
             "data": {"name": "Record 1", "val": 5, "tag": "main-tag"}},
        ])

        # Optimize storage before merge
        engine.optimize_storage(cold_threshold=2)

        # Perform three-way merge
        result = engine.merge("feature", "main", "merger")
        assert result["merged"] is True

        data = engine.get_data("main", "records")
        by_row = {r["row_id"]: r for r in data}

        assert by_row["r1"]["val"] == 100  # from feature
        assert by_row["r1"]["tag"] == "main-tag"  # from main
        assert by_row["r2"]["val"] == 200  # new row from feature
