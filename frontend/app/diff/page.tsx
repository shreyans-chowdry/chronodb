"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Branch,
  Commit,
  DiffResult,
  MergeResponse,
  fetchBranches,
  fetchCommits,
  fetchDiff,
  executeMerge,
} from "@/lib/api";
import DiffViewer from "@/components/DiffViewer";
import MergePanel from "@/components/MergePanel";

type ViewMode = "diff" | "merge";

export default function DiffPage() {
  // Branch & commit state
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchA, setBranchA] = useState("");
  const [branchB, setBranchB] = useState("");
  const [commitsA, setCommitsA] = useState<Commit[]>([]);
  const [commitsB, setCommitsB] = useState<Commit[]>([]);
  const [commitA, setCommitA] = useState("");
  const [commitB, setCommitB] = useState("");

  // Diff / Merge state
  const [diffResult, setDiffResult] = useState<DiffResult | null>(null);
  const [mergeResult, setMergeResult] = useState<MergeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("diff");
  const [mergeSuccess, setMergeSuccess] = useState<MergeResponse | null>(null);

  // Load branches on mount
  useEffect(() => {
    fetchBranches()
      .then((b) => {
        setBranches(b);
        if (b.length >= 2) {
          setBranchA(b[0].name);
          setBranchB(b[1].name);
        } else if (b.length === 1) {
          setBranchA(b[0].name);
          setBranchB(b[0].name);
        }
      })
      .catch(() => {});
  }, []);

  // Load commits when branch changes
  useEffect(() => {
    if (branchA) {
      fetchCommits(branchA).then(setCommitsA).catch(() => setCommitsA([]));
    }
  }, [branchA]);

  useEffect(() => {
    if (branchB) {
      fetchCommits(branchB).then(setCommitsB).catch(() => setCommitsB([]));
    }
  }, [branchB]);

  // Auto-select HEAD commits
  useEffect(() => {
    if (commitsA.length > 0 && !commitA) setCommitA(commitsA[0].hash);
  }, [commitsA, commitA]);

  useEffect(() => {
    if (commitsB.length > 0 && !commitB) setCommitB(commitsB[0].hash);
  }, [commitsB, commitB]);

  const handleCompare = useCallback(async () => {
    if (!commitA || !commitB) return;
    setLoading(true);
    setError(null);
    setDiffResult(null);
    setMergeResult(null);
    setMergeSuccess(null);
    try {
      const result = await fetchDiff(commitA, commitB);
      setDiffResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load diff");
    } finally {
      setLoading(false);
    }
  }, [commitA, commitB]);

  const handleMergePreview = useCallback(async () => {
    if (!branchA || !branchB || branchA === branchB) return;
    setLoading(true);
    setError(null);
    setMergeResult(null);
    setMergeSuccess(null);
    setViewMode("merge");
    try {
      // First, try a dry merge (no resolutions) to detect conflicts
      const result = await executeMerge(branchA, branchB, "dashboard-user");
      if (result.status === "ok") {
        // No conflicts, merge succeeded immediately
        setMergeSuccess(result);
        setMergeResult(null);
        // Also fetch the diff for visual feedback
        if (commitA && commitB) {
          const diffData = await fetchDiff(commitA, commitB);
          setDiffResult(diffData);
        }
      } else {
        // Conflicts detected — show resolution UI
        setMergeResult(result);
        // Also load the diff
        if (commitA && commitB) {
          const diffData = await fetchDiff(commitA, commitB);
          setDiffResult(diffData);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setLoading(false);
    }
  }, [branchA, branchB, commitA, commitB]);

  const handleMergeComplete = (result: MergeResponse) => {
    if (result.status === "ok") {
      setMergeSuccess(result);
      setMergeResult(null);
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-30 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center justify-between px-4 sm:px-6">
          {/* Logo + Back */}
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-2 rounded-lg px-2 py-1 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
              </svg>
              <span className="text-xs font-medium">Dashboard</span>
            </Link>
            <div className="h-5 w-px bg-zinc-700/40" />
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/20">
              <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-zinc-100">
                Diff & Merge
              </h1>
              <p className="text-[10px] text-zinc-500">
                Compare commits · Resolve conflicts
              </p>
            </div>
          </div>

          {/* Mode toggle */}
          <div className="flex rounded-lg border border-zinc-700/40 bg-zinc-800/50 p-0.5">
            <button
              onClick={() => setViewMode("diff")}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                viewMode === "diff"
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Diff View
            </button>
            <button
              onClick={() => setViewMode("merge")}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                viewMode === "merge"
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Merge
            </button>
          </div>
        </div>
      </header>

      {/* ── Main content ── */}
      <main className="mx-auto w-full max-w-[1600px] flex-1 p-4 sm:p-6">
        {/* Commit selector */}
        <div className="mb-6 overflow-hidden rounded-xl border border-zinc-700/40 bg-zinc-900/50 backdrop-blur-sm animate-slide-up">
          <div className="border-b border-zinc-700/40 px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-200">
              {viewMode === "diff" ? "Select Commits to Compare" : "Select Branches to Merge"}
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
            {/* Left side (A / target) */}
            <div className="space-y-2">
              <label className="block text-[11px] font-medium text-zinc-400">
                {viewMode === "diff" ? "Before (A)" : "Target Branch (ours)"}
              </label>
              <select
                value={branchA}
                onChange={(e) => {
                  setBranchA(e.target.value);
                  setCommitA("");
                }}
                className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-violet-500/50"
              >
                {branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
              {viewMode === "diff" && (
                <select
                  value={commitA}
                  onChange={(e) => setCommitA(e.target.value)}
                  className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-violet-500/50"
                >
                  {commitsA.map((c) => (
                    <option key={c.hash} value={c.hash}>
                      {c.hash.slice(0, 8)} — {c.message}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Right side (B / source) */}
            <div className="space-y-2">
              <label className="block text-[11px] font-medium text-zinc-400">
                {viewMode === "diff" ? "After (B)" : "Source Branch (theirs)"}
              </label>
              <select
                value={branchB}
                onChange={(e) => {
                  setBranchB(e.target.value);
                  setCommitB("");
                }}
                className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-violet-500/50"
              >
                {branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
              {viewMode === "diff" && (
                <select
                  value={commitB}
                  onChange={(e) => setCommitB(e.target.value)}
                  className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-violet-500/50"
                >
                  {commitsB.map((c) => (
                    <option key={c.hash} value={c.hash}>
                      {c.hash.slice(0, 8)} — {c.message}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 border-t border-zinc-700/40 px-4 py-3">
            {viewMode === "diff" ? (
              <button
                onClick={handleCompare}
                disabled={!commitA || !commitB || loading}
                className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:from-violet-500 hover:to-indigo-500 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    Comparing…
                  </>
                ) : (
                  <>
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
                    </svg>
                    Compare Commits
                  </>
                )}
              </button>
            ) : (
              <button
                onClick={handleMergePreview}
                disabled={!branchA || !branchB || branchA === branchB || loading}
                className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:from-violet-500 hover:to-indigo-500 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    Analyzing…
                  </>
                ) : (
                  <>
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                    </svg>
                    Start Merge
                  </>
                )}
              </button>
            )}

            {viewMode === "merge" && branchA === branchB && (
              <p className="text-[11px] text-amber-400">
                Select two different branches to merge
              </p>
            )}
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 p-4 animate-fade-in">
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4 text-red-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
              </svg>
              <p className="text-sm text-red-300">{error}</p>
            </div>
          </div>
        )}

        {/* Merge success banner */}
        {mergeSuccess && mergeSuccess.status === "ok" && (
          <div className="mb-6 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 animate-fade-in">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/20">
                <svg className="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-emerald-300">Merge Successful!</p>
                <p className="text-xs text-emerald-400/70">
                  Merged <span className="font-semibold">{branchB}</span> into{" "}
                  <span className="font-semibold">{branchA}</span>
                  {mergeSuccess.commit && (
                    <> · Commit <span className="font-mono">{mergeSuccess.commit.hash.slice(0, 8)}</span></>
                  )}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Diff result */}
        {diffResult && viewMode === "diff" && (
          <DiffViewer diffData={diffResult} commitA={commitA} commitB={commitB} />
        )}

        {/* Merge conflict panel */}
        {mergeResult && mergeResult.status === "conflict" && mergeResult.conflicts && (
          <div className="space-y-6">
            {/* Show the diff too for context */}
            {diffResult && (
              <DiffViewer diffData={diffResult} commitA={commitA} commitB={commitB} />
            )}

            {/* Conflict resolution */}
            <MergePanel
              targetBranch={branchA}
              sourceBranch={branchB}
              conflicts={mergeResult.conflicts}
              onMergeComplete={handleMergeComplete}
            />
          </div>
        )}

        {/* Empty state */}
        {!loading && !diffResult && !mergeResult && !mergeSuccess && !error && (
          <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-zinc-700/40 bg-zinc-900/50 p-16 text-center backdrop-blur-sm animate-fade-in">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20">
              <svg className="h-8 w-8 text-violet-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-300">
                {viewMode === "diff"
                  ? "Select two commits and click Compare"
                  : "Select two branches and click Start Merge"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {viewMode === "diff"
                  ? "View changes side-by-side with highlighted additions, deletions, and modifications"
                  : "Three-way merge with automatic conflict detection and resolution"}
              </p>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800/40 py-3 text-center text-[10px] text-zinc-600">
        ChronoDB · Diff & Merge Viewer · Built with Next.js + FastAPI
      </footer>
    </div>
  );
}
