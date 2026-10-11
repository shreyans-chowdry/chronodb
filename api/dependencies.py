"""
Shared engine instance for the API.

The original API opened a new VersionEngine for every request, which re-read
all metadata from disk on each call and lost the checked-out branch between
requests. A single engine is now opened lazily and shared. The storage engine
is single-writer, so api.main serializes requests with an asyncio lock in a
middleware (a thread lock held across a dependency's yield is released from a
different worker thread, which deadlocks).
"""

import os
import shutil
import threading
from typing import Optional

from engine.src.version.engine import VersionEngine

_lock = threading.RLock()
_engine: Optional[VersionEngine] = None
_engine_path: Optional[str] = None


def db_path() -> str:
    path = os.environ.get("CHRONODB_PATH", "api_test.db")
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or not os.access(".", os.W_OK):
        tmp_db = "/tmp/api_test.db"
        if not os.path.exists(tmp_db) and os.path.exists("api_test.db"):
            shutil.copyfile("api_test.db", tmp_db)
            if os.path.exists("api_test.db.wal"):
                shutil.copyfile("api_test.db.wal", tmp_db + ".wal")
        path = tmp_db
    return path


def engine_instance() -> VersionEngine:
    global _engine, _engine_path
    path = db_path()
    if _engine is None or _engine_path != path or not os.path.exists(path):
        if _engine is not None:
            try:
                _engine.close()
            except Exception:
                pass
        _engine = VersionEngine(db_path=path)
        _engine_path = path
    return _engine


def reset_engine() -> None:
    """Close the shared engine (used by the demo reset endpoint and tests)."""
    global _engine
    with _lock:
        if _engine is not None:
            try:
                _engine.close()
            except Exception:
                pass
        _engine = None


def get_engine() -> VersionEngine:
    with _lock:
        return engine_instance()
