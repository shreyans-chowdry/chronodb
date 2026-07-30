"""
ChronoDB Storage Engine — Buffer Pool Manager

Manages a fixed-size pool of in-memory page frames, implementing:
  - LRU (Least Recently Used) eviction policy
  - Dirty-page tracking with flush-on-eviction
  - Pin counting to prevent eviction of actively-used pages
  - Checkpoint: flush all dirty pages to disk

Design:
  The buffer pool sits between the upper layers (version engine, index, query
  executor) and the disk manager. Upper layers never read/write disk directly —
  they fetch pages from the buffer pool, which handles caching, eviction, and
  durability transparently.

  Frame layout:
    frames[0..pool_size-1] — each frame can hold one Page.
    page_table: maps page_id -> frame_index for O(1) lookup.
    lru_list: OrderedDict tracking access order for unpinned pages.

This is the custom storage engine — NOT the throwaway SQLite scaffold.
"""

from collections import OrderedDict
from typing import Dict, List, Optional, Set

from .page import Page, PAGE_SIZE, INVALID_PAGE_ID
from .disk_manager import DiskManager


class BufferPoolManager:
    """
    Fixed-size buffer pool with LRU eviction and dirty-page tracking.

    Args:
        pool_size: Maximum number of page frames in memory.
        disk_manager: The DiskManager to use for page I/O.

    Example:
        dm = DiskManager("chronodb.dat")
        bpm = BufferPoolManager(pool_size=64, disk_manager=dm)
        page = bpm.new_page()
        page.data[:5] = b"hello"
        bpm.unpin_page(page.page_id, is_dirty=True)
        bpm.flush_all_pages()  # checkpoint
    """

    def __init__(self, pool_size: int, disk_manager: DiskManager):
        if pool_size <= 0:
            raise ValueError("pool_size must be positive")

        self.pool_size = pool_size
        self.disk_manager = disk_manager

        # Frame storage: each slot holds a Page (or None if unused)
        self.frames: List[Page] = [Page() for _ in range(pool_size)]

        # page_id -> frame_index mapping for O(1) lookup
        self.page_table: Dict[int, int] = {}

        # Free frame list (indices of frames not holding any page)
        self.free_list: List[int] = list(range(pool_size))

        # LRU tracking: OrderedDict of page_id -> None.
        # Only UNPINNED pages appear here. Most-recently-used at the end,
        # least-recently-used at the front. Pages are added when unpinned
        # and removed when pinned or evicted.
        self._lru: OrderedDict = OrderedDict()

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def fetch_page(self, page_id: int) -> Optional[Page]:
        """
        Fetch a page from the buffer pool. If not cached, read from disk.

        The returned page has pin_count incremented by 1. The caller MUST
        call unpin_page() when done to allow future eviction.

        Args:
            page_id: The page to fetch.

        Returns:
            The Page object, or None if the page cannot be fetched (e.g.,
            the pool is full and all pages are pinned).
        """
        # Case 1: Page is already in the buffer pool
        if page_id in self.page_table:
            frame_idx = self.page_table[page_id]
            page = self.frames[frame_idx]
            page.pin_count += 1

            # Remove from LRU list (it's now pinned, not evictable)
            if page_id in self._lru:
                del self._lru[page_id]

            return page

        # Case 2: Page is not in the pool — need a free frame
        frame_idx = self._get_free_frame()
        if frame_idx is None:
            return None  # All frames are pinned, cannot evict

        # Read the page from disk into the frame
        page = self.frames[frame_idx]
        page.reset()
        page.page_id = page_id
        page.data = self.disk_manager.read_page(page_id)
        page.pin_count = 1
        page.is_dirty = False

        # Register in page table
        self.page_table[page_id] = frame_idx

        return page

    def new_page(self) -> Optional[Page]:
        """
        Allocate a new page on disk and bring it into the buffer pool.

        Returns:
            The new Page, or None if the pool is full and all pages are pinned.
        """
        # Find a free frame
        frame_idx = self._get_free_frame()
        if frame_idx is None:
            return None  # All frames pinned, cannot evict

        # Allocate a new page on disk
        page_id = self.disk_manager.allocate_page()

        # Initialize the frame
        page = self.frames[frame_idx]
        page.reset()
        page.page_id = page_id
        page.pin_count = 1
        page.is_dirty = False

        # Register in page table
        self.page_table[page_id] = frame_idx

        return page

    def unpin_page(self, page_id: int, is_dirty: bool = False) -> bool:
        """
        Unpin a page (decrement its pin count). Optionally mark as dirty.

        When pin_count reaches 0, the page becomes eligible for LRU eviction.

        Args:
            page_id: The page to unpin.
            is_dirty: If True, mark the page as dirty (needs flush before eviction).

        Returns:
            True if the page was found and unpinned, False if not in the pool.
        """
        if page_id not in self.page_table:
            return False

        frame_idx = self.page_table[page_id]
        page = self.frames[frame_idx]

        # Mark dirty if requested (dirty bit is sticky — once dirty, stays dirty
        # until flushed)
        if is_dirty:
            page.is_dirty = True

        # Decrement pin count (floor at 0)
        if page.pin_count <= 0:
            return False
        page.pin_count -= 1

        # If fully unpinned, add to LRU list (eligible for eviction)
        if page.pin_count == 0:
            self._lru[page_id] = None  # Add to end (most recently used)

        return True

    def flush_page(self, page_id: int) -> bool:
        """
        Write a page's data to disk if it is dirty. Clears the dirty flag.

        Args:
            page_id: The page to flush.

        Returns:
            True if the page was found and flushed, False if not in the pool.
        """
        if page_id not in self.page_table:
            return False

        frame_idx = self.page_table[page_id]
        page = self.frames[frame_idx]

        if page.is_dirty:
            self.disk_manager.write_page(page.page_id, page.data)
            page.is_dirty = False

        return True

    def flush_all_pages(self) -> int:
        """
        Checkpoint: flush ALL dirty pages to disk.

        Returns:
            The number of pages that were actually flushed (were dirty).
        """
        flushed_count = 0
        for frame_idx in range(self.pool_size):
            page = self.frames[frame_idx]
            if page.page_id != INVALID_PAGE_ID and page.is_dirty:
                self.disk_manager.write_page(page.page_id, page.data)
                page.is_dirty = False
                flushed_count += 1

        return flushed_count

    def delete_page(self, page_id: int) -> bool:
        """
        Delete a page from the buffer pool (and deallocate on disk).

        The page must have pin_count == 0 to be deleted.

        Args:
            page_id: The page to delete.

        Returns:
            True if deleted, False if not found or still pinned.
        """
        if page_id not in self.page_table:
            return False

        frame_idx = self.page_table[page_id]
        page = self.frames[frame_idx]

        if page.pin_count > 0:
            return False  # Cannot delete a pinned page

        # Remove from LRU
        if page_id in self._lru:
            del self._lru[page_id]

        # Flush if dirty before deleting
        if page.is_dirty:
            self.disk_manager.write_page(page.page_id, page.data)

        # Reset the frame and return it to the free list
        page.reset()
        del self.page_table[page_id]
        self.free_list.append(frame_idx)

        # Deallocate on disk
        self.disk_manager.deallocate_page(page_id)

        return True

    # ──────────────────────────────────────────────
    # Diagnostic / Inspection
    # ──────────────────────────────────────────────

    def get_pin_count(self, page_id: int) -> int:
        """Get the pin count for a page. Returns -1 if not in the pool."""
        if page_id not in self.page_table:
            return -1
        return self.frames[self.page_table[page_id]].pin_count

    def is_dirty(self, page_id: int) -> bool:
        """Check if a page is dirty. Returns False if not in the pool."""
        if page_id not in self.page_table:
            return False
        return self.frames[self.page_table[page_id]].is_dirty

    def get_num_free_frames(self) -> int:
        """Return the number of free (unused) frames in the pool."""
        return len(self.free_list)

    def get_pages_in_pool(self) -> Set[int]:
        """Return the set of page_ids currently in the buffer pool."""
        return set(self.page_table.keys())

    # ──────────────────────────────────────────────
    # Internal: Frame management and LRU eviction
    # ──────────────────────────────────────────────

    def _get_free_frame(self) -> Optional[int]:
        """
        Get a free frame index. If no free frames, evict the LRU page.

        Returns:
            A frame index, or None if all frames are pinned.
        """
        # Try the free list first
        if self.free_list:
            return self.free_list.pop()

        # No free frames — must evict
        return self._evict_lru()

    def _evict_lru(self) -> Optional[int]:
        """
        Evict the least-recently-used unpinned page.

        If the evicted page is dirty, it is flushed to disk first.

        Returns:
            The freed frame index, or None if all pages are pinned.
        """
        if not self._lru:
            return None  # All pages are pinned, nothing to evict

        # Pop the least-recently-used page (front of OrderedDict)
        evict_page_id, _ = self._lru.popitem(last=False)

        frame_idx = self.page_table[evict_page_id]
        page = self.frames[frame_idx]

        # If dirty, flush to disk before evicting
        if page.is_dirty:
            self.disk_manager.write_page(page.page_id, page.data)

        # Clean up
        page.reset()
        del self.page_table[evict_page_id]

        return frame_idx

    def __repr__(self) -> str:
        dirty_count = sum(
            1 for f in self.frames
            if f.page_id != INVALID_PAGE_ID and f.is_dirty
        )
        return (
            f"BufferPoolManager(pool_size={self.pool_size}, "
            f"used={len(self.page_table)}, "
            f"free={len(self.free_list)}, "
            f"dirty={dirty_count}, "
            f"lru_size={len(self._lru)})"
        )
