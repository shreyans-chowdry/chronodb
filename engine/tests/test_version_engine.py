"""
Unit tests for ChronoDB MVP Version Engine.

Tests cover the core invariants specified in the MVP prompt (agent.pdf [A]):
  1. commit() creates a new row_versions entry (not an overwrite)
  2. branch() is O(1) and copies no data
  3. rollback() preserves the rolled-back state in history
  4. checkout() switches to correct branch data
  5. Multiple branches see independent data states
  6. Commit history chain is correct (parent pointers)
"""

import sys
import os
import json
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
    db_path = str(tmp_path / "test_chronodb.dat")
    e = VersionEngine(db_path)
    yield e
    e.close()


class TestSchemaInitialization:
    """Verify the database is correctly initialized."""

    def test_main_branch_exists(self, engine):
        """The 'main' branch should exist after initialization."""
        branches = engine.list_branches()
        names = [b["name"] for b in branches]
        assert "main" in names

    def test_initial_commit_exists(self, engine):
        """There should be one initial commit on 'main'."""
        history = engine.get_commit_history("main")
        assert len(history) == 1
        assert history[0]["message"] == "Initial commit"

    def test_default_branch_is_main(self, engine):
        """The default checked-out branch should be 'main'."""
        assert engine.get_current_branch() == "main"


class TestCommit:
    """Test commit operations — copy-on-write semantics."""

    def test_commit_creates_new_row_version_not_overwrite(self, engine):
        """
        Each commit with changes should create NEW row_versions entries,
        never modifying existing ones. This is the copy-on-write invariant.
        """
        # First commit: insert a row
        engine.commit("main", "Add Alice", "test-author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        # Instead of SQLite row_versions, check the version chain length in the B+ Tree
        leaf = engine.btree.find_leaf("accounts:acc-1")
        count_before = len(leaf.entries["accounts:acc-1"])
        engine.btree._unpin_node_clean(leaf.page_id)

        # Second commit: update the same row
        engine.commit("main", "Update Alice balance", "test-author", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 200}},
        ])

        leaf = engine.btree.find_leaf("accounts:acc-1")
        versions = leaf.entries["accounts:acc-1"]
        engine.btree._unpin_node_clean(leaf.page_id)
        
        count_after = len(versions)

        # The update should have ADDED a new row_version, not replaced the old one
        assert count_after == count_before + 1

        # Both versions should exist in the database
        assert len(versions) == 2
        
        # Read the page data from buffer pool
        def get_data(page_version_id):
            page = engine.pool.fetch_page(page_version_id)
            null_idx = page.data.find(b'\x00')
            if null_idx == -1:
                null_idx = 4096
            data = json.loads(page.data[:null_idx].decode('utf-8'))
            engine.pool.unpin_page(page_version_id, is_dirty=False)
            return data
            
        assert get_data(versions[0][1])["balance"] == 100  # original
        assert get_data(versions[1][1])["balance"] == 200  # updated

    def test_commit_returns_correct_metadata(self, engine):
        """Commit should return a dict with id, hash, message, author."""
        result = engine.commit("main", "Test commit", "alice")
        assert "id" in result
        assert "hash" in result
        assert result["message"] == "Test commit"
        assert result["author"] == "alice"

    def test_commit_advances_branch_head(self, engine):
        """After a commit, the branch HEAD should point to the new commit."""
        commit1 = engine.commit("main", "Commit 1", "author")
        branch = engine.catalog.get_branch("main")
        assert branch["head_commit_id"] == commit1["id"]

    def test_commit_on_nonexistent_branch_raises(self, engine):
        """Committing to a branch that doesn't exist should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.commit("nonexistent", "msg", "author")


class TestBranch:
    """Test branching — must be O(1) with no data copy."""

    def test_branch_is_o1_no_data_copy(self, engine):
        """
        Creating a branch should NOT copy any row_versions data.
        It should only create a new branch pointer.
        """
        # Add data on main
        engine.commit("main", "Add data", "author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
            {"action": "insert", "table_name": "accounts", "row_id": "acc-2",
             "data": {"name": "Bob", "balance": 200}},
        ])

        num_pages_before = engine.disk.get_num_pages()

        # Create a branch
        engine.branch("feature-x", source_branch="main")

        num_pages_after = engine.disk.get_num_pages()

        # No new row_versions should have been created
        assert num_pages_after == num_pages_before

    def test_branch_points_to_source_head(self, engine):
        """New branch should point to the same HEAD commit as the source."""
        commit = engine.commit("main", "Commit on main", "author")
        new_branch = engine.branch("feature-x", source_branch="main")
        assert new_branch["head_commit_id"] == commit["id"]

    def test_branch_duplicate_name_raises(self, engine):
        """Creating a branch with an existing name should raise ValueError."""
        engine.branch("feature-x")
        with pytest.raises(ValueError, match="already exists"):
            engine.branch("feature-x")

    def test_branch_from_nonexistent_source_raises(self, engine):
        """Branching from a nonexistent source should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.branch("feature-x", source_branch="nonexistent")


class TestCheckout:
    """Test checkout — switching the active branch."""

    def test_checkout_switches_branch(self, engine):
        """Checkout should change the current branch."""
        engine.branch("feature-x")
        engine.checkout("feature-x")
        assert engine.get_current_branch() == "feature-x"

    def test_checkout_nonexistent_raises(self, engine):
        """Checking out a nonexistent branch should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.checkout("nonexistent")

    def test_checkout_returns_branch_name(self, engine):
        """Checkout should return the branch name."""
        engine.branch("dev")
        result = engine.checkout("dev")
        assert result == "dev"


class TestRollback:
    """Test rollback — must create a new commit, never rewrite history."""

    def test_rollback_preserves_history(self, engine):
        """
        Rollback must NOT delete any commits. It must add a NEW commit
        that reproduces the target state (Git revert semantics).
        """
        # Create a chain: initial → add Alice → update Alice
        c1 = engine.commit("main", "Add Alice", "author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])
        c2 = engine.commit("main", "Update Alice", "author", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 999}},
        ])

        commits_before = len(engine.get_commit_history("main"))

        # Rollback to c1
        rollback_commit = engine.rollback("main", c1["hash"], "author")

        commits_after = len(engine.get_commit_history("main"))

        # Should have ONE more commit (the rollback commit), not fewer
        assert commits_after == commits_before + 1
        assert "Rollback" in rollback_commit["message"]

    def test_rollback_restores_correct_data(self, engine):
        """After rollback, data should match the target commit's state."""
        c1 = engine.commit("main", "Add Alice 100", "author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])
        engine.commit("main", "Update Alice 999", "author", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 999}},
        ])

        # Data should show 999 before rollback
        data_before = engine.get_data("main", "accounts")
        assert data_before[0]["balance"] == 999

        # Rollback to c1
        engine.rollback("main", c1["hash"], "author")

        # Data should now show 100 (the state at c1)
        data_after = engine.get_data("main", "accounts")
        assert data_after[0]["balance"] == 100

    def test_rollback_to_nonexistent_commit_raises(self, engine):
        """Rollback to a commit hash that doesn't exist should raise."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.rollback("main", "deadbeef12345678", "author")

    def test_rollback_to_unreachable_commit_raises(self, engine):
        """Rollback to a commit not in the branch's history should raise."""
        # Create commit on a separate branch
        engine.branch("other")
        other_commit = engine.commit("other", "Other commit", "author", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r1",
             "data": {"x": 1}},
        ])

        # Add a commit on main so the histories diverge
        engine.commit("main", "Main commit", "author", changes=[
            {"action": "insert", "table_name": "t", "row_id": "r2",
             "data": {"x": 2}},
        ])

        with pytest.raises(ValueError, match="not in branch"):
            engine.rollback("main", other_commit["hash"], "author")


class TestBranchIsolation:
    """Test that branches maintain independent data states."""

    def test_branches_see_independent_data(self, engine):
        """Changes on one branch should not be visible on another."""
        # Add data on main
        engine.commit("main", "Add Alice on main", "author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 100}},
        ])

        # Branch off
        engine.branch("experiment")

        # Mutate on the experiment branch
        engine.commit("experiment", "Update Alice on experiment", "author", changes=[
            {"action": "update", "table_name": "accounts", "row_id": "acc-1",
             "data": {"name": "Alice", "balance": 9999}},
        ])

        # Main should still show 100
        main_data = engine.get_data("main", "accounts")
        assert main_data[0]["balance"] == 100

        # Experiment should show 9999
        exp_data = engine.get_data("experiment", "accounts")
        assert exp_data[0]["balance"] == 9999

    def test_delete_on_branch_not_visible_on_other(self, engine):
        """Deleting a row on one branch shouldn't affect the other."""
        engine.commit("main", "Add row", "author", changes=[
            {"action": "insert", "table_name": "items", "row_id": "item-1",
             "data": {"name": "Widget"}},
        ])
        engine.branch("cleanup")
        engine.commit("cleanup", "Delete row", "author", changes=[
            {"action": "delete", "table_name": "items", "row_id": "item-1",
             "data": None},
        ])

        # Main still has the item
        assert len(engine.get_data("main", "items")) == 1
        # Cleanup branch doesn't
        assert len(engine.get_data("cleanup", "items")) == 0


class TestCommitHistory:
    """Test commit history chain correctness."""

    def test_commit_chain_has_correct_parent_pointers(self, engine):
        """Each commit's parent_id should point to the previous commit."""
        c1 = engine.commit("main", "Commit 1", "author")
        c2 = engine.commit("main", "Commit 2", "author")
        c3 = engine.commit("main", "Commit 3", "author")

        history = engine.get_commit_history("main")
        # History is newest-first: c3, c2, c1, initial
        assert history[0]["id"] == c3["id"]
        assert history[0]["parent_id"] == c2["id"]
        assert history[1]["id"] == c2["id"]
        assert history[1]["parent_id"] == c1["id"]
        assert history[2]["id"] == c1["id"]

    def test_history_on_new_branch_includes_source_history(self, engine):
        """A new branch's history should include the source branch's commits."""
        c1 = engine.commit("main", "Main commit", "author")
        engine.branch("feature")
        c2 = engine.commit("feature", "Feature commit", "author")

        feature_history = engine.get_commit_history("feature")
        messages = [c["message"] for c in feature_history]

        assert "Feature commit" in messages
        assert "Main commit" in messages
        assert "Initial commit" in messages

    def test_history_limit(self, engine):
        """History should respect the limit parameter."""
        for i in range(10):
            engine.commit("main", f"Commit {i}", "author")

        history = engine.get_commit_history("main", limit=3)
        assert len(history) == 3


class TestDataOperations:
    """Test CRUD operations through the version engine."""

    def test_insert_and_read(self, engine):
        """Insert a row and read it back."""
        engine.commit("main", "Insert row", "author", changes=[
            {"action": "insert", "table_name": "products", "row_id": "p-1",
             "data": {"name": "Widget", "price": 9.99}},
        ])
        data = engine.get_data("main", "products")
        assert len(data) == 1
        assert data[0]["name"] == "Widget"
        assert data[0]["price"] == 9.99

    def test_update_shows_latest_value(self, engine):
        """After updating, get_data should return the updated value."""
        engine.commit("main", "Insert", "author", changes=[
            {"action": "insert", "table_name": "products", "row_id": "p-1",
             "data": {"name": "Widget", "price": 9.99}},
        ])
        engine.commit("main", "Update price", "author", changes=[
            {"action": "update", "table_name": "products", "row_id": "p-1",
             "data": {"name": "Widget", "price": 19.99}},
        ])
        data = engine.get_data("main", "products")
        assert data[0]["price"] == 19.99

    def test_delete_removes_from_view(self, engine):
        """Deleted rows should not appear in get_data results."""
        engine.commit("main", "Insert", "author", changes=[
            {"action": "insert", "table_name": "products", "row_id": "p-1",
             "data": {"name": "Widget"}},
        ])
        engine.commit("main", "Delete", "author", changes=[
            {"action": "delete", "table_name": "products", "row_id": "p-1",
             "data": None},
        ])
        data = engine.get_data("main", "products")
        assert len(data) == 0

    def test_get_tables(self, engine):
        """get_tables should list all tables with active data."""
        engine.commit("main", "Insert data", "author", changes=[
            {"action": "insert", "table_name": "accounts", "row_id": "a-1",
             "data": {"name": "Alice"}},
            {"action": "insert", "table_name": "products", "row_id": "p-1",
             "data": {"name": "Widget"}},
        ])
        tables = engine.get_tables("main")
        assert "accounts" in tables
        assert "products" in tables

    def test_empty_table_not_listed(self, engine):
        """A table with all rows deleted should not appear in get_tables."""
        engine.commit("main", "Insert", "author", changes=[
            {"action": "insert", "table_name": "temp", "row_id": "t-1",
             "data": {"x": 1}},
        ])
        engine.commit("main", "Delete all", "author", changes=[
            {"action": "delete", "table_name": "temp", "row_id": "t-1",
             "data": None},
        ])
        tables = engine.get_tables("main")
        assert "temp" not in tables


class TestTimeTravelQueries:
    """Test time-travel query functions: query_as_of_commit and query_as_of_timestamp."""

    def test_query_as_of_commit(self, engine):
        """Querying AS OF COMMIT <hash> should return the exact state at that commit."""
        c1 = engine.commit("main", "Insert v1", "author", changes=[
            {"action": "insert", "table_name": "users", "row_id": "u1", "data": {"name": "Alice", "role": "user"}},
        ])
        c2 = engine.commit("main", "Update v2", "author", changes=[
            {"action": "update", "table_name": "users", "row_id": "u1", "data": {"name": "Alice", "role": "admin"}},
        ])

        # Query AS OF c1 hash
        v1_data = engine.query_as_of_commit("users", c1["hash"])
        assert len(v1_data) == 1
        assert v1_data[0]["role"] == "user"

        # Query AS OF c2 hash
        v2_data = engine.query_as_of_commit("users", c2["hash"])
        assert len(v2_data) == 1
        assert v2_data[0]["role"] == "admin"

    def test_query_as_of_commit_nonexistent_raises(self, engine):
        """Querying AS OF a nonexistent commit hash should raise ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            engine.query_as_of_commit("users", "invalidhash123")

    def test_query_as_of_timestamp(self, engine):
        """Querying AS OF <timestamp> should resolve to the latest commit <= timestamp."""
        import time
        t0 = time.time()
        c1 = engine.commit("main", "Commit 1", "author", changes=[
            {"action": "insert", "table_name": "stock", "row_id": "s1", "data": {"qty": 10}},
        ])
        t1 = c1["timestamp"]
        time.sleep(0.01)

        c2 = engine.commit("main", "Commit 2", "author", changes=[
            {"action": "update", "table_name": "stock", "row_id": "s1", "data": {"qty": 50}},
        ])
        t2 = c2["timestamp"]

        # Query at t1 should give qty=10
        data_at_t1 = engine.query_as_of_timestamp("stock", t1)
        assert data_at_t1[0]["qty"] == 10

        # Query at t2 should give qty=50
        data_at_t2 = engine.query_as_of_timestamp("stock", t2)
        assert data_at_t2[0]["qty"] == 50

    def test_query_as_of_timestamp_before_all_commits_raises(self, engine):
        """Querying AS OF a timestamp before any commit should raise ValueError."""
        with pytest.raises(ValueError, match="No commits exist"):
            engine.query_as_of_timestamp("users", 1.0)
