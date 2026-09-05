/**
 * graphLayout.ts — DAG layout engine for the branch commit graph.
 *
 * Converts raw commits + branches into React Flow nodes and edges.
 * No external layout library required; positions are computed via
 * column-per-branch + row-per-topological-order.
 */

import type { Node, Edge } from "@xyflow/react";
import type { Commit, Branch } from "@/lib/api";

// ── Constants ──

const COLUMN_GAP = 220;
const ROW_GAP = 100;

// Curated palette — visually distinct on dark backgrounds
export const BRANCH_COLORS: string[] = [
  "#8b5cf6", // violet
  "#10b981", // emerald
  "#f59e0b", // amber
  "#f43f5e", // rose
  "#06b6d4", // cyan
  "#6366f1", // indigo
  "#84cc16", // lime
  "#d946ef", // fuchsia
  "#0ea5e9", // sky
  "#f97316", // orange
];

// ── Types ──

export interface CommitNodeData {
  commit: Commit;
  branchName: string;
  branchColor: string;
  isMerge: boolean;
  isHead: boolean;
  [key: string]: unknown;
}

export interface GraphLayout {
  nodes: Node[];
  edges: Edge[];
  branchColorMap: Map<string, string>;
}

// ── Layout function ──

export function computeGraphLayout(
  commits: Commit[],
  branches: Branch[]
): GraphLayout {
  if (commits.length === 0) {
    return { nodes: [], edges: [], branchColorMap: new Map() };
  }

  // 1. Build branch → color map
  const branchColorMap = new Map<string, string>();
  const branchNames = Array.from(new Set(branches.map((b) => b.name)));
  branchNames.forEach((name, i) => {
    branchColorMap.set(name, BRANCH_COLORS[i % BRANCH_COLORS.length]);
  });

  // Also add colors for any branch_id found on commits but not in branches list
  commits.forEach((c) => {
    const bid = String(c.branch_id);
    if (!branchColorMap.has(bid)) {
      branchColorMap.set(
        bid,
        BRANCH_COLORS[branchColorMap.size % BRANCH_COLORS.length]
      );
    }
  });

  // 2. Build branch → column index
  const branchColumns = new Map<string, number>();
  // "main" always gets column 0
  const sortedBranchNames = [...branchColorMap.keys()].sort((a, b) => {
    if (a === "main") return -1;
    if (b === "main") return 1;
    return a.localeCompare(b);
  });
  sortedBranchNames.forEach((name, i) => branchColumns.set(name, i));

  // 3. Build commit lookup and head set
  const commitById = new Map<number, Commit>();
  commits.forEach((c) => commitById.set(c.id, c));

  const headCommitIds = new Set<number>(branches.map((b) => b.head_commit_id));

  // 4. Sort commits topologically (ascending timestamp, then id)
  const sorted = [...commits].sort((a, b) => {
    const dt = a.timestamp - b.timestamp;
    return dt !== 0 ? dt : a.id - b.id;
  });

  // 5. Assign row indices
  const rowMap = new Map<number, number>();
  sorted.forEach((c, i) => rowMap.set(c.id, i));

  // 6. Generate nodes
  const nodes: Node[] = sorted.map((commit) => {
    const branchName = String(commit.branch_id);
    const col = branchColumns.get(branchName) ?? 0;
    const row = rowMap.get(commit.id) ?? 0;
    const isMerge = commit.second_parent_id !== null && commit.second_parent_id !== undefined;
    const isHead = headCommitIds.has(commit.id);

    return {
      id: String(commit.id),
      type: "commitNode",
      position: { x: col * COLUMN_GAP, y: row * ROW_GAP },
      data: {
        commit,
        branchName,
        branchColor: branchColorMap.get(branchName) ?? BRANCH_COLORS[0],
        isMerge,
        isHead,
      } as CommitNodeData,
    };
  });

  // 7. Generate edges
  const edges: Edge[] = [];

  sorted.forEach((commit) => {
    // Primary parent edge
    if (commit.parent_id !== null && commit.parent_id !== undefined) {
      if (commitById.has(commit.parent_id)) {
        const branchName = String(commit.branch_id);
        edges.push({
          id: `e-${commit.parent_id}-${commit.id}`,
          source: String(commit.parent_id),
          target: String(commit.id),
          type: "smoothstep",
          style: {
            stroke: branchColorMap.get(branchName) ?? BRANCH_COLORS[0],
            strokeWidth: 2,
          },
          animated: false,
        });
      }
    }

    // Second parent edge (merge)
    if (
      commit.second_parent_id !== null &&
      commit.second_parent_id !== undefined
    ) {
      if (commitById.has(commit.second_parent_id)) {
        const sourceBranch = commitById.get(commit.second_parent_id);
        const mergeColor = sourceBranch
          ? branchColorMap.get(String(sourceBranch.branch_id)) ?? BRANCH_COLORS[1]
          : BRANCH_COLORS[1];
        edges.push({
          id: `e-merge-${commit.second_parent_id}-${commit.id}`,
          source: String(commit.second_parent_id),
          target: String(commit.id),
          type: "smoothstep",
          style: {
            stroke: mergeColor,
            strokeWidth: 2,
            strokeDasharray: "6 3",
            opacity: 0.7,
          },
          animated: true,
          label: "merge",
          labelStyle: {
            fontSize: 9,
            fill: mergeColor,
            fontWeight: 600,
          },
          labelBgStyle: {
            fill: "#18181b",
            fillOpacity: 0.8,
          },
        });
      }
    }
  });

  return { nodes, edges, branchColorMap };
}
