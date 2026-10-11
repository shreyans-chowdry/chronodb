"""
ChronoDB — Garbage Collection (Mark-and-Sweep)

Implements a mark-and-sweep garbage collector over the commit DAG:
  1. MARK: Starting from every branch HEAD, BFS-traverse the commit DAG
     (following parent_id and second_parent_id) to find all reachable commits.
  2. SWEEP: Any commit not in the reachable set is orphaned. Collect all
     page_version_ids referenced by orphaned commits in the B+ Tree version
     chains, deallocate those pages, prune the version chain entries, and
     remove the orphaned commits from the catalog.
"""

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("chronodb.gc")


@dataclass
class GCReport:
    """Statistics from a garbage collection run."""
    reachable_commits: int
    orphaned_commits: int
    pages_reclaimed: int
    version_entries_pruned: int
    commits_removed: int
    versions_rehydrated: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reachable_commits": self.reachable_commits,
            "orphaned_commits": self.orphaned_commits,
            "pages_reclaimed": self.pages_reclaimed,
            "version_entries_pruned": self.version_entries_pruned,
            "commits_removed": self.commits_removed,
            "versions_rehydrated": self.versions_rehydrated,
        }

    def summary(self) -> str:
        return (
            f"GC Summary:\n"
            f"  Reachable commits:      {self.reachable_commits}\n"
            f"  Orphaned commits:       {self.orphaned_commits}\n"
            f"  Pages reclaimed:        {self.pages_reclaimed}\n"
            f"  Version entries pruned: {self.version_entries_pruned}\n"
            f"  Commits removed:        {self.commits_removed}"
        )


class GarbageCollector:
    """
    Mark-and-sweep garbage collector for ChronoDB.

    Finds commits unreachable from any branch HEAD, then reclaims their
    page versions from the B+ Tree and deallocates the underlying disk pages.
    """

    def __init__(self, catalog: Any, btree: Any, pool: Any, heap: Any = None):
        self.catalog = catalog
        self.btree = btree
        self.pool = pool
        self.heap = heap
        self.versions_rehydrated = 0

    # ────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────

    def collect(self) -> GCReport:
        """
        Run a full mark-and-sweep garbage collection pass.

        Returns a GCReport with statistics about what was reclaimed.
        """
        # ── Phase 1: MARK ──
        reachable = self._mark_reachable()
        all_commit_ids = set(self.catalog.commits.keys())
        orphaned = all_commit_ids - reachable

        if not orphaned:
            return GCReport(
                reachable_commits=len(reachable),
                orphaned_commits=0,
                pages_reclaimed=0,
                version_entries_pruned=0,
                commits_removed=0,
            )

        # ── Phase 2: SWEEP ──
        pages_reclaimed, entries_pruned = self._sweep(orphaned)

        # Remove orphaned commits from the catalog
        commits_removed = self.catalog.remove_commits(orphaned)

        report = GCReport(
            reachable_commits=len(reachable),
            orphaned_commits=len(orphaned),
            pages_reclaimed=pages_reclaimed,
            version_entries_pruned=entries_pruned,
            commits_removed=commits_removed,
            versions_rehydrated=self.versions_rehydrated,
        )

        logger.info(report.summary())
        return report

    # ────────────────────────────────────────────────
    # Phase 1: MARK — BFS from all branch HEADs
    # ────────────────────────────────────────────────

    def _mark_reachable(self) -> Set[int]:
        """
        BFS-traverse the commit DAG from every branch HEAD.
        Returns the set of all reachable commit IDs.
        """
        reachable: Set[int] = set()
        queue: List[int] = []

        # Seed the BFS with every branch HEAD and every tagged commit
        for branch_name, branch_data in self.catalog.branches.items():
            head_id = branch_data.get("head_commit_id")
            if head_id is not None:
                queue.append(head_id)
        for tag in getattr(self.catalog, "tags", {}).values():
            queue.append(tag.get("commit_id"))

        while queue:
            commit_id = queue.pop(0)
            if commit_id is None or commit_id in reachable:
                continue

            reachable.add(commit_id)

            commit = self.catalog.commits.get(commit_id)
            if not commit:
                continue

            # Follow both parents (for merge commits)
            parent = commit.get("parent_id")
            if parent is not None:
                queue.append(parent)

            second_parent = commit.get("second_parent_id")
            if second_parent is not None:
                queue.append(second_parent)

        return reachable

    # ────────────────────────────────────────────────
    # Phase 2: SWEEP — Prune version chains & reclaim pages
    # ────────────────────────────────────────────────

    def _sweep(self, orphaned: Set[int]) -> Tuple[int, int]:
        """
        Remove orphaned versions from every version chain and release their
        storage.

        Delta-encoded versions point at a base snapshot. If a surviving delta's
        base is about to be reclaimed, the delta is first rewritten as a full
        snapshot ("rehydrated") so no live version loses its base.

        Returns (pages_reclaimed, entries_pruned).
        """
        import json as _json
        from ..storage.page import INVALID_PAGE_ID
        from ..storage.heap import is_packed_ref, read_packed
        from ..storage.delta import is_delta_page, decode_delta_page
        from ..storage.reader import read_row_data

        entries_pruned = 0
        doomed_pages: Set[int] = set()
        doomed_refs: Set[int] = set()
        new_chains: Dict[str, list] = {}

        keys = [f"{t}:{r}" for t, rows in self.catalog.tables.items() for r in rows]
        for key in keys:
            chain = self.btree.get_chain(key)
            if not chain:
                continue
            surviving = []
            for commit_id, ref in chain:
                if commit_id in orphaned:
                    entries_pruned += 1
                    if is_packed_ref(ref):
                        doomed_refs.add(ref)
                    elif ref != INVALID_PAGE_ID:
                        doomed_pages.add(ref)
                else:
                    surviving.append((commit_id, ref))
            if len(surviving) != len(chain):
                new_chains[key] = surviving

        def base_of(ref: int) -> Optional[int]:
            if is_packed_ref(ref):
                rec = read_packed(self.pool, ref)
                return rec[0] if rec else None
            page = self.pool.fetch_page(ref)
            if not page:
                return None
            try:
                if is_delta_page(page.data):
                    return decode_delta_page(page.data)[0]
                return None
            finally:
                self.pool.unpin_page(ref, is_dirty=False)

        # Rehydrate survivors whose base snapshot is being reclaimed
        if doomed_pages:
            for key in keys:
                chain = list(new_chains[key]) if key in new_chains else (self.btree.get_chain(key) or [])
                changed = False
                for i, (cid, ref) in enumerate(chain):
                    if ref == INVALID_PAGE_ID:
                        continue
                    b = base_of(ref)
                    if b is not None and b in doomed_pages:
                        data = read_row_data(self.pool, ref)
                        page = self.pool.new_page()
                        if not page or data is None:
                            raise RuntimeError("GC could not rehydrate a delta version")
                        raw = _json.dumps(data).encode("utf-8")
                        page.data[: len(raw)] = raw
                        self.pool.unpin_page(page.page_id, is_dirty=True)
                        if is_packed_ref(ref):
                            doomed_refs.add(ref)
                        else:
                            doomed_pages.add(ref)
                        chain[i] = (cid, page.page_id)
                        changed = True
                        self.versions_rehydrated += 1
                if changed:
                    new_chains[key] = chain

        for key, chain in new_chains.items():
            self.btree.set_chain(key, chain)

        pages_reclaimed = 0
        for pid in doomed_pages:
            if self.pool.delete_page(pid):
                pages_reclaimed += 1
        if self.heap is not None:
            for ref in doomed_refs:
                if self.heap.free(ref):
                    pages_reclaimed += 1

        return pages_reclaimed, entries_pruned
