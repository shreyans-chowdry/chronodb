"""
ChronoDB — Three-Way Merge Algorithm

Implements a Git-style three-way merge for the version-controlled database:
  1. Find the Lowest Common Ancestor (LCA) of two branch HEADs
  2. Compute row/cell-level diffs of each branch against the LCA
  3. Auto-merge non-conflicting changes
  4. Detect and report conflicts when both branches modified the same row differently
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from ..storage.buffer_pool import BufferPoolManager
from ..storage.page import INVALID_PAGE_ID, PAGE_SIZE
from ..storage.reader import read_row_data
from ..index.btree import BTreeIndex
from ..version.catalog import SystemCatalog


# ── Diff Types ──

class RowDiff:
    """Represents a single row's diff against the ancestor."""
    __slots__ = ("table_name", "row_id", "action", "ancestor_data", "branch_data")

    def __init__(
        self,
        table_name: str,
        row_id: str,
        action: str,  # "added", "deleted", "modified"
        ancestor_data: Optional[Dict[str, Any]],
        branch_data: Optional[Dict[str, Any]],
    ):
        self.table_name = table_name
        self.row_id = row_id
        self.action = action
        self.ancestor_data = ancestor_data
        self.branch_data = branch_data


class ConflictEntry:
    """Represents a merge conflict on a single row."""
    __slots__ = (
        "table_name", "row_id",
        "ancestor_data", "source_data", "target_data",
        "conflicting_cells", "conflict_type",
    )

    def __init__(
        self,
        table_name: str,
        row_id: str,
        ancestor_data: Optional[Dict[str, Any]],
        source_data: Optional[Dict[str, Any]],
        target_data: Optional[Dict[str, Any]],
        conflicting_cells: List[str],
        conflict_type: str,  # "modify_modify", "delete_modify", "modify_delete", "add_add"
    ):
        self.table_name = table_name
        self.row_id = row_id
        self.ancestor_data = ancestor_data
        self.source_data = source_data
        self.target_data = target_data
        self.conflicting_cells = conflicting_cells
        self.conflict_type = conflict_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "row_id": self.row_id,
            "ancestor_data": self.ancestor_data,
            "source_data": self.source_data,
            "target_data": self.target_data,
            "conflicting_cells": self.conflicting_cells,
            "conflict_type": self.conflict_type,
        }


# ── Three-Way Merge Engine ──

class ThreeWayMerge:
    """
    Three-way merge algorithm for ChronoDB.

    Given a source branch and a target branch:
      1. Finds their Lowest Common Ancestor (LCA)
      2. Computes row-level and cell-level diffs for each branch vs LCA
      3. Auto-merges non-conflicting changes into a new merge commit
      4. Returns structured conflicts if both branches modified the same row
    """

    def __init__(
        self,
        catalog: SystemCatalog,
        btree: BTreeIndex,
        pool: BufferPoolManager,
    ):
        self.catalog = catalog
        self.btree = btree
        self.pool = pool

    # ────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────

    def merge(
        self,
        source_branch: str,
        target_branch: str,
        author: str,
        resolutions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Perform a three-way merge of source_branch into target_branch.

        Returns:
          - On success: {"merged": True, "commit": <commit_dict>}
          - On conflict: {"merged": False, "conflicting_rows": [...]}

        Raises:
          ValueError: If either branch doesn't exist or no LCA is found.
        """
        # Validate branches
        source = self.catalog.get_branch(source_branch)
        if source is None:
            raise ValueError(f"Source branch '{source_branch}' does not exist")

        target = self.catalog.get_branch(target_branch)
        if target is None:
            raise ValueError(f"Target branch '{target_branch}' does not exist")

        source_head = source["head_commit_id"]
        target_head = target["head_commit_id"]

        # Fast-forward: if target HEAD is an ancestor of source HEAD,
        # we can just move the target pointer forward
        if self.catalog.is_ancestor(target_head, source_head):
            # Fast-forward: target is behind source — just move the pointer
            self.catalog.update_branch_head(target_branch, source_head)
            commit = self.catalog.get_commit(source_head)
            return {"merged": True, "commit": commit, "strategy": "fast-forward"}

        # Find LCA
        lca_id = self.catalog.find_lca(source_head, target_head)
        if lca_id is None:
            raise ValueError(
                f"No common ancestor found between '{source_branch}' and '{target_branch}'"
            )

        # Compute diffs
        source_diffs = self._compute_diffs(lca_id, source_head)
        target_diffs = self._compute_diffs(lca_id, target_head)

        # Detect conflicts and build merged changes
        conflicts, merged_changes = self._reconcile(
            source_diffs, target_diffs, lca_id, source_head, target_head, resolutions
        )

        if conflicts:
            return {
                "merged": False,
                "conflicting_rows": [c.to_dict() for c in conflicts],
            }

        # No conflicts — create the merge commit
        # The merge commit is applied to target_branch with second_parent = source_head
        return {
            "merged": True,
            "changes": merged_changes,
            "source_head": source_head,
            "target_head": target_head,
            "author": author,
            "message": f"Merge branch '{source_branch}' into '{target_branch}'",
        }

    # ────────────────────────────────────────────────
    # Diff computation
    # ────────────────────────────────────────────────

    def _compute_diffs(
        self, ancestor_commit_id: int, branch_commit_id: int
    ) -> Dict[Tuple[str, str], RowDiff]:
        """
        Compute row-level diffs between the ancestor commit and a branch HEAD.

        Returns a dict keyed by (table_name, row_id) → RowDiff.
        Only rows that changed are included.
        """
        diffs: Dict[Tuple[str, str], RowDiff] = {}

        for table_name, row_ids in self.catalog.tables.items():
            for row_id in row_ids:
                ancestor_data = self._resolve_row_data(table_name, row_id, ancestor_commit_id)
                branch_data = self._resolve_row_data(table_name, row_id, branch_commit_id)

                # Skip rows that haven't changed
                if ancestor_data == branch_data:
                    continue

                key = (table_name, row_id)

                if ancestor_data is None and branch_data is not None:
                    diffs[key] = RowDiff(table_name, row_id, "added", None, branch_data)
                elif ancestor_data is not None and branch_data is None:
                    diffs[key] = RowDiff(table_name, row_id, "deleted", ancestor_data, None)
                else:
                    diffs[key] = RowDiff(table_name, row_id, "modified", ancestor_data, branch_data)

        return diffs

    # ────────────────────────────────────────────────
    # Conflict detection & reconciliation
    # ────────────────────────────────────────────────

    def _reconcile(
        self,
        source_diffs: Dict[Tuple[str, str], RowDiff],
        target_diffs: Dict[Tuple[str, str], RowDiff],
        lca_id: int,
        source_head: int,
        target_head: int,
        resolutions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[List[ConflictEntry], List[Dict[str, Any]]]:
        """
        Reconcile diffs from both branches.

        Returns:
          - conflicts: list of ConflictEntry for rows that conflict
          - merged_changes: list of change dicts ready for the commit() method
        """
        conflicts: List[ConflictEntry] = []
        merged_changes: List[Dict[str, Any]] = []

        # All keys that changed on either branch
        all_keys = set(source_diffs.keys()) | set(target_diffs.keys())

        for key in all_keys:
            table_name, row_id = key
            res_key = f"{table_name}:{row_id}"

            # Apply manual resolution if provided
            if resolutions and res_key in resolutions:
                res_data = resolutions[res_key]
                if res_data is None:
                    merged_changes.append({"action": "delete", "table_name": table_name, "row_id": row_id, "data": None})
                else:
                    # 'insert' or 'update' doesn't matter much for engine.commit(), it handles both similarly
                    merged_changes.append({"action": "update", "table_name": table_name, "row_id": row_id, "data": res_data})
                continue

            s_diff = source_diffs.get(key)
            t_diff = target_diffs.get(key)

            if s_diff and not t_diff:
                # Only source changed this row — take source's version
                merged_changes.append(self._diff_to_change(s_diff))

            elif t_diff and not s_diff:
                # Only target changed this row — take target's version
                # (These changes are already on the target branch, but we
                # need them in the merge commit to maintain the version chain.)
                # Actually, since these are already on target, we don't need
                # to re-apply them. The merge commit only needs source changes
                # that target doesn't have.
                pass  # target changes are already on the target branch

            else:
                # Both branches changed the same row
                assert s_diff is not None and t_diff is not None

                # Check if both made identical changes
                if s_diff.branch_data == t_diff.branch_data:
                    # Identical change — no conflict, no need to re-apply
                    # (target already has it)
                    pass

                elif s_diff.action == "deleted" and t_diff.action == "deleted":
                    # Both deleted — no conflict (already deleted on target)
                    pass

                elif s_diff.action == "deleted" and t_diff.action in ("modified", "added"):
                    # Source deleted, target modified — CONFLICT
                    conflicts.append(ConflictEntry(
                        table_name=table_name,
                        row_id=row_id,
                        ancestor_data=s_diff.ancestor_data,
                        source_data=None,
                        target_data=t_diff.branch_data,
                        conflicting_cells=[],
                        conflict_type="delete_modify",
                    ))

                elif s_diff.action in ("modified", "added") and t_diff.action == "deleted":
                    # Source modified, target deleted — CONFLICT
                    conflicts.append(ConflictEntry(
                        table_name=table_name,
                        row_id=row_id,
                        ancestor_data=t_diff.ancestor_data,
                        source_data=s_diff.branch_data,
                        target_data=None,
                        conflicting_cells=[],
                        conflict_type="modify_delete",
                    ))

                elif s_diff.action == "added" and t_diff.action == "added":
                    # Both added the same row_id with different data — CONFLICT
                    conflicting_cells = self._find_conflicting_cells(
                        s_diff.branch_data or {}, t_diff.branch_data or {}
                    )
                    conflicts.append(ConflictEntry(
                        table_name=table_name,
                        row_id=row_id,
                        ancestor_data=None,
                        source_data=s_diff.branch_data,
                        target_data=t_diff.branch_data,
                        conflicting_cells=conflicting_cells,
                        conflict_type="add_add",
                    ))

                else:
                    # Both modified — do cell-level merge
                    conflict = self._cell_level_merge(
                        table_name, row_id,
                        s_diff.ancestor_data or {},
                        s_diff.branch_data or {},
                        t_diff.branch_data or {},
                    )
                    if conflict is not None:
                        conflicts.append(conflict)
                    else:
                        # Cell-level auto-merge succeeded — apply the merged result
                        merged_data = self._auto_merge_cells(
                            s_diff.ancestor_data or {},
                            s_diff.branch_data or {},
                            t_diff.branch_data or {},
                        )
                        merged_changes.append({
                            "action": "update",
                            "table_name": table_name,
                            "row_id": row_id,
                            "data": merged_data,
                        })

        return conflicts, merged_changes

    def _cell_level_merge(
        self,
        table_name: str,
        row_id: str,
        ancestor: Dict[str, Any],
        source: Dict[str, Any],
        target: Dict[str, Any],
    ) -> Optional[ConflictEntry]:
        """
        Attempt cell-level merge. Returns a ConflictEntry if conflicting cells
        are found, or None if auto-merge is possible.
        """
        all_keys = set(ancestor.keys()) | set(source.keys()) | set(target.keys())
        conflicting_cells = []

        for cell_key in all_keys:
            ancestor_val = ancestor.get(cell_key)
            source_val = source.get(cell_key)
            target_val = target.get(cell_key)

            source_changed = (source_val != ancestor_val)
            target_changed = (target_val != ancestor_val)

            if source_changed and target_changed and source_val != target_val:
                conflicting_cells.append(cell_key)

        if conflicting_cells:
            return ConflictEntry(
                table_name=table_name,
                row_id=row_id,
                ancestor_data=ancestor,
                source_data=source,
                target_data=target,
                conflicting_cells=sorted(conflicting_cells),
                conflict_type="modify_modify",
            )

        return None

    def _auto_merge_cells(
        self,
        ancestor: Dict[str, Any],
        source: Dict[str, Any],
        target: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Auto-merge non-conflicting cell-level changes from both branches.
        
        For each cell:
          - If only source changed it → take source's value
          - If only target changed it → take target's value
          - If neither changed it → keep ancestor's value
          - If both changed to the same value → take that value
        """
        all_keys = set(ancestor.keys()) | set(source.keys()) | set(target.keys())
        merged = {}

        for cell_key in all_keys:
            ancestor_val = ancestor.get(cell_key)
            source_val = source.get(cell_key)
            target_val = target.get(cell_key)

            source_changed = (source_val != ancestor_val)
            target_changed = (target_val != ancestor_val)

            if source_changed and not target_changed:
                merged[cell_key] = source_val
            elif target_changed and not source_changed:
                merged[cell_key] = target_val
            elif source_changed and target_changed:
                # Both changed to the same value (conflicts caught earlier)
                merged[cell_key] = source_val
            else:
                # Neither changed
                merged[cell_key] = ancestor_val

        # Remove keys whose value is None (deleted cells)
        return {k: v for k, v in merged.items() if v is not None}

    # ────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────

    def _resolve_row_data(
        self, table_name: str, row_id: str, commit_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve a single row's data at a specific commit.
        Returns None if the row doesn't exist or is deleted at that commit.
        """
        key = f"{table_name}:{row_id}"
        page_version_id = self.btree.resolve_version(
            key, commit_id, self.catalog.is_ancestor
        )

        if page_version_id is None or page_version_id == INVALID_PAGE_ID:
            return None

        return read_row_data(self.pool, page_version_id)

    def _diff_to_change(self, diff: RowDiff) -> Dict[str, Any]:
        """Convert a RowDiff into a change dict compatible with engine.commit()."""
        if diff.action == "deleted":
            return {
                "action": "delete",
                "table_name": diff.table_name,
                "row_id": diff.row_id,
                "data": None,
            }
        else:
            return {
                "action": "update" if diff.action == "modified" else "insert",
                "table_name": diff.table_name,
                "row_id": diff.row_id,
                "data": diff.branch_data,
            }

    @staticmethod
    def _find_conflicting_cells(
        data_a: Dict[str, Any], data_b: Dict[str, Any]
    ) -> List[str]:
        """Find cells that differ between two row data dicts."""
        all_keys = set(data_a.keys()) | set(data_b.keys())
        return sorted(k for k in all_keys if data_a.get(k) != data_b.get(k))
