"use client";

import React, { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useRouter } from "next/navigation";
import type { CommitNodeData } from "@/lib/graphLayout";
import type { Node } from "@xyflow/react";

type CommitNodeType = Node<CommitNodeData, "commitNode">;

function formatTimestamp(ts: number): string {
  const date = new Date(ts * 1000);
  const month = date.toLocaleString("en", { month: "short" });
  const day = date.getDate();
  const hours = date.getHours().toString().padStart(2, "0");
  const mins = date.getMinutes().toString().padStart(2, "0");
  return `${month} ${day}, ${hours}:${mins}`;
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max - 1) + "…" : str;
}

function CommitNodeComponent({ data }: NodeProps<CommitNodeType>) {
  const router = useRouter();
  const { commit, branchName, branchColor, isMerge, isHead } =
    data as CommitNodeData;

  const handleClick = useCallback(() => {
    if (commit.parent_id !== null && commit.parent_id !== undefined) {
      // Navigate to diff page — we need to find the parent's hash
      // For now, we use the commit hash and parent_id (the diff page expects hashes)
      // Since we have the hash of the current commit, we'll pass both
      router.push(
        `/diff?from_graph=1&commit_b=${encodeURIComponent(commit.hash)}`
      );
    }
  }, [commit, router]);

  return (
    <div
      id={`commit-node-${commit.id}`}
      className="commit-node-wrapper"
      onClick={handleClick}
      style={{ cursor: commit.parent_id ? "pointer" : "default" }}
    >
      {/* Target handle (top — receives edges from parents) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-transparent !border-0 !w-3 !h-3"
        style={{ top: -2 }}
        isConnectable={false}
      />

      {/* Node card */}
      <div
        className="commit-node-card"
        style={
          {
            "--branch-color": branchColor,
          } as React.CSSProperties
        }
      >
        {/* Branch color indicator + HEAD badge */}
        <div className="commit-node-header">
          <div className="commit-node-branch-dot" style={{ background: branchColor }} />
          <span className="commit-node-branch-label" style={{ color: branchColor }}>
            {branchName}
          </span>
          {isHead && <span className="commit-node-head-badge">HEAD</span>}
          {isMerge && (
            <span className="commit-node-merge-badge">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
              merge
            </span>
          )}
        </div>

        {/* Commit message */}
        <p className="commit-node-message">{truncate(commit.message, 40)}</p>

        {/* Meta row */}
        <div className="commit-node-meta">
          <span className="commit-node-hash">{commit.hash.slice(0, 8)}</span>
          <span className="commit-node-separator">·</span>
          <span className="commit-node-author">{commit.author}</span>
          <span className="commit-node-separator">·</span>
          <span className="commit-node-time">{formatTimestamp(commit.timestamp)}</span>
        </div>
      </div>

      {/* Source handle (bottom — sends edges to children) */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-transparent !border-0 !w-3 !h-3"
        style={{ bottom: -2 }}
        isConnectable={false}
      />
    </div>
  );
}

const CommitNode = memo(CommitNodeComponent);
CommitNode.displayName = "CommitNode";

export default CommitNode;
