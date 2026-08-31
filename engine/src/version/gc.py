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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reachable_commits": self.reachable_commits,
            "orphaned_commits": self.orphaned_commits,
            "pages_reclaimed": self.pages_reclaimed,
            "version_entries_pruned": self.version_entries_pruned,
            "commits_removed": self.commits_removed,
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

    def __init__(self, catalog: Any, btree: Any, pool: Any):
        self.catalog = catalog
        self.btree = btree
        self.pool = pool

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

        # Seed the BFS with every branch HEAD
        for branch_name, branch_data in self.catalog.branches.items():
            head_id = branch_data.get("head_commit_id")
            if head_id is not None:
                queue.append(head_id)

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
        Walk every key's version chain in the B+ Tree.
        Remove entries whose commit_id is in the orphaned set.
        Deallocate the page versions from those entries.

        Returns (pages_reclaimed, entries_pruned).
        """
        from ..storage.page import INVALID_PAGE_ID

        pages_reclaimed = 0
        entries_pruned = 0
        pages_to_reclaim: Set[int] = set()

        for table_name, row_ids in list(self.catalog.tables.items()):
            for row_id in row_ids:
                key = f"{table_name}:{row_id}"
                leaf = self.btree.find_leaf(key)

                if key not in leaf.entries:
                    self.btree._unpin_node_clean(leaf.page_id)
                    continue

                version_chain = leaf.entries[key]
                original_len = len(version_chain)

                # Separate: keep reachable versions, collect orphaned page_ids
                surviving = []
                for commit_id, page_version_id in version_chain:
                    if commit_id in orphaned:
                        # Mark page for reclamation
                        if page_version_id != INVALID_PAGE_ID:
                            pages_to_reclaim.add(page_version_id)
                        entries_pruned += 1
                    else:
                        surviving.append((commit_id, page_version_id))

                if len(surviving) != original_len:
                    # Version chain was modified — update it
                    leaf.entries[key] = surviving
                    self.btree._save_node(leaf)
                else:
                    self.btree._unpin_node_clean(leaf.page_id)

        # Reclaim disk pages
        for page_id in pages_to_reclaim:
            self.pool.delete_page(page_id)
            pages_reclaimed += 1

        # Flush to ensure everything is persisted
        self.pool.flush_all_pages()

        return pages_reclaimed, entries_pruned
