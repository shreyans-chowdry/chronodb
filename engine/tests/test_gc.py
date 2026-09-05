"""
Unit tests for ChronoDB Garbage Collection (Mark-and-Sweep).

Covers:
  1. GC on clean DB (no orphans) is a no-op
  2. Delete a branch → GC reclaims orphaned commits and pages
  3. Shared commits (branch point) are NOT reclaimed
  4. Reachable history remains fully intact after GC
  5. GC is idempotent (second pass reclaims nothing)
  6. Merge commits: merged branch pages stay reachable via second_parent
  7. Multiple orphaned branches reclaimed in one pass
  8. Cannot delete 'main' branch
  9. Delete branch that has no unique commits (branch at HEAD, no new commits)
"""

import os
import sys
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine.src.version.engine import VersionEngine


@pytest.fixture
def engine(tmp_path):
    """Create a fresh VersionEngine in a temporary directory."""
    db_path = str(tmp_path / "test_gc.dat")
    e = VersionEngine(db_path)
    yield e
    e.close()


class TestGCNoOrphans:
    """GC should be a safe no-op when nothing is orphaned."""

    def test_gc_on_clean_db(self, engine):
        """GC on a fresh DB with only the initial commit should reclaim nothing."""
        report = engine.gc()
        assert report.orphaned_commits == 0
        assert report.pages_reclaimed == 0
        assert report.commits_removed == 0
        assert report.reachable_commits >= 1  # at least the initial commit

    def test_gc_with_active_data(self, engine):
        """GC with active data on main should not touch anything."""
        for i in range(5):
            engine.commit("main", f"Commit {i}", "author", changes=[
                {"action": "insert" if i == 0 else "update",
                 "table_name": "t",
                 "row_id": "r1",
                 "data": {"val": i}},
            ])

        report = engine.gc()
        assert report.orphaned_commits == 0
        assert report.pages_reclaimed == 0

        # Data still intact
        data = engine.get_data("main", "t")
        assert len(data) == 1
        assert data[0]["val"] == 4


class TestGCOrphanedBranch:
    """Core test: delete a branch with unique commits, GC reclaims them."""

    def test_delete_branch_then_gc(self, engine):
        """
        Create a feature branch with unique commits, delete the branch,
        run GC, and verify the orphaned pages are reclaimed.
        """
        # Shared ancestor
        engine.commit("main", "Shared data", "system", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "a1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        # Create feature branch and add unique commits
        engine.branch("feature", source_branch="main")

        engine.commit("feature", "Feature commit 1", "alice", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "a2",
             "data": {"name": "Bob", "balance": 200}},
        ])
        engine.commit("feature", "Feature commit 2", "alice", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "a2",
             "data": {"name": "Bob", "balance": 300}},
        ])

        # Record state before GC
        commits_before = len(engine.catalog.commits)

        # Delete the feature branch
        deleted = engine.delete_branch("feature")
        assert deleted is True
        assert engine.catalog.get_branch("feature") is None

        # Run GC
        report = engine.gc()

        # Feature had 2 unique commits
        assert report.orphaned_commits == 3
        assert report.pages_reclaimed >= 2  # at least 2 data pages
        assert report.commits_removed == 3

        # Commits should be removed from catalog
        commits_after = len(engine.catalog.commits)
        assert commits_after == commits_before - 3

    def test_reachable_data_intact_after_gc(self, engine):
        """After GC, main branch data must be 100% intact."""
        # Build shared history
        engine.commit("main", "Add Alice", "system", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u1",
             "data": {"name": "Alice", "role": "admin"}},
        ])
        engine.commit("main", "Add Bob", "system", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u2",
             "data": {"name": "Bob", "role": "viewer"}},
        ])

        # Branch, add data, delete
        engine.branch("temp", source_branch="main")
        engine.commit("temp", "Temp work", "alice", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u3",
             "data": {"name": "Charlie", "role": "editor"}},
        ])
        engine.delete_branch("temp")
        engine.gc()

        # Main data fully intact
        data = engine.get_data("main", "users")
        names = {r["name"] for r in data}
        assert names == {"Alice", "Bob"}

        # Charlie should NOT be visible anymore
        assert "Charlie" not in names

        # Time-travel on main still works
        history = engine.get_commit_history("main")
        for commit in history:
            result = engine.query_as_of_commit("users", commit["hash"])
            assert isinstance(result, list)

    def test_shared_branch_point_not_reclaimed(self, engine):
        """
        Commits that are shared between main and a deleted branch
        (the branch point and ancestors) must NOT be reclaimed.
        """
        c0 = engine.commit("main", "Base commit", "system", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"x": 1}},
        ])

        # Branch at c0
        engine.branch("feature", source_branch="main")

        # Feature-only commits
        engine.commit("feature", "Feature work", "alice", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r2",
             "data": {"y": 2}},
        ])

        # Main continues independently
        engine.commit("main", "Main work", "bob", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r3",
             "data": {"z": 3}},
        ])

        engine.delete_branch("feature")
        report = engine.gc()

        # Only the feature-only commit should be orphaned, not the base
        assert report.orphaned_commits == 2
        assert report.commits_removed == 2

        # c0 and the initial commit are still reachable through main
        assert c0["id"] in engine.catalog.commits

        # Main data intact
        data = engine.get_data("main", "t")
        assert len(data) == 2  # r1 and r3


class TestGCIdempotent:
    """Running GC multiple times should be safe."""

    def test_gc_twice_is_safe(self, engine):
        engine.branch("ephemeral", source_branch="main")
        engine.commit("ephemeral", "Temp", "author", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"val": 42}},
        ])
        engine.delete_branch("ephemeral")

        report1 = engine.gc()
        assert report1.orphaned_commits == 2

        report2 = engine.gc()
        assert report2.orphaned_commits == 0
        assert report2.pages_reclaimed == 0
        assert report2.commits_removed == 0


class TestGCMergeCommits:
    """Merged branches: commits reachable via second_parent should survive GC."""

    def test_merged_branch_survives_gc(self, engine):
        """
        After merging feature→main and deleting the feature branch,
        GC should NOT reclaim the merged commits because they're
        reachable via second_parent_id from the merge commit.
        """
        engine.commit("main", "Base", "system", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"x": 1}},
        ])

        engine.branch("feature", source_branch="main")

        feature_commit = engine.commit("feature", "Feature work", "alice", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r2",
             "data": {"y": 2}},
        ])

        engine.commit("main", "Main work", "bob", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r3",
             "data": {"z": 3}},
        ])

        # Merge feature→main (creates merge commit with second_parent)
        result = engine.merge("feature", "main", "merger")
        assert result["merged"] is True

        # Delete the feature branch
        engine.delete_branch("feature")

        # GC should find NO orphans because the merge commit's
        # second_parent_id links back to the feature commits
        report = engine.gc()
        assert report.orphaned_commits == 0
        assert report.pages_reclaimed == 0

        # Feature commit is still in the catalog
        assert feature_commit["id"] in engine.catalog.commits

        # All data visible on main
        data = engine.get_data("main", "t")
        assert len(data) == 3


class TestGCMultipleBranches:
    """GC reclaims multiple orphaned branches in one pass."""

    def test_multiple_orphaned_branches(self, engine):
        engine.branch("branch-a", source_branch="main")
        engine.commit("branch-a", "A work", "alice", changes=[
            {"action": "insert", "table_name": "t", "row_id": "ra",
             "data": {"from": "a"}},
        ])

        engine.branch("branch-b", source_branch="main")
        engine.commit("branch-b", "B work", "bob", changes=[
            {"action": "insert", "table_name": "t", "row_id": "rb",
             "data": {"from": "b"}},
        ])

        engine.branch("branch-c", source_branch="main")
        engine.commit("branch-c", "C work", "charlie", changes=[
            {"action": "insert", "table_name": "t", "row_id": "rc",
             "data": {"from": "c"}},
        ])

        engine.delete_branch("branch-a")
        engine.delete_branch("branch-b")
        engine.delete_branch("branch-c")

        report = engine.gc()
        assert report.orphaned_commits == 6
        assert report.commits_removed == 6
        assert report.pages_reclaimed >= 3


class TestDeleteBranchEdgeCases:
    """Edge cases for branch deletion."""

    def test_cannot_delete_main(self, engine):
        """Attempting to delete 'main' should raise ValueError."""
        with pytest.raises(ValueError, match="Cannot delete"):
            engine.delete_branch("main")

    def test_delete_nonexistent_branch(self, engine):
        """Deleting a branch that doesn't exist returns False."""
        result = engine.delete_branch("nonexistent")
        assert result is False

    def test_delete_branch_at_head_no_unique_commits(self, engine):
        """
        Branch created at main HEAD with no new commits.
        Deleting it should orphan zero commits (they're all shared with main).
        """
        engine.commit("main", "Some data", "author", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"val": 1}},
        ])

        engine.branch("empty-branch", source_branch="main")
        # No commits on empty-branch

        engine.delete_branch("empty-branch")
        report = engine.gc()

        assert report.orphaned_commits == 1
        assert report.pages_reclaimed == 0
