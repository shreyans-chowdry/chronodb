"""
ChronoDB Storage Engine — Disk Manager

Handles raw I/O between the buffer pool and the database file on disk.
Pages are stored sequentially: page N lives at byte offset N * PAGE_SIZE.

The DiskManager is the ONLY component that touches the filesystem directly —
all other components go through the Buffer Pool Manager.
"""

import os
import threading
from typing import Optional

from .page import PAGE_SIZE


class DiskManager:
    """
    Manages reading and writing fixed-size pages to/from a database file.

    Pages are laid out contiguously in the file:
        Page 0: bytes [0, PAGE_SIZE)
        Page 1: bytes [PAGE_SIZE, 2*PAGE_SIZE)
        ...

    Thread-safety: All I/O operations are protected by a lock.

    Args:
        db_file_path: Path to the database file. Created if it doesn't exist.
    """

    def __init__(self, db_file_path: str):
        self.db_file_path = db_file_path
        self._lock = threading.Lock()
        self._next_page_id = 0
        # Pages released by GC / the storage optimizer. They are handed out again
        # by allocate_page() before the file is extended. The list itself is
        # persisted by the SystemCatalog header.
        self.free_pages: list = []

        # Create the file if it doesn't exist; otherwise determine next_page_id
        # from existing file size
        if os.path.exists(db_file_path):
            file_size = os.path.getsize(db_file_path)
            self._next_page_id = file_size // PAGE_SIZE
        else:
            # Create an empty file
            with open(db_file_path, "wb") as f:
                pass

        # One long-lived handle. Durability comes from the WAL, so individual
        # page writes are not fsync'd; sync() is called at checkpoints.
        self._fh = open(db_file_path, "r+b")

    def read_page(self, page_id: int) -> bytearray:
        """
        Read a page from disk into a bytearray buffer.

        Args:
            page_id: The page to read.

        Returns:
            A bytearray of exactly PAGE_SIZE bytes.

        Raises:
            ValueError: If page_id is out of range.
        """
        with self._lock:
            if page_id < 0 or page_id >= self._next_page_id:
                raise ValueError(
                    f"Cannot read page {page_id}: valid range is [0, {self._next_page_id})"
                )

            offset = page_id * PAGE_SIZE
            data = bytearray(PAGE_SIZE)

            self._fh.seek(offset)
            bytes_read = self._fh.readinto(data)

            # Pad with zeros if the file is shorter than expected (shouldn't
            # happen in normal operation, but handle gracefully)
            if bytes_read is None or bytes_read < PAGE_SIZE:
                pass  # data is already zero-padded from bytearray init

            return data

    def write_page(self, page_id: int, data: bytearray) -> None:
        """
        Write a page's data to disk at the correct offset.

        Args:
            page_id: The page slot to write to.
            data: Exactly PAGE_SIZE bytes to write.

        Raises:
            ValueError: If data is not exactly PAGE_SIZE bytes.
        """
        if len(data) != PAGE_SIZE:
            raise ValueError(
                f"Page data must be exactly {PAGE_SIZE} bytes, got {len(data)}"
            )

        with self._lock:
            offset = page_id * PAGE_SIZE
            self._fh.seek(offset)
            self._fh.write(data)
            self._fh.flush()  # hand to the OS (no fsync)

    def allocate_page(self) -> int:
        """
        Allocate a page and return its page_id.

        A previously freed page is reused when one is available; otherwise the
        file is extended by one zeroed page.

        Returns:
            The page_id of the allocated page.
        """
        with self._lock:
            if self.free_pages:
                return self.free_pages.pop()
            page_id = self._next_page_id
            self._next_page_id += 1

            # Extend the file with a zeroed page
            self._fh.seek(page_id * PAGE_SIZE)
            self._fh.write(bytes(PAGE_SIZE))
            self._fh.flush()

            return page_id

    def deallocate_page(self, page_id: int) -> None:
        """
        Return a page to the free list so that a later allocation can reuse it.
        The file is not shrunk; freed pages are recycled in place.
        """
        with self._lock:
            if 0 <= page_id < self._next_page_id and page_id not in self.free_pages:
                self.free_pages.append(page_id)

    def get_num_live_pages(self) -> int:
        """Pages that are allocated and not on the free list."""
        return self._next_page_id - len(self.free_pages)

    def get_num_pages(self) -> int:
        """Return the total number of pages allocated on disk."""
        return self._next_page_id

    def sync(self) -> None:
        """Force all written pages to stable storage."""
        with self._lock:
            if self._fh and not self._fh.closed:
                self._fh.flush()
                os.fsync(self._fh.fileno())

    def get_file_size(self) -> int:
        return self._next_page_id * PAGE_SIZE

    def close(self) -> None:
        """Flush and close the file handle."""
        with self._lock:
            if self._fh and not self._fh.closed:
                self._fh.flush()
                os.fsync(self._fh.fileno())
                self._fh.close()

    def __repr__(self) -> str:
        return (
            f"DiskManager(file='{self.db_file_path}', "
            f"pages={self._next_page_id})"
        )
