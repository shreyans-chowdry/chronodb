"use client";

import React, { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type NodeTypes,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useCommitGraph } from "@/hooks/useChronoDB";
import { computeGraphLayout, BRANCH_COLORS } from "@/lib/graphLayout";
import CommitNode from "./CommitNode";
import ErrorState from "../ErrorState";

// Register custom node types (stable reference)
const nodeTypes: NodeTypes = {
  commitNode: CommitNode,
};

export default function BranchGraph() {
  const { data, loading, error, refetch } = useCommitGraph();

  const layout = useMemo(() => {
    if (!data) return null;
    return computeGraphLayout(data.commits, data.branches);
  }, [data]);

  const minimapNodeColor = useCallback(
    (node: { data?: { branchColor?: string } }) => {
      return (node.data?.branchColor as string) ?? "#8b5cf6";
    },
    []
  );

  // Loading state
  if (loading && !data) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="relative h-12 w-12">
            <div className="absolute inset-0 rounded-full border-2 border-zinc-700/40" />
            <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-violet-500" />
          </div>
          <p className="text-sm text-zinc-400">Loading commit graph…</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <ErrorState message={error} onRetry={refetch} />
      </div>
    );
  }

  // Empty state
  if (!layout || layout.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20">
          <svg className="h-8 w-8 text-violet-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6Z" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-medium text-zinc-300">No commits to display</p>
          <p className="mt-1 text-xs text-zinc-500">
            Create some commits across branches to see the graph
          </p>
        </div>
      </div>
    );
  }

  // Build branch legend data
  const branchLegend = Array.from(layout.branchColorMap.entries());

  return (
    <div className="branch-graph-container relative h-full w-full">
      {/* Branch legend */}
      <div className="branch-graph-legend" id="branch-legend">
        <div className="branch-graph-legend-title">
          <svg className="h-3.5 w-3.5 text-violet-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6Z" />
          </svg>
          Branches
        </div>
        {branchLegend.map(([name, color]) => (
          <div key={name} className="branch-graph-legend-item">
            <div
              className="branch-graph-legend-dot"
              style={{ background: color }}
            />
            <span className="branch-graph-legend-name">{name}</span>
          </div>
        ))}
      </div>

      {/* Stats badge */}
      <div className="branch-graph-stats" id="graph-stats">
        {layout.nodes.length} commits · {branchLegend.length} branches
      </div>

      {/* React Flow canvas */}
      <ReactFlow
        nodes={layout.nodes}
        edges={layout.edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.05}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnDrag={true}
        zoomOnScroll={true}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          type: "smoothstep",
          animated: false,
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#27272a"
        />
        <Controls
          showInteractive={false}
          className="branch-graph-controls"
        />
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor="rgba(0, 0, 0, 0.7)"
          className="branch-graph-minimap"
          pannable
          zoomable
        />
      </ReactFlow>
    </div>
  );
}
