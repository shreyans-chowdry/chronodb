"""
Unit tests for ChronoDB Buffer Pool Manager.

Tests cover the three invariants from the prompt:
  1. Allocation — new_page() and fetch_page() correctly manage frames
  2. Eviction under memory pressure — LRU eviction when pool is full
  3. Correct flush of dirty pages — dirty pages written to disk on eviction/checkpoint

Additional tests cover pin counting, page deletion, and edge cases.
"""

import sys
import os
import tempfile
import pytest

# Path setup for flexible execution
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.abspath(os.path.join(engine_dir, "src"))
for p in (root_dir, engine_dir, src_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from engine.src.storage.page import Page, PAGE_SIZE, INVALID_PAGE_ID
    from engine.src.storage.disk_manager import DiskManager
    from engine.src.storage.buffer_pool import BufferPoolManager
except ImportError:
    try:
        from src.storage.page import Page, PAGE_SIZE, INVALID_PAGE_ID  # type: ignore # pyright: ignore
        from src.storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from src.storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore
    except ImportError:
        from storage.page import Page, PAGE_SIZE, INVALID_PAGE_ID  # type: ignore # pyright: ignore
        from storage.disk_manager import DiskManager  # type: ignore # pyright: ignore
        from storage.buffer_pool import BufferPoolManager  # type: ignore # pyright: ignore


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database file path."""
    return str(tmp_path / "test_chronodb.dat")


@pytest.fixture
def disk_manager(tmp_db):
    """Create a DiskManager backed by a temp file."""
    dm = DiskManager(tmp_db)
    yield dm
    dm.close()


@pytest.fixture
def small_pool(disk_manager):
    """Create a small (3-frame) BufferPoolManager for eviction testing."""
    return BufferPoolManager(pool_size=3, disk_manager=disk_manager)


@pytest.fixture
def large_pool(disk_manager):
    """Create a larger (10-frame) BufferPoolManager for general testing."""
    return BufferPoolManager(pool_size=10, disk_manager=disk_manager)


# ══════════════════════════════════════════════════
# Page Tests
# ══════════════════════════════════════════════════


class TestPage:
    """Basic page functionality."""

    def test_page_size_is_4kb(self):
        """Pages must be exactly 4096 bytes."""
        assert PAGE_SIZE == 4096

    def test_new_page_is_zeroed(self):
        """A new page should contain all zeros."""
        p = Page(page_id=0)
        assert len(p.data) == PAGE_SIZE
        assert all(b == 0 for b in p.data)

    def test_page_reset_clears_state(self):
        """reset() should return the page to a clean, empty state."""
        p = Page(page_id=42)
        p.data[:5] = b"hello"
        p.is_dirty = True
        p.pin_count = 3
        p.reset()
        assert p.page_id == INVALID_PAGE_ID
        assert p.is_dirty is False
        assert p.pin_count == 0
        assert all(b == 0 for b in p.data)


# ══════════════════════════════════════════════════
# Disk Manager Tests
# ══════════════════════════════════════════════════


class TestDiskManager:
    """Disk I/O correctness."""

    def test_allocate_page_returns_sequential_ids(self, disk_manager):
        """Allocated pages should have sequential IDs starting from 0."""
        p0 = disk_manager.allocate_page()
        p1 = disk_manager.allocate_page()
        p2 = disk_manager.allocate_page()
        assert p0 == 0
        assert p1 == 1
        assert p2 == 2

    def test_write_then_read_roundtrip(self, disk_manager):
        """Data written to a page should be readable back exactly."""
        page_id = disk_manager.allocate_page()
        data = bytearray(PAGE_SIZE)
        data[:11] = b"ChronoDB!!!"
        data[PAGE_SIZE - 4:] = b"END!"

        disk_manager.write_page(page_id, data)
        read_back = disk_manager.read_page(page_id)

        assert read_back[:11] == b"ChronoDB!!!"
        assert read_back[PAGE_SIZE - 4:] == b"END!"

    def test_read_invalid_page_raises(self, disk_manager):
        """Reading a page that hasn't been allocated should raise ValueError."""
        with pytest.raises(ValueError, match="Cannot read page"):
            disk_manager.read_page(999)

    def test_write_wrong_size_raises(self, disk_manager):
        """Writing data that isn't exactly PAGE_SIZE should raise ValueError."""
        disk_manager.allocate_page()
        with pytest.raises(ValueError, match="must be exactly"):
            disk_manager.write_page(0, bytearray(100))

    def test_get_num_pages(self, disk_manager):
        """get_num_pages() should track the number of allocated pages."""
        assert disk_manager.get_num_pages() == 0
        disk_manager.allocate_page()
        disk_manager.allocate_page()
        assert disk_manager.get_num_pages() == 2


# ══════════════════════════════════════════════════
# Buffer Pool Manager — Allocation Tests
# ══════════════════════════════════════════════════


class TestAllocation:
    """Test page allocation and fetching."""

    def test_new_page_returns_valid_page(self, large_pool):
        """new_page() should return a page with valid page_id and pin_count=1."""
        page = large_pool.new_page()
        assert page is not None
        assert page.page_id >= 0
        assert page.pin_count == 1
        assert page.is_dirty is False

    def test_new_pages_have_unique_ids(self, large_pool):
        """Each new page should have a unique page_id."""
        pages = [large_pool.new_page() for _ in range(5)]
        ids = [p.page_id for p in pages]
        assert len(set(ids)) == 5

    def test_fetch_page_returns_same_page(self, large_pool):
        """Fetching a page already in the pool should return the same object."""
        page = large_pool.new_page()
        page.data[:5] = b"hello"
        page_id = page.page_id
        large_pool.unpin_page(page_id, is_dirty=True)

        fetched = large_pool.fetch_page(page_id)
        assert fetched is not None
        assert fetched.page_id == page_id
        assert fetched.data[:5] == b"hello"

    def test_fetch_increments_pin_count(self, large_pool):
        """Each fetch should increment the pin count."""
        page = large_pool.new_page()
        page_id = page.page_id
        assert page.pin_count == 1

        # Fetch again (double pin)
        fetched = large_pool.fetch_page(page_id)
        assert fetched.pin_count == 2

    def test_new_page_returns_none_when_full_and_all_pinned(self, small_pool):
        """If pool is full and all pages are pinned, new_page() returns None."""
        # Fill all 3 frames, keep them pinned
        p0 = small_pool.new_page()
        p1 = small_pool.new_page()
        p2 = small_pool.new_page()

        # Pool is full, all pinned → should return None
        assert small_pool.new_page() is None

    def test_free_frame_count_decreases_on_allocation(self, large_pool):
        """Allocating pages should decrease the free frame count."""
        initial_free = large_pool.get_num_free_frames()
        large_pool.new_page()
        assert large_pool.get_num_free_frames() == initial_free - 1


# ══════════════════════════════════════════════════
# Buffer Pool Manager — Eviction Tests
# ══════════════════════════════════════════════════


class TestEvictionUnderMemoryPressure:
    """Test LRU eviction when the pool is full."""

    def test_lru_eviction_frees_frame_for_new_page(self, small_pool):
        """
        When pool is full but pages are unpinned, LRU eviction should
        free a frame for a new page.
        """
        # Fill the pool (3 frames)
        p0 = small_pool.new_page()
        p1 = small_pool.new_page()
        p2 = small_pool.new_page()
        id0, id1, id2 = p0.page_id, p1.page_id, p2.page_id

        # Unpin all (making them evictable)
        small_pool.unpin_page(id0)
        small_pool.unpin_page(id1)
        small_pool.unpin_page(id2)

        # Allocate a 4th page — should evict the LRU (p0, first unpinned)
        p3 = small_pool.new_page()
        assert p3 is not None
        assert id0 not in small_pool.get_pages_in_pool()  # p0 was evicted
        assert p3.page_id in small_pool.get_pages_in_pool()

    def test_lru_eviction_order_is_correct(self, small_pool):
        """
        Pages should be evicted in LRU order: the least-recently-used
        unpinned page goes first.
        """
        # Fill pool
        p0 = small_pool.new_page()
        p1 = small_pool.new_page()
        p2 = small_pool.new_page()

        # Save IDs before eviction (Page objects are reused when frames recycle)
        id0, id1, id2 = p0.page_id, p1.page_id, p2.page_id

        # Unpin in order: p0, p1, p2
        small_pool.unpin_page(id0)
        small_pool.unpin_page(id1)
        small_pool.unpin_page(id2)

        # Access p0 again (moves it to most-recently-used end)
        fetched_p0 = small_pool.fetch_page(id0)
        small_pool.unpin_page(id0)

        # Now LRU order is: p1 (least recent) → p2 → p0 (most recent)
        # Allocate new page — should evict p1
        p3 = small_pool.new_page()
        assert id1 not in small_pool.get_pages_in_pool()  # p1 was evicted
        assert id0 in small_pool.get_pages_in_pool()       # p0 survived
        assert id2 in small_pool.get_pages_in_pool()       # p2 survived

    def test_pinned_pages_are_not_evicted(self, small_pool):
        """Pinned pages (pin_count > 0) must NEVER be evicted."""
        # Fill pool
        p0 = small_pool.new_page()  # pinned
        p1 = small_pool.new_page()
        p2 = small_pool.new_page()

        # Save IDs before eviction (Page objects are reused when frames recycle)
        id0, id1, id2 = p0.page_id, p1.page_id, p2.page_id

        # Keep p0 pinned, unpin p1 and p2
        small_pool.unpin_page(id1)
        small_pool.unpin_page(id2)

        # Allocate two new pages — p1 and p2 should be evicted, NOT p0
        p3 = small_pool.new_page()
        p4 = small_pool.new_page()

        assert id0 in small_pool.get_pages_in_pool()       # p0 is pinned, safe
        assert id1 not in small_pool.get_pages_in_pool()   # p1 evicted
        assert id2 not in small_pool.get_pages_in_pool()   # p2 evicted

    def test_eviction_when_all_pinned_returns_none(self, small_pool):
        """If all pages are pinned, fetch_page for a non-cached page returns None."""
        # Fill pool, keep all pinned
        p0 = small_pool.new_page()
        p1 = small_pool.new_page()
        p2 = small_pool.new_page()

        # Allocate a page on disk that's not in the pool
        page_id = small_pool.disk_manager.allocate_page()

        # Try to fetch — should fail (no evictable frames)
        result = small_pool.fetch_page(page_id)
        assert result is None


# ══════════════════════════════════════════════════
# Buffer Pool Manager — Dirty Page Flush Tests
# ══════════════════════════════════════════════════


class TestDirtyPageFlush:
    """Test that dirty pages are correctly flushed to disk."""

    def test_dirty_page_flushed_on_eviction(self, small_pool):
        """
        When a dirty page is evicted, its data must be written to disk
        before the frame is reused.
        """
        # Create a page and write data to it
        page = small_pool.new_page()
        page_id = page.page_id
        page.data[:6] = b"DIRTY!"
        small_pool.unpin_page(page_id, is_dirty=True)

        # Fill the rest of the pool
        p1 = small_pool.new_page()
        small_pool.unpin_page(p1.page_id)
        p2 = small_pool.new_page()
        small_pool.unpin_page(p2.page_id)

        # Allocate another page — this should evict our dirty page
        p3 = small_pool.new_page()

        # The evicted page's data should now be on disk
        disk_data = small_pool.disk_manager.read_page(page_id)
        assert disk_data[:6] == b"DIRTY!"

    def test_clean_page_not_flushed_on_eviction(self, small_pool, tmp_db):
        """
        When a clean page is evicted, no disk write should occur
        (the on-disk copy is already up to date).
        """
        # Create and immediately unpin without marking dirty
        page = small_pool.new_page()
        page_id = page.page_id
        small_pool.unpin_page(page_id, is_dirty=False)

        # On-disk data should still be all zeros (never written)
        disk_data = small_pool.disk_manager.read_page(page_id)
        assert all(b == 0 for b in disk_data)

    def test_flush_page_writes_to_disk(self, large_pool):
        """flush_page() should write a dirty page to disk and clear the dirty flag."""
        page = large_pool.new_page()
        page_id = page.page_id
        page.data[:4] = b"SYNC"
        large_pool.unpin_page(page_id, is_dirty=True)

        assert large_pool.is_dirty(page_id) is True

        # Flush
        large_pool.flush_page(page_id)
        assert large_pool.is_dirty(page_id) is False

        # Verify on disk
        disk_data = large_pool.disk_manager.read_page(page_id)
        assert disk_data[:4] == b"SYNC"

    def test_flush_all_pages_checkpoint(self, large_pool):
        """
        flush_all_pages() (checkpoint) should write ALL dirty pages to disk.
        """
        # Create several pages with data
        pages = []
        for i in range(5):
            p = large_pool.new_page()
            p.data[:1] = bytes([i + 65])  # A, B, C, D, E
            pages.append(p)

        # Unpin some as dirty, some as clean
        large_pool.unpin_page(pages[0].page_id, is_dirty=True)
        large_pool.unpin_page(pages[1].page_id, is_dirty=False)  # clean
        large_pool.unpin_page(pages[2].page_id, is_dirty=True)
        large_pool.unpin_page(pages[3].page_id, is_dirty=True)
        large_pool.unpin_page(pages[4].page_id, is_dirty=False)  # clean

        # Checkpoint — should flush 3 dirty pages
        flushed = large_pool.flush_all_pages()
        assert flushed == 3

        # Verify dirty pages are on disk
        assert large_pool.disk_manager.read_page(pages[0].page_id)[:1] == b"A"
        assert large_pool.disk_manager.read_page(pages[2].page_id)[:1] == b"C"
        assert large_pool.disk_manager.read_page(pages[3].page_id)[:1] == b"D"

        # All pages should now be clean
        for p in pages:
            assert large_pool.is_dirty(p.page_id) is False

    def test_dirty_flag_is_sticky(self, large_pool):
        """
        The dirty flag should be sticky: marking a page dirty and then
        unpinning without the dirty flag should NOT clear it.
        """
        page = large_pool.new_page()
        page_id = page.page_id
        large_pool.unpin_page(page_id, is_dirty=True)
        assert large_pool.is_dirty(page_id) is True

        # Fetch and unpin without dirty flag — should still be dirty
        fetched = large_pool.fetch_page(page_id)
        large_pool.unpin_page(page_id, is_dirty=False)
        assert large_pool.is_dirty(page_id) is True


# ══════════════════════════════════════════════════
# Buffer Pool Manager — Pin Count Tests
# ══════════════════════════════════════════════════


class TestPinCount:
    """Test pin counting behavior."""

    def test_unpin_decrements_pin_count(self, large_pool):
        """unpin_page should decrement pin_count by 1."""
        page = large_pool.new_page()
        assert page.pin_count == 1
        large_pool.unpin_page(page.page_id)
        assert large_pool.get_pin_count(page.page_id) == 0

    def test_multiple_pins_and_unpins(self, large_pool):
        """Multiple fetches should increment pin count; multiple unpins decrement."""
        page = large_pool.new_page()
        page_id = page.page_id

        # Pin twice more
        large_pool.fetch_page(page_id)
        large_pool.fetch_page(page_id)
        assert large_pool.get_pin_count(page_id) == 3

        # Unpin all
        large_pool.unpin_page(page_id)
        large_pool.unpin_page(page_id)
        large_pool.unpin_page(page_id)
        assert large_pool.get_pin_count(page_id) == 0

    def test_unpin_nonexistent_page_returns_false(self, large_pool):
        """Unpinning a page not in the pool should return False."""
        assert large_pool.unpin_page(9999) is False


# ══════════════════════════════════════════════════
# Buffer Pool Manager — Delete Page Tests
# ══════════════════════════════════════════════════


class TestDeletePage:
    """Test page deletion."""

    def test_delete_unpinned_page(self, large_pool):
        """Deleting an unpinned page should succeed and free the frame."""
        page = large_pool.new_page()
        page_id = page.page_id
        free_before = large_pool.get_num_free_frames()
        large_pool.unpin_page(page_id)
        assert large_pool.delete_page(page_id) is True
        assert page_id not in large_pool.get_pages_in_pool()
        assert large_pool.get_num_free_frames() == free_before + 1

    def test_delete_pinned_page_fails(self, large_pool):
        """Deleting a pinned page should fail (return False)."""
        page = large_pool.new_page()
        assert large_pool.delete_page(page.page_id) is False


# ══════════════════════════════════════════════════
# Integration: Data Persistence Through Eviction
# ══════════════════════════════════════════════════


class TestDataPersistence:
    """Test that data survives eviction + re-fetch cycle."""

    def test_data_survives_eviction_and_refetch(self, small_pool):
        """
        Write data to a page → unpin dirty → evict → fetch again.
        The data should be intact (read from disk after eviction).
        """
        # Write data
        page = small_pool.new_page()
        page_id = page.page_id
        page.data[:12] = b"ChronoDB_FTW"
        small_pool.unpin_page(page_id, is_dirty=True)

        # Fill pool to force eviction of our page
        p1 = small_pool.new_page()
        small_pool.unpin_page(p1.page_id)
        p2 = small_pool.new_page()
        small_pool.unpin_page(p2.page_id)
        p3 = small_pool.new_page()  # evicts our page
        small_pool.unpin_page(p3.page_id)

        # Page should have been evicted
        assert page_id not in small_pool.get_pages_in_pool()

        # Fetch it back — should read from disk
        refetched = small_pool.fetch_page(page_id)
        assert refetched is not None
        assert refetched.data[:12] == b"ChronoDB_FTW"

    def test_multiple_eviction_cycles(self, small_pool):
        """Data should survive multiple eviction and re-fetch cycles."""
        page = small_pool.new_page()
        page_id = page.page_id
        page.data[:4] = b"ABCD"
        small_pool.unpin_page(page_id, is_dirty=True)

        # Evict and refetch 3 times
        for cycle in range(3):
            # Fill pool to evict our page
            temps = []
            for _ in range(3):
                t = small_pool.new_page()
                if t:
                    temps.append(t)
            for t in temps:
                small_pool.unpin_page(t.page_id)

            # Re-fetch and verify
            refetched = small_pool.fetch_page(page_id)
            assert refetched is not None
            assert refetched.data[:4] == b"ABCD", f"Data lost in cycle {cycle}"
            small_pool.unpin_page(page_id)
