"""
ChronoDB MVP Version Engine — Public API

This package provides the Git-like version-control engine for ChronoDB's MVP.
The engine uses SQLite as a temporary scaffold (to be replaced by a custom
page-based storage engine in Phase 2).
"""

from .engine import VersionEngine
from .schema import init_db

__all__ = ["VersionEngine", "init_db"]
