"""
Unit tests for ChronoDB Version-Aware B+ Tree Index.
"""

import sys
import os
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from engine.src.storage.disk_manager import DiskManager
    from engine.src.storage.buffer_pool import BufferPoolManager
    from engine.src.index.btree import BTreeIndex
    from engine.src.index.btree_node import BTreeNode, BTreeLeafNode, BTreeInternalNode
    from engine.src.storage.page import PAGE_SIZE
except ImportError:
    try:
        from src.storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from src.storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore
        from src.index.btree import BTreeIndex  # type: ignore # pyright: ignore
        from src.index.btree_node import BTreeNode, BTreeLeafNode, BTreeInternalNode  # type: ignore # pyright: ignore
        from src.storage.page import PAGE_SIZE  # type: ignore # pyright: ignore
    except ImportError:
        from storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore
        from index.btree import BTreeIndex  # type: ignore # pyright: ignore
        from index.btree_node import BTreeNode, BTreeLeafNode, BTreeInternalNode  # type: ignore # pyright: ignore
        from storage.page import PAGE_SIZE  # type: ignore # pyright: ignore


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "btree_test.dat")


@pytest.fixture
def disk(tmp_db):
    dm = DiskManager(tmp_db)
    yield dm
    dm.close()


@pytest.fixture
def pool(disk):
    # Large enough pool to avoid thrashing during small tests
    return BufferPoolManager(pool_size=100, disk_manager=disk)


@pytest.fixture
def btree(pool):
    return BTreeIndex(buffer_pool=pool)


# ══════════════════════════════════════════════
# Node Serialization Tests
# ══════════════════════════════════════════════


class TestNodeSerialization:
    def test_leaf_node_serialization(self, pool):
        page = pool.new_page()
        leaf = BTreeLeafNode(page_id=page.page_id)
        leaf.append_version("user123", commit_id=10, page_version_id=42)
        leaf.append_version("user123", commit_id=15, page_version_id=50)
        
        leaf.serialize_to_page(page)
        
        # Deserialize
        restored = BTreeNode.deserialize_from_page(page)
        assert isinstance(restored, BTreeLeafNode)
        assert restored.is_leaf
        assert "user123" in restored.entries
        assert restored.entries["user123"] == [(10, 42), (15, 50)]
        pool.unpin_page(page.page_id, is_dirty=True)

    def test_internal_node_serialization(self, pool):
        page = pool.new_page()
        internal = BTreeInternalNode(page_id=page.page_id)
        internal.keys = ["alpha", "beta"]
        internal.children = [1, 2, 3]
        
        internal.serialize_to_page(page)
        
        restored = BTreeNode.deserialize_from_page(page)
        assert isinstance(restored, BTreeInternalNode)
        assert not restored.is_leaf
        assert restored.keys == ["alpha", "beta"]
        assert restored.children == [1, 2, 3]
        pool.unpin_page(page.page_id, is_dirty=True)

    def test_node_exceeds_page_size_raises(self, pool):
        page = pool.new_page()
        leaf = BTreeLeafNode(page_id=page.page_id)
        
        # Create a massive key that will cause the JSON to exceed 4096 bytes
        massive_key = "K" * 5000
        leaf.append_version(massive_key, 1, 1)
        
        with pytest.raises(ValueError, match="exceeds PAGE_SIZE"):
            leaf.serialize_to_page(page)
        pool.unpin_page(page.page_id, is_dirty=False)


# ══════════════════════════════════════════════
# B+ Tree Index Tests
# ══════════════════════════════════════════════


class TestBTreeOperations:
    def test_insert_and_find_leaf(self, btree):
        btree.insert("key1", commit_id=1, page_version_id=100)
        
        leaf = btree.find_leaf("key1")
        assert "key1" in leaf.entries
        assert leaf.entries["key1"] == [(1, 100)]
        btree._unpin_node_clean(leaf.page_id)

    def test_insert_appends_to_version_chain(self, btree):
        btree.insert("keyA", commit_id=1, page_version_id=10)
        btree.insert("keyA", commit_id=2, page_version_id=20)
        btree.insert("keyA", commit_id=3, page_version_id=30)
        
        leaf = btree.find_leaf("keyA")
        assert leaf.entries["keyA"] == [(1, 10), (2, 20), (3, 30)]
        btree._unpin_node_clean(leaf.page_id)

    def test_leaf_node_split(self, btree):
        # Insert enough large keys to force a leaf split.
        # JSON overhead per entry is ~50 bytes. 
        # A 100-byte key means ~150 bytes per entry.
        # 4096 / 150 = ~27 entries to fill a page.
        for i in range(40):
            key = f"key_{i:03d}_" + "X" * 100
            btree.insert(key, commit_id=1, page_version_id=i)
            
        # The root should now be an internal node
        root = btree._fetch_node(btree.root_page_id)
        assert not root.is_leaf
        assert len(root.keys) > 0  # Should have been split
        assert len(root.children) == len(root.keys) + 1
        btree._unpin_node_clean(root.page_id)
        
        # Verify all keys are still retrievable
        for i in range(40):
            key = f"key_{i:03d}_" + "X" * 100
            leaf = btree.find_leaf(key)
            assert key in leaf.entries
            assert leaf.entries[key] == [(1, i)]
            btree._unpin_node_clean(leaf.page_id)

    def test_internal_node_split(self, btree):
        # To split an internal node, we need many leaf splits.
        # We can achieve this by inserting hundreds of large keys.
        for i in range(250):
            key = f"key_{i:03d}_" + "X" * 100
            btree.insert(key, commit_id=1, page_version_id=i)
            
        root = btree._fetch_node(btree.root_page_id)
        assert not root.is_leaf
        btree._unpin_node_clean(root.page_id)
        
        # Verify random keys
        for i in [0, 50, 100, 150, 200, 249]:
            key = f"key_{i:03d}_" + "X" * 100
            leaf = btree.find_leaf(key)
            assert key in leaf.entries
            assert leaf.entries[key] == [(1, i)]
            btree._unpin_node_clean(leaf.page_id)


# ══════════════════════════════════════════════
# Version-Chain Resolver Tests
# ══════════════════════════════════════════════


class TestVersionChainResolver:
    def test_resolve_latest_linear_history(self, btree):
        # Linear history: 1 -> 2 -> 3
        btree.insert("doc1", commit_id=1, page_version_id=10)
        btree.insert("doc1", commit_id=2, page_version_id=20)
        btree.insert("doc1", commit_id=3, page_version_id=30)
        
        # Simple ancestor check for linear history
        def is_ancestor_linear(c1, c2):
            return c1 <= c2
            
        assert btree.resolve_version("doc1", 3, is_ancestor_linear) == 30
        assert btree.resolve_version("doc1", 2, is_ancestor_linear) == 20
        assert btree.resolve_version("doc1", 1, is_ancestor_linear) == 10
        assert btree.resolve_version("doc1", 0, is_ancestor_linear) is None

    def test_resolve_branching_history(self, btree):
        # Simulated DAG:
        # 1 -> 2 -> 3 (main)
        #  \-> 4 -> 5 (feature)
        btree.insert("doc1", commit_id=1, page_version_id=10) # main
        btree.insert("doc1", commit_id=2, page_version_id=20) # main
        btree.insert("doc1", commit_id=4, page_version_id=40) # feature (branched from 1)
        btree.insert("doc1", commit_id=3, page_version_id=30) # main
        btree.insert("doc1", commit_id=5, page_version_id=50) # feature
        
        dag = {
            1: [],
            2: [1],
            3: [2],
            4: [1],
            5: [4]
        }
        
        def is_ancestor_dag(ancestor, target):
            if ancestor == target:
                return True
            parents = dag.get(target, [])
            for p in parents:
                if is_ancestor_dag(ancestor, p):
                    return True
            return False

        # Querying from main (commit 3)
        assert btree.resolve_version("doc1", 3, is_ancestor_dag) == 30
        
        # Querying from main before commit 3 (commit 2)
        assert btree.resolve_version("doc1", 2, is_ancestor_dag) == 20
        
        # Querying from feature branch (commit 5)
        # Should see 40 -> 50, but NOT 20 or 30
        assert btree.resolve_version("doc1", 5, is_ancestor_dag) == 50
        
        # Querying from feature branch (commit 4)
        assert btree.resolve_version("doc1", 4, is_ancestor_dag) == 40
        
        # Querying from root
        assert btree.resolve_version("doc1", 1, is_ancestor_dag) == 10
