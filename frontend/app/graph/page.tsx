"use client";

import dynamic from "next/dynamic";
import Link from "next/link";

// Dynamic import to avoid SSR issues with React Flow (uses window/DOM APIs)
const BranchGraph = dynamic(
  () => import("@/components/graph/BranchGraph"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-4 animate-fade-in">
          <div className="relative h-12 w-12">
            <div className="absolute inset-0 rounded-full border-2 border-zinc-700/40" />
            <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-violet-500" />
          </div>
          <p className="text-sm text-zinc-400">Initializing graph…</p>
        </div>
      </div>
    ),
  }
);

export default function GraphPage() {
  return (
    <div className="flex h-screen flex-col">
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-30 border-b border-zinc-200/60 dark:border-zinc-800/60 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1920px] items-center justify-between px-4 sm:px-6">
          {/* Logo + Back */}
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-2 rounded-lg px-2 py-1 text-zinc-400 transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-700 dark:hover:text-zinc-200"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
              </svg>
              <span className="text-xs font-medium">Dashboard</span>
            </Link>
            <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700/40" />
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/20">
              <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
                Branch Graph
              </h1>
              <p className="text-[10px] text-zinc-500">
                Commit DAG · All branches
              </p>
            </div>
          </div>

          {/* Nav links */}
          <div className="flex items-center gap-2">
            <Link
              href="/diff"
              className="flex items-center gap-1.5 rounded-lg border border-zinc-200/50 dark:border-zinc-700/40 bg-zinc-50/50 dark:bg-zinc-800/50 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 transition-all hover:border-violet-500/40 hover:bg-violet-500/10 hover:text-violet-600 dark:hover:text-violet-300"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
              Diff &amp; Merge
            </Link>
          </div>
        </div>
      </header>

      {/* ── Graph canvas (fills remaining height) ── */}
      <main className="relative flex-1 bg-zinc-50 dark:bg-zinc-950">
        <BranchGraph />
      </main>
    </div>
  );
}
