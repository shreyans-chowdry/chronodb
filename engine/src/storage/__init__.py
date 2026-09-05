"""
ChronoDB Storage Engine — Public API

Exports the page-based storage components:
  - Page, DiskManager, BufferPoolManager
  - Delta encoding/decoding: encode_delta_page, decode_delta_page, apply_delta, compute_delta, is_delta_page
  - Unified reader: read_row_data
  - Adaptive Storage Optimizer: StorageOptimizer, OptimizerReport
"""

from .page import Page, PAGE_SIZE, INVALID_PAGE_ID
from .disk_manager import DiskManager
from .buffer_pool import BufferPoolManager
from .delta import (
    DELTA_MAGIC,
    is_delta_page,
    compute_delta,
    apply_delta,
    encode_delta_page,
    decode_delta_page,
)
from .reader import read_row_data
from .optimizer import StorageOptimizer, OptimizerReport

__all__ = [
    "Page",
    "PAGE_SIZE",
    "INVALID_PAGE_ID",
    "DiskManager",
    "BufferPoolManager",
    "DELTA_MAGIC",
    "is_delta_page",
    "compute_delta",
    "apply_delta",
    "encode_delta_page",
    "decode_delta_page",
    "read_row_data",
    "StorageOptimizer",
    "OptimizerReport",
]
