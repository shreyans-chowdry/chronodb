"""
ChronoDB Storage Engine — Delta Encoding & Decoding

Provides utilities to compute, encode, and apply deltas for historical row versions.
Delta-encoded pages store only the modified/added/deleted fields relative to a base
ancestor snapshot, saving significant storage bytes for cold versions.

Page Binary Layout (4KB):
  Byte 0:       0xDE (Magic byte indicating a delta page)
  Bytes 1-4:    base_page_id (4 bytes, signed big-endian integer)
  Bytes 5-8:    payload_length (4 bytes, unsigned big-endian integer)
  Bytes 9..9+L: UTF-8 encoded JSON payload: {"set": {...}, "del": [...]}
  Bytes 9+L..:  0x00 padding up to PAGE_SIZE (4096 bytes)
"""

import json
import struct
from typing import Any, Dict, List, Optional, Tuple

from .page import PAGE_SIZE, INVALID_PAGE_ID

DELTA_MAGIC = 0xDE


def is_delta_page(page_data: bytearray) -> bool:
    """Check if the given page buffer starts with the delta magic byte."""
    return len(page_data) > 0 and page_data[0] == DELTA_MAGIC


def compute_delta(base_data: Dict[str, Any], current_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute the difference from base_data to current_data.
    
    Returns a dictionary:
      - "set": fields that were added or modified in current_data
      - "del": fields that were present in base_data but removed in current_data
    """
    delta_set: Dict[str, Any] = {}
    delta_del: List[str] = []

    for k, v in current_data.items():
        if k not in base_data or base_data[k] != v:
            delta_set[k] = v

    for k in base_data:
        if k not in current_data:
            delta_del.append(k)

    return {"set": delta_set, "del": delta_del}


def apply_delta(base_data: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply a delta to base_data to reconstruct the target version data.
    """
    reconstructed = dict(base_data)
    for k in delta.get("del", []):
        reconstructed.pop(k, None)
    for k, v in delta.get("set", {}).items():
        reconstructed[k] = v
    return reconstructed


def encode_delta_page(base_data: Dict[str, Any], current_data: Dict[str, Any], base_page_id: int) -> bytes:
    """
    Encode the delta between base_data and current_data into a 4KB page byte array.
    """
    delta = compute_delta(base_data, current_data)
    payload_bytes = json.dumps(delta).encode("utf-8")
    payload_len = len(payload_bytes)

    header_len = 9  # 1 (magic) + 4 (base_page_id) + 4 (payload_len)
    total_len = header_len + payload_len

    if total_len > PAGE_SIZE:
        raise ValueError(f"Delta payload size {total_len} exceeds PAGE_SIZE {PAGE_SIZE}")

    header = struct.pack(">B i I", DELTA_MAGIC, base_page_id, payload_len)
    return header + payload_bytes


def decode_delta_page(page_data: bytearray) -> Tuple[int, Dict[str, Any]]:
    """
    Decode a delta page into (base_page_id, delta_dict).
    
    Raises:
        ValueError: If the page is not a valid delta page.
    """
    if len(page_data) < 9 or page_data[0] != DELTA_MAGIC:
        raise ValueError("Invalid delta page: magic byte mismatch or buffer too small")

    magic, base_page_id, payload_len = struct.unpack(">B i I", bytes(page_data[:9]))
    if 9 + payload_len > len(page_data):
        raise ValueError(f"Invalid delta page payload length: {payload_len}")

    delta_json = page_data[9:9 + payload_len].decode("utf-8")
    delta = json.loads(delta_json)
    return base_page_id, delta
