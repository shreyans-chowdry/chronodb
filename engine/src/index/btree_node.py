"""
ChronoDB Storage Engine — B+ Tree Nodes

Defines the structure of B+ Tree nodes (Internal and Leaf).
Nodes are designed to be serialized into 4KB pages and managed by the Buffer Pool.

For this MVP, we use JSON serialization into the 4KB page buffer rather than
strict binary struct packing, as it drastically simplifies development while
still strictly adhering to the 4KB page boundary constraints.
"""

import json
from typing import List, Dict, Tuple, Optional, Any

from ..storage.page import Page, PAGE_SIZE, INVALID_PAGE_ID


class BTreeNode:
    """Base class for B+ Tree nodes."""
    def __init__(self, page_id: int, is_leaf: bool, parent_id: int = INVALID_PAGE_ID):
        self.page_id = page_id
        self.is_leaf = is_leaf
        self.parent_id = parent_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert node state to dictionary for JSON serialization."""
        return {
            "is_leaf": self.is_leaf,
            "parent_id": self.parent_id
        }

    def serialize_to_page(self, page: Page) -> None:
        """Serialize this node into a 4KB Buffer Pool page."""
        data_dict = self.to_dict()
        json_bytes = json.dumps(data_dict).encode("utf-8")
        
        if len(json_bytes) > PAGE_SIZE:
            raise ValueError(f"Node size {len(json_bytes)} exceeds PAGE_SIZE {PAGE_SIZE}")
        
        # Zero out page data and copy JSON bytes
        page.data[:] = b'\x00' * PAGE_SIZE
        page.data[:len(json_bytes)] = json_bytes

    @classmethod
    def deserialize_from_page(cls, page: Page) -> "BTreeNode":
        """Deserialize a BTreeNode from a 4KB Buffer Pool page."""
        # Find the end of the JSON string (first null byte)
        null_idx = page.data.find(b'\x00')
        if null_idx == -1:
            null_idx = PAGE_SIZE
        elif null_idx == 0:
            raise ValueError("Cannot deserialize empty page")
            
        json_str = page.data[:null_idx].decode("utf-8")
        data_dict = json.loads(json_str)
        
        if data_dict["is_leaf"]:
            return BTreeLeafNode.from_dict(page.page_id, data_dict)
        else:
            return BTreeInternalNode.from_dict(page.page_id, data_dict)


class BTreeInternalNode(BTreeNode):
    """
    Internal node of the B+ Tree.
    Contains routing keys and pointers (page_ids) to child nodes.
    
    If there are N keys, there are N+1 child pointers.
    """
    def __init__(self, page_id: int, parent_id: int = INVALID_PAGE_ID):
        super().__init__(page_id, is_leaf=False, parent_id=parent_id)
        self.keys: List[str] = []
        self.children: List[int] = []  # List of page_ids

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["keys"] = self.keys
        d["children"] = self.children
        return d

    @classmethod
    def from_dict(cls, page_id: int, data: Dict[str, Any]) -> "BTreeInternalNode":
        node = cls(page_id, data.get("parent_id", INVALID_PAGE_ID))
        node.keys = data.get("keys", [])
        node.children = data.get("children", [])
        return node

    def insert_child(self, key: str, right_child_id: int) -> None:
        """Insert a new routing key and right child pointer."""
        # Find the correct position for the key
        idx = 0
        while idx < len(self.keys) and self.keys[idx] < key:
            idx += 1
            
        self.keys.insert(idx, key)
        # The right child is inserted after the key
        self.children.insert(idx + 1, right_child_id)


class BTreeLeafNode(BTreeNode):
    """
    Version-aware leaf node of the B+ Tree.
    
    Maps a primary key to a Version Chain.
    A Version Chain is a list of [commit_id, page_version_id] tuples.
    Newer versions are appended to the end of the list.
    """
    def __init__(self, page_id: int, parent_id: int = INVALID_PAGE_ID):
        super().__init__(page_id, is_leaf=True, parent_id=parent_id)
        # Dictionary mapping key to a list of [commit_id, page_version_id]
        self.entries: Dict[str, List[Tuple[int, int]]] = {}
        self.next_page_id: int = INVALID_PAGE_ID

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["entries"] = self.entries
        d["next_page_id"] = self.next_page_id
        return d

    @classmethod
    def from_dict(cls, page_id: int, data: Dict[str, Any]) -> "BTreeLeafNode":
        node = cls(page_id, data.get("parent_id", INVALID_PAGE_ID))
        # JSON keys are always strings, but tuple lists come back as lists of lists
        # We need to convert [commit_id, page_version_id] lists back to tuples if needed,
        # but for JSON serializability it's fine to keep them as lists, or explicitly cast.
        node.entries = {
            k: [tuple(ver) for ver in v] for k, v in data.get("entries", {}).items()
        }
        node.next_page_id = data.get("next_page_id", INVALID_PAGE_ID)
        return node

    def get_sorted_keys(self) -> List[str]:
        """Return keys in sorted order."""
        return sorted(self.entries.keys())

    def append_version(self, key: str, commit_id: int, page_version_id: int) -> None:
        """Append a new version to the key's version chain."""
        if key not in self.entries:
            self.entries[key] = []
        self.entries[key].append((commit_id, page_version_id))
