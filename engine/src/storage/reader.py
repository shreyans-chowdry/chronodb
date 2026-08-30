"""
ChronoDB Storage Engine — Unified Row Version Reader

Provides safe and transparent reading of row data from the Buffer Pool,
automatically detecting and decoding delta-encoded pages relative to base snapshots.
"""

import json
from typing import Any, Dict, Optional

from .buffer_pool import BufferPoolManager
from .page import PAGE_SIZE, INVALID_PAGE_ID
from .delta import is_delta_page, decode_delta_page, apply_delta


def read_row_data(
    pool: BufferPoolManager, page_version_id: int, max_depth: int = 50
) -> Optional[Dict[str, Any]]:
    """
    Read and deserialize row data from a page in the buffer pool.
    
    If the page is delta-encoded, it fetches the base snapshot page (recursively
    if necessary) and applies the delta to reconstruct the complete row dictionary.
    
    Ensures all fetched buffer pool pages are properly unpinned.
    
    Args:
        pool: The BufferPoolManager instance.
        page_version_id: The ID of the page to read.
        max_depth: Maximum recursion depth for delta chains.
        
    Returns:
        The decoded row data dictionary, or None if the page is empty/tombstone/invalid.
    """
    if page_version_id is None or page_version_id == INVALID_PAGE_ID:
        return None

    page = pool.fetch_page(page_version_id)
    if not page:
        return None

    try:
        if is_delta_page(page.data):
            base_page_id, delta = decode_delta_page(page.data)
            # Unpin current delta page before fetching base page to prevent pin exhaustion
            pool.unpin_page(page_version_id, is_dirty=False)

            if max_depth <= 0:
                raise RuntimeError(
                    f"Maximum delta chain depth exceeded resolving page {page_version_id}"
                )

            base_data = read_row_data(pool, base_page_id, max_depth=max_depth - 1)
            if base_data is None:
                return None
            return apply_delta(base_data, delta)

        else:
            # Full snapshot page
            null_idx = page.data.find(b"\x00")
            if null_idx == -1:
                null_idx = PAGE_SIZE
            if null_idx == 0:
                pool.unpin_page(page_version_id, is_dirty=False)
                return None

            data_json = page.data[:null_idx].decode("utf-8")
            pool.unpin_page(page_version_id, is_dirty=False)
            return json.loads(data_json)

    except Exception:
        # Guarantee page unpin in case of unexpected exception
        pool.unpin_page(page_version_id, is_dirty=False)
        raise
