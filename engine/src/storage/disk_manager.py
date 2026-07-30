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

        # Create the file if it doesn't exist; otherwise determine next_page_id
        # from existing file size
        if os.path.exists(db_file_path):
            file_size = os.path.getsize(db_file_path)
            self._next_page_id = file_size // PAGE_SIZE
        else:
            # Create an empty file
            with open(db_file_path, "wb") as f:
                pass

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

            with open(self.db_file_path, "rb") as f:
                f.seek(offset)
                bytes_read = f.readinto(data)

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

            with open(self.db_file_path, "r+b") as f:
                f.seek(offset)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

    def allocate_page(self) -> int:
        """
        Allocate a new page on disk and return its page_id.

        The new page is zeroed out on disk.

        Returns:
            The page_id of the newly allocated page.
        """
        with self._lock:
            page_id = self._next_page_id
            self._next_page_id += 1

            # Extend the file with a zeroed page
            with open(self.db_file_path, "ab") as f:
                f.write(bytearray(PAGE_SIZE))
                f.flush()
                os.fsync(f.fileno())

            return page_id

    def deallocate_page(self, page_id: int) -> None:
        """
        Mark a page as deallocated.

        For now, this is a no-op (the space is not reclaimed). A future
        implementation will maintain a free-page list for reuse.
        """
        # TODO: Implement free-page list for space reclamation
        pass

    def get_num_pages(self) -> int:
        """Return the total number of pages allocated on disk."""
        return self._next_page_id

    def close(self) -> None:
        """Close the disk manager. No-op for file-based I/O."""
        pass

    def __repr__(self) -> str:
        return (
            f"DiskManager(file='{self.db_file_path}', "
            f"pages={self._next_page_id})"
        )
