"""
ChronoDB Storage Engine — WAL Log Record

Defines the binary log record format for the Write-Ahead Log.

Record types:
  BEGIN      — Transaction start marker
  COMMIT     — Transaction committed (durable)
  ABORT      — Transaction rolled back
  UPDATE     — Page mutation (stores the after-image for redo)
  CHECKPOINT — All dirty pages flushed; recovery starts from here

Binary wire format (big-endian):
  ┌────────────┬─────────┬──────────┬────────┬──────┬─────────┬───────────┬──────────────┬──────────┐
  │ record_len │   LSN   │ prev_lsn │ txn_id │ type │ page_id │ img_len   │ after_image  │  CRC32   │
  │  4 bytes   │ 8 bytes │  8 bytes │ 8 bytes│1 byte│ 4 bytes │  4 bytes  │  0..4096 B   │  4 bytes │
  └────────────┴─────────┴──────────┴────────┴──────┴─────────┴───────────┴──────────────┴──────────┘
  record_len covers everything AFTER itself (LSN through CRC32).
  CRC32 covers everything from LSN through end of after_image.
"""

import struct
import zlib
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional


class LogRecordType(IntEnum):
    """WAL log record types."""
    BEGIN = 1       # Transaction start
    COMMIT = 2      # Transaction committed
    ABORT = 3       # Transaction aborted
    UPDATE = 4      # Page mutation (redo after-image)
    CHECKPOINT = 5  # Checkpoint marker


# Binary header: LSN(Q) + prev_lsn(Q) + txn_id(Q) + type(B) + page_id(i)
_HEADER_FORMAT = ">QQQBi"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)  # 29 bytes


@dataclass
class LogRecord:
    """
    A single WAL log record.

    Attributes:
        lsn: Log Sequence Number — globally unique, monotonically increasing.
        prev_lsn: Previous LSN for this transaction (for undo chaining).
        txn_id: Transaction identifier.
        record_type: Type of log record (BEGIN, COMMIT, ABORT, UPDATE, CHECKPOINT).
        page_id: Page affected by this record (-1 if N/A, e.g. BEGIN/COMMIT).
        after_image: The page data AFTER the mutation (redo image). Only
                     present for UPDATE records. Exactly PAGE_SIZE bytes.
    """
    lsn: int = 0
    prev_lsn: int = 0
    txn_id: int = 0
    record_type: LogRecordType = LogRecordType.BEGIN
    page_id: int = -1
    after_image: Optional[bytes] = None

    def serialize(self) -> bytes:
        """
        Serialize this record to bytes with a length prefix and CRC32 checksum.

        Returns:
            Complete binary record: [4-byte length] + [body] + [4-byte CRC32]
        """
        # Pack header
        header = struct.pack(
            _HEADER_FORMAT,
            self.lsn, self.prev_lsn, self.txn_id,
            int(self.record_type), self.page_id,
        )

        # Pack after-image (variable length, 0 for non-UPDATE records)
        img_data = self.after_image or b""
        img_len = struct.pack(">I", len(img_data))

        # Body = header + img_len + img_data
        body = header + img_len + img_data

        # CRC32 checksum of body
        checksum = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        # Length prefix (covers body + checksum)
        length_prefix = struct.pack(">I", len(body) + 4)

        return length_prefix + body + checksum

    @classmethod
    def deserialize(cls, data: bytes) -> "LogRecord":
        """
        Deserialize a log record from bytes (WITHOUT the 4-byte length prefix).

        Args:
            data: Record bytes starting from LSN through CRC32.

        Returns:
            The deserialized LogRecord.

        Raises:
            ValueError: If the checksum doesn't match (corrupted record).
        """
        offset = 0

        # Unpack header
        lsn, prev_lsn, txn_id, record_type, page_id = struct.unpack_from(
            _HEADER_FORMAT, data, offset
        )
        offset += _HEADER_SIZE

        # Unpack after-image length
        (img_len,) = struct.unpack_from(">I", data, offset)
        offset += 4

        # Read after-image bytes
        after_image = bytes(data[offset : offset + img_len]) if img_len > 0 else None
        offset += img_len

        # Verify CRC32 checksum
        body = data[:offset]
        (stored_crc,) = struct.unpack_from(">I", data, offset)
        computed_crc = zlib.crc32(body) & 0xFFFFFFFF

        if stored_crc != computed_crc:
            raise ValueError(
                f"WAL record CRC mismatch at LSN {lsn}: "
                f"stored=0x{stored_crc:08x}, computed=0x{computed_crc:08x}"
            )

        return cls(
            lsn=lsn,
            prev_lsn=prev_lsn,
            txn_id=txn_id,
            record_type=LogRecordType(record_type),
            page_id=page_id,
            after_image=after_image,
        )

    def __repr__(self) -> str:
        img_info = f", img={len(self.after_image)}B" if self.after_image else ""
        return (
            f"LogRecord(lsn={self.lsn}, txn={self.txn_id}, "
            f"type={self.record_type.name}, page={self.page_id}{img_info})"
        )
