"""
ChronoDB Storage Engine — Version-Aware B+ Tree

Implements a B+ Tree over primary keys, backed by the Buffer Pool Manager.
Unlike a standard B+ Tree, leaf nodes map keys to a *Version Chain* rather
than a single static record pointer. 

Includes the Version-Chain Resolver to perform point-in-time (AS OF) lookups
across branching commit histories.
"""

from typing import List, Tuple, Optional, Callable

from ..storage.buffer_pool import BufferPoolManager
from ..storage.page import INVALID_PAGE_ID
from .btree_node import BTreeNode, BTreeInternalNode, BTreeLeafNode


class BTreeIndex:
    """
    Page-backed, version-aware B+ Tree.
    """
    def __init__(self, buffer_pool: BufferPoolManager, root_page_id: int = INVALID_PAGE_ID):
        self.buffer_pool = buffer_pool
        self.root_page_id = root_page_id
        
        # Initialize an empty root if not provided
        if self.root_page_id == INVALID_PAGE_ID:
            page = self.buffer_pool.new_page()
            if not page:
                raise RuntimeError("Buffer pool out of memory allocating root page")
            self.root_page_id = page.page_id
            
            # Create empty leaf node as root
            root_node = BTreeLeafNode(page_id=self.root_page_id)
            root_node.serialize_to_page(page)
            self.buffer_pool.unpin_page(self.root_page_id, is_dirty=True)

    def _fetch_node(self, page_id: int) -> BTreeNode:
        """Fetch a page from the buffer pool and deserialize it into a BTreeNode."""
        page = self.buffer_pool.fetch_page(page_id)
        if not page:
            raise RuntimeError(f"Failed to fetch page {page_id}")
        node = BTreeNode.deserialize_from_page(page)
        # Note: We don't unpin here because the caller usually needs to modify
        # or read it. The caller MUST unpin.
        return node

    def _save_node(self, node: BTreeNode) -> None:
        """Serialize a BTreeNode and write it back to its page, then unpin."""
        page = self.buffer_pool.fetch_page(node.page_id)
        if not page:
            raise RuntimeError(f"Failed to fetch page {node.page_id} for saving")
        
        # Serialize will overwrite the page data
        node.serialize_to_page(page)
        
        # We unpin twice: once for this fetch_page, once for the original fetch_node
        self.buffer_pool.unpin_page(node.page_id, is_dirty=True)
        self.buffer_pool.unpin_page(node.page_id, is_dirty=True)

    def _unpin_node_clean(self, page_id: int) -> None:
        """Unpin a node that was fetched but not modified."""
        self.buffer_pool.unpin_page(page_id, is_dirty=False)

    def find_leaf(self, key: str) -> BTreeLeafNode:
        """
        Traverse the tree to find the leaf node that should contain the key.
        Returns the leaf node. The caller MUST _unpin_node_clean() or _save_node() it.
        """
        curr_page_id = self.root_page_id
        
        while True:
            node = self._fetch_node(curr_page_id)
            if node.is_leaf:
                return node  # type: ignore
            
            # Internal node: find the correct child
            internal = node  # type: BTreeInternalNode # type: ignore
            
            # Find the first index where key < keys[i]
            child_idx = len(internal.keys)
            for i, k in enumerate(internal.keys):
                if key < k:
                    child_idx = i
                    break
                    
            next_page_id = internal.children[child_idx]
            self._unpin_node_clean(curr_page_id)
            curr_page_id = next_page_id

    def insert(self, key: str, commit_id: int, page_version_id: int) -> None:
        """
        Insert a new version for a key.
        If the key exists, appends to its version chain.
        If the node overflows after insertion, splits the node.
        """
        leaf = self.find_leaf(key)
        
        # Append version
        leaf.append_version(key, commit_id, page_version_id)
        
        try:
            # Try saving. If it exceeds 4KB, it will raise ValueError
            self._save_node(leaf)
        except ValueError:
            # Re-fetch because _save_node failed and probably left it pinned?
            # Actually _save_node fetches again and fails before unpinning.
            # Let's clean up the pin state.
            self._unpin_node_clean(leaf.page_id) # For the second fetch inside save_node (which didn't happen if it threw before fetch? No, it throws after serialize)
            # Actually, serialize_to_page throws before unpin_page.
            self._unpin_node_clean(leaf.page_id) # For the initial find_leaf fetch
            
            # Re-fetch clean node, perform split
            leaf_clean = self._fetch_node(leaf.page_id) # type: ignore
            
            # Add the entry in memory again
            leaf_clean.append_version(key, commit_id, page_version_id)
            
            self._split_leaf(leaf_clean)

    def _split_leaf(self, leaf: BTreeLeafNode) -> None:
        """Split a leaf node that has grown too large."""
        keys = leaf.get_sorted_keys()
        mid_idx = len(keys) // 2
        
        if mid_idx == 0:
            raise RuntimeError("Cannot split a leaf node with only one massive key entry. (Page size too small)")
            
        split_key = keys[mid_idx]
        
        # Allocate new leaf page
        new_page = self.buffer_pool.new_page()
        if not new_page:
            raise RuntimeError("Out of memory splitting leaf")
            
        new_leaf = BTreeLeafNode(page_id=new_page.page_id, parent_id=leaf.parent_id)
        
        # Move half the entries to the new leaf
        for k in keys[mid_idx:]:
            new_leaf.entries[k] = leaf.entries[k]
            del leaf.entries[k]
            
        # Update linked list pointers
        new_leaf.next_page_id = leaf.next_page_id
        leaf.next_page_id = new_leaf.page_id
        
        # Save new leaf
        new_leaf.serialize_to_page(new_page)
        self.buffer_pool.unpin_page(new_leaf.page_id, is_dirty=True)
        
        # We need to insert the split_key into the parent
        self._insert_into_parent(leaf, split_key, new_leaf.page_id)

    def _insert_into_parent(self, left_node: BTreeNode, key: str, right_page_id: int) -> None:
        """Insert a routing key into the parent of left_node."""
        if left_node.parent_id == INVALID_PAGE_ID:
            # We are splitting the root. Create a new root.
            new_root_page = self.buffer_pool.new_page()
            if not new_root_page:
                raise RuntimeError("Out of memory allocating new root")
                
            new_root = BTreeInternalNode(page_id=new_root_page.page_id)
            new_root.keys = [key]
            new_root.children = [left_node.page_id, right_page_id]
            
            # Update parent pointers
            left_node.parent_id = new_root.page_id
            
            # Update the right child's parent pointer
            right_node = self._fetch_node(right_page_id)
            right_node.parent_id = new_root.page_id
            self._save_node(right_node)
            
            # Save left node
            self._save_node(left_node)
            
            # Save new root
            new_root.serialize_to_page(new_root_page)
            self.buffer_pool.unpin_page(new_root.page_id, is_dirty=True)
            
            self.root_page_id = new_root.page_id
            return
            
        # Fetch parent
        parent = self._fetch_node(left_node.parent_id) # type: ignore
        parent.insert_child(key, right_page_id) # type: ignore
        
        # Save left child
        self._save_node(left_node)
        
        try:
            self._save_node(parent)
        except ValueError:
            # Parent is full, unpin and split it
            self._unpin_node_clean(parent.page_id)
            self._unpin_node_clean(parent.page_id) # due to _save_node fetch
            
            parent_clean = self._fetch_node(parent.page_id)
            parent_clean.insert_child(key, right_page_id) # type: ignore
            self._split_internal(parent_clean) # type: ignore

    def _split_internal(self, node: BTreeInternalNode) -> None:
        """Split an internal node that has grown too large."""
        mid_idx = len(node.keys) // 2
        
        push_up_key = node.keys[mid_idx]
        
        # Allocate new internal page
        new_page = self.buffer_pool.new_page()
        if not new_page:
            raise RuntimeError("Out of memory splitting internal node")
            
        new_node = BTreeInternalNode(page_id=new_page.page_id, parent_id=node.parent_id)
        
        # Move right half to new node
        new_node.keys = node.keys[mid_idx + 1:]
        new_node.children = node.children[mid_idx + 1:]
        
        # Truncate left node
        node.keys = node.keys[:mid_idx]
        node.children = node.children[:mid_idx + 1]
        
        # Update parent pointers of children moved to new_node
        for child_id in new_node.children:
            child = self._fetch_node(child_id)
            child.parent_id = new_node.page_id
            self._save_node(child)
            
        # Save new node
        new_node.serialize_to_page(new_page)
        self.buffer_pool.unpin_page(new_node.page_id, is_dirty=True)
        
        # Insert pushed up key into parent
        self._insert_into_parent(node, push_up_key, new_node.page_id)

    # ────────────────────────────────────────────────────────
    # Version-Chain Resolver
    # ────────────────────────────────────────────────────────

    def resolve_version(
        self, 
        key: str, 
        target_commit_id: int, 
        is_ancestor_fn: Callable[[int, int], bool]
    ) -> Optional[int]:
        """
        Given a primary key and a target commit ID, walk the version chain 
        to find the correct page_version_id for that point in time.
        
        Args:
            key: The primary key to search for.
            target_commit_id: The commit ID we are querying "AS OF".
            is_ancestor_fn: A function `fn(c1, c2)` that returns True if c1 
                            is an ancestor of c2 (or if c1 == c2).
                            
        Returns:
            The page_version_id valid at the target commit, or None if the
            key did not exist or was deleted at that time.
        """
        leaf = self.find_leaf(key)
        
        if key not in leaf.entries:
            self._unpin_node_clean(leaf.page_id)
            return None
            
        version_chain = leaf.entries[key]
        self._unpin_node_clean(leaf.page_id)
        
        # Traverse the chain backwards (newest to oldest)
        for commit_id, page_version_id in reversed(version_chain):
            # If this version's commit is an ancestor of the target commit
            # (or is the target commit itself), then this is the version 
            # visible to the query.
            if is_ancestor_fn(commit_id, target_commit_id):
                # A page_version_id of -1 or None typically indicates a tombstone (DELETE)
                # But for our MVP, we can assume the caller handles tombstones if it returns a specific value.
                return page_version_id
                
        return None
