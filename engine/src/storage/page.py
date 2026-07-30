"""
ChronoDB Storage Engine — Page Abstraction

Fixed 4KB page as the fundamental unit of storage. Every piece of data in the
storage engine lives inside a page. Pages are identified by a unique page_id
and contain a fixed-size byte buffer.

This is the custom storage layer — NOT the throwaway SQLite scaffold.
"""

# Fixed page size: 4KB (4096 bytes), matching typical OS page size and
# standard database page sizes (PostgreSQL uses 8KB, SQLite uses 4KB).
PAGE_SIZE = 4096

# Sentinel value for "no page"
INVALID_PAGE_ID = -1


class Page:
    """
    Represents a single fixed-size (4KB) database page.

    Attributes:
        page_id: Unique identifier for this page on disk.
        data: The raw byte content of the page (always PAGE_SIZE bytes).
        is_dirty: Whether this page has been modified since last flush to disk.
        pin_count: Number of active users of this page. A page cannot be
                   evicted while pin_count > 0.
    """

    __slots__ = ("page_id", "data", "is_dirty", "pin_count")

    def __init__(self, page_id: int = INVALID_PAGE_ID):
        self.page_id: int = page_id
        self.data: bytearray = bytearray(PAGE_SIZE)
        self.is_dirty: bool = False
        self.pin_count: int = 0

    def reset(self):
        """Reset page to a clean, empty state (used when recycling a frame)."""
        self.page_id = INVALID_PAGE_ID
        self.data = bytearray(PAGE_SIZE)
        self.is_dirty = False
        self.pin_count = 0

    def __repr__(self) -> str:
        return (
            f"Page(id={self.page_id}, dirty={self.is_dirty}, "
            f"pin_count={self.pin_count}, used_bytes={self._used_bytes()})"
        )

    def _used_bytes(self) -> int:
        """Count non-zero bytes (rough measure of how full the page is)."""
        return sum(1 for b in self.data if b != 0)
