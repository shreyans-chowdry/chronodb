"use client";

import { useState, useCallback } from "react";
import { useBranches, useCommits } from "@/hooks/useChronoDB";

import BranchSwitcher from "@/components/BranchSwitcher";
import TableViewer from "@/components/TableViewer";
import CommitPanel from "@/components/CommitPanel";
import CommitHistory from "@/components/CommitHistory";
import DarkModeToggle from "@/components/DarkModeToggle";
import ErrorState from "@/components/ErrorState";

export default function DashboardPage() {
  const [activeBranch, setActiveBranch] = useState("main");
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const {
    data: branches,
    loading: branchesLoading,
    error: branchesError,
    refetch: refetchBranches,
  } = useBranches();

  const {
    data: commits,
    loading: commitsLoading,
    error: commitsError,
    refetch: refetchCommits,
  } = useCommits(activeBranch);

  const triggerRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
    refetchCommits();
    refetchBranches();
  }, [refetchCommits, refetchBranches]);

  const handleBranchChange = useCallback(
    (name: string) => {
      setActiveBranch(name);
      setSelectedTable(null);
    },
    []
  );

  return (
    <div className="flex min-h-screen flex-col">
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-30 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center justify-between px-4 sm:px-6">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/20">
              <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-zinc-100">
                ChronoDB
              </h1>
              <p className="text-[10px] text-zinc-500">
                Version-Controlled Database
              </p>
            </div>
          </div>

          {/* Center: branch switcher */}
          <div className="flex items-center gap-3">
            {branchesError ? (
              <ErrorState
                message="Failed to load branches"
                onRetry={refetchBranches}
              />
            ) : branchesLoading || !branches ? (
              <div className="h-8 w-32 animate-pulse rounded-lg bg-zinc-800/50" />
            ) : (
              <BranchSwitcher
                branches={branches}
                activeBranch={activeBranch}
                onBranchChange={handleBranchChange}
                onRefresh={triggerRefresh}
              />
            )}
          </div>

          {/* Right: dark mode */}
          <div className="flex items-center gap-2">
            <DarkModeToggle />
          </div>
        </div>
      </header>

      {/* ── Main content ── */}
      <main className="mx-auto flex w-full max-w-[1600px] flex-1 gap-4 p-4 sm:p-6">
        {/* Left panel: commit history */}
        <aside className="hidden w-80 flex-shrink-0 lg:block animate-fade-in">
          <div className="sticky top-20 flex h-[calc(100vh-6rem)] flex-col gap-4">
            <CommitHistory
              commits={commits || []}
              loading={commitsLoading}
              error={commitsError}
              branchName={activeBranch}
              onRollback={triggerRefresh}
              onRetry={refetchCommits}
            />
          </div>
        </aside>

        {/* Right panel: table viewer + commit form */}
        <div className="flex min-w-0 flex-1 flex-col gap-4 animate-slide-up">
          {/* Table viewer */}
          <div className="min-h-[300px] flex-1" key={`table-${activeBranch}-${refreshKey}`}>
            <TableViewer
              branchName={activeBranch}
              selectedTable={selectedTable}
              onSelectTable={setSelectedTable}
            />
          </div>

          {/* Commit panel */}
          <CommitPanel
            branchName={activeBranch}
            onCommitCreated={triggerRefresh}
          />

          {/* Mobile: commit history below */}
          <div className="lg:hidden" key={`history-mobile-${activeBranch}-${refreshKey}`}>
            <CommitHistory
              commits={commits || []}
              loading={commitsLoading}
              error={commitsError}
              branchName={activeBranch}
              onRollback={triggerRefresh}
              onRetry={refetchCommits}
            />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800/40 py-3 text-center text-[10px] text-zinc-600">
        ChronoDB · Version-Controlled Database Engine · Built with Next.js + FastAPI
      </footer>
    </div>
  );
}
