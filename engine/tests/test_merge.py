"""
Unit tests for ChronoDB Three-Way Merge.

Covers 10 scenarios:
  1. Fast-forward merge
  2. Clean merge (no conflicts, different rows)
  3. Cell-level conflict detection (same row, different values)
  4. Delete vs Modify conflict
  5. Both branches add same new row with different data
  6. Non-conflicting same change (identical modification)
  7. Merge commit has two parents (second_parent_id set)
  8. LCA correctness
  9. Merge into non-existent branch raises
  10. Post-merge data visibility
"""

import sys
import os
import pytest

# Ensure parent directories are on sys.path for flexible execution contexts
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine.src.version.engine import VersionEngine


@pytest.fixture
def engine(tmp_path):
    """Create a fresh VersionEngine in a temp directory for each test."""
    db_path = str(tmp_path / "test_merge.dat")
    e = VersionEngine(db_path)
    yield e
    e.close()


class TestFastForwardMerge:
    """When target has no new commits, merge should fast-forward."""

    def test_fast_forward(self, engine):
        """Source is ahead, target has no new commits — fast-forward."""
        # Setup: create feature branch from main, add commits only on feature
        engine.branch("feature", source_branch="main")
        engine.commit("feature", "Add users table", "alice", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u1",
             "data": {"name": "Alice", "age": 30}},
        ])
        engine.commit("feature", "Add products", "alice", changes=[
            {"action": "insert", "table_name": "products", "row_id": "p1",
             "data": {"name": "Widget", "price": 9.99}},
        ])

        # main has no new commits since branch point
        result = engine.merge("feature", "main", "alice")

        assert result["merged"] is True
        assert result["strategy"] == "fast-forward"

        # After fast-forward, main should see feature's data
        users = engine.get_data("main", "users")
        assert len(users) == 1
        assert users[0]["name"] == "Alice"

        products = engine.get_data("main", "products")
        assert len(products) == 1
        assert products[0]["name"] == "Widget"


class TestCleanMerge:
    """Both branches changed different rows — should auto-merge cleanly."""

    def test_no_conflicts_different_rows(self, engine):
        """Source and target modified different rows — clean merge."""
        # Shared ancestor: insert a row
        engine.commit("main", "Add base data", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        # Branch off
        engine.branch("feature", source_branch="main")

        # Source branch: add a new row
        engine.commit("feature", "Add Bob on feature", "alice", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-2",
             "data": {"name": "Bob", "balance": 200}},
        ])

        # Target branch: modify a different row
        engine.commit("main", "Update Alice on main", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 150}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is True
        assert result["strategy"] == "three-way"

        # After merge, main should see both changes
        data = engine.get_data("main", "accounts")
        names = {row["name"]: row for row in data}

        assert names["Alice"]["balance"] == 150  # main's update preserved
        assert names["Bob"]["balance"] == 200     # feature's insert merged in


class TestCellLevelConflict:
    """Both branches modified the same row with different values."""

    def test_modify_modify_conflict(self, engine):
        """Same row changed differently on both branches — conflict."""
        engine.commit("main", "Add Alice", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100, "status": "active"}},
        ])

        engine.branch("feature", source_branch="main")

        # Source: change balance to 200
        engine.commit("feature", "Update balance on feature", "alice", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 200, "status": "active"}},
        ])

        # Target: change balance to 300
        engine.commit("main", "Update balance on main", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 300, "status": "active"}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is False
        assert len(result["conflicting_rows"]) == 1

        conflict = result["conflicting_rows"][0]
        assert conflict["table_name"] == "accounts"
        assert conflict["row_id"] == "acc-1"
        assert "balance" in conflict["conflicting_cells"]
        assert conflict["conflict_type"] == "modify_modify"
        assert conflict["source_data"]["balance"] == 200
        assert conflict["target_data"]["balance"] == 300

    def test_non_overlapping_cell_changes_auto_merge(self, engine):
        """Same row but different cells changed — should auto-merge."""
        engine.commit("main", "Add Alice", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100, "status": "active"}},
        ])

        engine.branch("feature", source_branch="main")

        # Source: change balance only
        engine.commit("feature", "Update balance", "alice", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 200, "status": "active"}},
        ])

        # Target: change status only
        engine.commit("main", "Update status", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100, "status": "premium"}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is True

        # After merge, should have both changes combined
        data = engine.get_data("main", "accounts")
        assert len(data) == 1
        assert data[0]["balance"] == 200    # from feature
        assert data[0]["status"] == "premium"  # from main


class TestDeleteModifyConflict:
    """One branch deletes a row, the other modifies it."""

    def test_delete_vs_modify(self, engine):
        """Source deletes, target modifies — should conflict."""
        engine.commit("main", "Add Alice", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        engine.branch("feature", source_branch="main")

        # Source: delete the row
        engine.commit("feature", "Delete Alice", "alice", changes=[
            {"action": "delete", "table_name": "accounts", "row_id": "acc-1",
             "data": None},
        ])

        # Target: modify the row
        engine.commit("main", "Update Alice", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 200}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is False
        assert len(result["conflicting_rows"]) == 1
        conflict = result["conflicting_rows"][0]
        assert conflict["conflict_type"] == "delete_modify"
        assert conflict["source_data"] is None  # deleted on source
        assert conflict["target_data"]["balance"] == 200


class TestAddAddConflict:
    """Both branches add the same row_id with different data."""

    def test_both_add_same_row_different_data(self, engine):
        """Both branches insert the same row_id with different data — conflict."""
        engine.branch("feature", source_branch="main")

        # Source: add a row
        engine.commit("feature", "Add user on feature", "alice", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u1",
             "data": {"name": "Alice", "role": "admin"}},
        ])

        # Target: add same row_id with different data
        engine.commit("main", "Add user on main", "bob", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u1",
             "data": {"name": "Bob", "role": "viewer"}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is False
        assert len(result["conflicting_rows"]) == 1
        conflict = result["conflicting_rows"][0]
        assert conflict["conflict_type"] == "add_add"
        assert "name" in conflict["conflicting_cells"]


class TestIdenticalChange:
    """Both branches made the exact same change — should auto-merge."""

    def test_same_change_no_conflict(self, engine):
        """Both branches make identical modification — no conflict."""
        engine.commit("main", "Add Alice", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        engine.branch("feature", source_branch="main")

        # Both branches apply the exact same update
        engine.commit("feature", "Fix typo on feature", "alice", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice Smith", "balance": 100}},
        ])

        engine.commit("main", "Fix typo on main", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice Smith", "balance": 100}},
        ])

        result = engine.merge("feature", "main", "merger")

        # Should succeed since both made identical changes
        assert result["merged"] is True


class TestMergeCommitTwoParents:
    """Verify the merge commit has second_parent_id set correctly."""

    def test_merge_commit_has_two_parents(self, engine):
        """Merge commit should reference both branch HEADs as parents."""
        engine.commit("main", "Main data", "system", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"x": 1}},
        ])

        engine.branch("feature", source_branch="main")

        feature_commit = engine.commit("feature", "Feature data", "alice", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r2",
             "data": {"y": 2}},
        ])

        engine.commit("main", "More main data", "bob", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r3",
             "data": {"z": 3}},
        ])

        result = engine.merge("feature", "main", "merger")

        assert result["merged"] is True
        assert result["strategy"] == "three-way"

        merge_commit = result["commit"]
        assert merge_commit["second_parent_id"] == feature_commit["id"]
        assert "Merge branch" in merge_commit["message"]


class TestLCACorrectness:
    """Test the Lowest Common Ancestor algorithm."""

    def test_lca_with_linear_history(self, engine):
        """LCA of branches diverging from a common commit."""
        # main: initial → c1 → c2
        c1 = engine.commit("main", "C1", "author")

        # Branch at c1
        engine.branch("feature", source_branch="main")

        c2 = engine.commit("main", "C2", "author")
        c3 = engine.commit("feature", "C3", "author")

        lca = engine.catalog.find_lca(
            engine.catalog.get_branch("main")["head_commit_id"],
            engine.catalog.get_branch("feature")["head_commit_id"],
        )

        # LCA should be c1 (where they diverged)
        assert lca == c1["id"]

    def test_lca_same_commit(self, engine):
        """LCA of the same commit with itself is itself."""
        head = engine.catalog.get_branch("main")["head_commit_id"]
        lca = engine.catalog.find_lca(head, head)
        assert lca == head

    def test_is_ancestor_with_merge_commits(self, engine):
        """is_ancestor should traverse second_parent_id."""
        engine.commit("main", "Shared data", "system", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"x": 1}},
        ])

        engine.branch("feature", source_branch="main")

        engine.commit("feature", "Feature work", "alice", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r2",
             "data": {"y": 2}},
        ])

        engine.commit("main", "Main work", "bob", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r3",
             "data": {"z": 3}},
        ])

        # Merge feature into main
        result = engine.merge("feature", "main", "merger")
        assert result["merged"] is True

        # After merge, the initial commit should be an ancestor of the merge commit
        initial_commit_id = engine.get_commit_history("main")[-1]["id"]
        merge_commit_id = result["commit"]["id"]

        assert engine.catalog.is_ancestor(initial_commit_id, merge_commit_id)


class TestMergeErrorHandling:
    """Test error cases."""

    def test_merge_nonexistent_source_raises(self, engine):
        """Merging from a nonexistent branch should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.merge("nonexistent", "main", "author")

    def test_merge_nonexistent_target_raises(self, engine):
        """Merging into a nonexistent branch should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.merge("main", "nonexistent", "author")


class TestPostMergeDataVisibility:
    """After a successful merge, target branch should see all merged data."""

    def test_all_data_visible_after_merge(self, engine):
        """After merge, target should see data from both branches."""
        # Common ancestor data
        engine.commit("main", "Base data", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        engine.branch("feature", source_branch="main")

        # Feature adds a new row
        engine.commit("feature", "Add Bob", "alice", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-2",
             "data": {"name": "Bob", "balance": 200}},
        ])

        # Main updates existing row
        engine.commit("main", "Update Alice", "bob", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 150}},
        ])

        # Merge
        result = engine.merge("feature", "main", "merger")
        assert result["merged"] is True

        # Verify all data is visible on main
        data = engine.get_data("main", "accounts")
        assert len(data) == 2

        by_name = {row["name"]: row for row in data}
        assert by_name["Alice"]["balance"] == 150  # main's update
        assert by_name["Bob"]["balance"] == 200     # feature's insert

        # Feature branch data should be unchanged
        feature_data = engine.get_data("feature", "accounts")
        feature_by_name = {row["name"]: row for row in feature_data}
        assert feature_by_name["Alice"]["balance"] == 100  # still original
        assert feature_by_name["Bob"]["balance"] == 200
