"use client";

import { useState } from "react";
import { Commit } from "@/lib/api";
import { rollbackToCommit } from "@/lib/api";
import ErrorState from "./ErrorState";

interface CommitHistoryProps {
  commits: Commit[];
  loading: boolean;
  error: string | null;
  branchName: string;
  onRollback: () => void;
  onRetry: () => void;
}

function timeAgo(timestamp: number): string {
  const seconds = Math.floor(Date.now() / 1000 - timestamp);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function CommitHistory({
  commits,
  loading,
  error,
  branchName,
  onRollback,
  onRetry,
}: CommitHistoryProps) {
  const [rollingBack, setRollingBack] = useState<string | null>(null);
  const [confirmHash, setConfirmHash] = useState<string | null>(null);
  const [rollbackError, setRollbackError] = useState<string | null>(null);

  async function handleRollback(hash: string) {
    setRollingBack(hash);
    setRollbackError(null);
    try {
      await rollbackToCommit(hash, branchName, "dashboard-user");
      onRollback();
      setConfirmHash(null);
    } catch (err) {
      setRollbackError(
        err instanceof Error ? err.message : "Rollback failed"
      );
    } finally {
      setRollingBack(null);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-700/40 bg-zinc-900/50 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-700/40 px-4 py-3">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-violet-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
          </svg>
          <h2 className="text-sm font-semibold text-zinc-200">
            Commit History
          </h2>
        </div>
        <span className="text-[10px] text-zinc-600">
          {commits.length} commit{commits.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="p-4">
            <ErrorState message={error} onRetry={onRetry} />
          </div>
        )}

        {loading && !error && (
          <div className="space-y-3 p-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="animate-pulse space-y-2">
                <div className="h-3 w-24 rounded bg-zinc-700/50" />
                <div className="h-4 w-full rounded bg-zinc-700/30" />
                <div className="h-3 w-16 rounded bg-zinc-700/30" />
              </div>
            ))}
          </div>
        )}

        {!loading && !error && commits.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <p className="text-sm text-zinc-500">No commits yet</p>
            <p className="text-xs text-zinc-600">
              Create your first commit to see history
            </p>
          </div>
        )}

        {!loading && !error && commits.length > 0 && (
          <div className="relative p-4">
            {/* Timeline line */}
            <div className="absolute bottom-0 left-[29px] top-4 w-px bg-gradient-to-b from-violet-500/30 via-zinc-700/30 to-transparent" />

            <div className="space-y-1">
              {commits.map((commit, idx) => {
                const isFirst = idx === 0;
                const isInitial = commit.message === "Initial commit" || commit.parent_id === null;

                return (
                  <div key={commit.id} className="group relative flex gap-3 rounded-lg p-2 transition-colors hover:bg-zinc-800/30">
                    {/* Timeline dot */}
                    <div className="relative z-10 mt-1.5 flex-shrink-0">
                      <div
                        className={`h-3 w-3 rounded-full border-2 transition-colors ${
                          isFirst
                            ? "border-violet-400 bg-violet-500 shadow-sm shadow-violet-500/50"
                            : "border-zinc-600 bg-zinc-800 group-hover:border-zinc-500"
                        }`}
                      />
                    </div>

                    {/* Commit info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <p className="truncate text-sm font-medium text-zinc-200">
                          {commit.message}
                        </p>
                        {!isInitial && !isFirst && (
                          <>
                            {confirmHash === commit.hash ? (
                              <div className="flex flex-shrink-0 items-center gap-1">
                                <button
                                  onClick={() => handleRollback(commit.hash)}
                                  disabled={rollingBack === commit.hash}
                                  className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-400 transition-all hover:bg-amber-500/30 active:scale-95"
                                >
                                  {rollingBack === commit.hash
                                    ? "…"
                                    : "Confirm"}
                                </button>
                                <button
                                  onClick={() => setConfirmHash(null)}
                                  className="rounded px-1.5 py-0.5 text-[10px] text-zinc-500 hover:text-zinc-300"
                                >
                                  ✕
                                </button>
                              </div>
                            ) : (
                              <button
                                onClick={() => {
                                  setConfirmHash(commit.hash);
                                  setRollbackError(null);
                                }}
                                className="flex-shrink-0 rounded bg-zinc-800/50 px-2 py-0.5 text-[10px] text-zinc-500 opacity-0 transition-all hover:bg-zinc-700/50 hover:text-zinc-300 group-hover:opacity-100"
                              >
                                Rollback
                              </button>
                            )}
                          </>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-zinc-500">
                        <span className="font-mono text-violet-400/60">
                          {commit.hash.slice(0, 8)}
                        </span>
                        <span>·</span>
                        <span>{commit.author}</span>
                        <span>·</span>
                        <span>{timeAgo(commit.timestamp)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {rollbackError && (
          <div className="px-4 pb-4">
            <p className="text-xs text-red-400">{rollbackError}</p>
          </div>
        )}
      </div>
    </div>
  );
}
