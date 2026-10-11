"use client";

import { useEffect, useState } from "react";
import { AppProvider, useApp, View, VIEWS } from "@/lib/store";
import { api } from "@/lib/api";
import BranchMenu from "@/components/BranchMenu";
import Timeline from "@/components/Timeline";
import { Toasts } from "@/components/ui";
import {
  IconClock, IconGraph, IconMerge, IconStorage, IconTable, IconTerminal, LogoMark,
} from "@/components/icons";
import DataView from "@/views/DataView";
import SqlView from "@/views/SqlView";
import HistoryView from "@/views/HistoryView";
import GraphView from "@/views/GraphView";
import CompareView from "@/views/CompareView";
import StorageView from "@/views/StorageView";

const ICONS: Record<View, (p: { width?: number; height?: number }) => React.ReactNode> = {
  data: IconTable,
  sql: IconTerminal,
  history: IconClock,
  graph: IconGraph,
  compare: IconMerge,
  storage: IconStorage,
};

const TITLES: Record<View, { title: string; sub: string }> = {
  data: { title: "Data", sub: "Edit rows directly. Changes are staged and saved together as one commit on the current branch." },
  sql: { title: "SQL console", sub: "SELECT, INSERT, UPDATE and DELETE with AS OF COMMIT, BRANCH, TAG or TIMESTAMP for reading the past." },
  history: { title: "History", sub: "Every commit reachable from this branch. Inspect what changed, roll back, revert a single commit, or tag a release." },
  graph: { title: "Graph", sub: "How branches split off and merge back. Select a commit to open it in History." },
  compare: { title: "Compare and merge", sub: "See how two branches differ, then merge with a three-way merge. Conflicting rows are resolved here." },
  storage: { title: "Storage", sub: "How history is stored, plus maintenance: delta compression, garbage collection, branches and tags." },
};

function Shell() {
  const { view, setView, asOf, apiDown, refresh, author, setAuthor, branch } = useApp();
  const Current = { data: DataView, sql: SqlView, history: HistoryView, graph: GraphView, compare: CompareView, storage: StorageView }[view];

  // Keyboard: 1–6 switch views when not typing
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(t.tagName)) return;
      const i = Number(e.key) - 1;
      if (i >= 0 && i < VIEWS.length) setView(VIEWS[i].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setView]);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          <LogoMark className="brand-mark" />
          <div>
            <div className="brand-name">ChronoDB</div>
            <div className="brand-sub">version-controlled database</div>
          </div>
        </div>
        <div className="nav">
          {VIEWS.map((v, i) => {
            const Icon = ICONS[v.id];
            return (
              <button key={v.id} className="nav-item" aria-current={view === v.id ? "page" : undefined} onClick={() => setView(v.id)} title={`${v.hint} (${i + 1})`}>
                <Icon />
                <span style={{ flex: 1 }}>{v.label}</span>
                <kbd className="rail-tables" aria-hidden>{i + 1}</kbd>
              </button>
            );
          })}
        </div>
        <div className="rail-foot">
          <label className="field">
            <span>Committing as</span>
            <input className="input" value={author} onChange={(e) => setAuthor(e.target.value)} aria-label="Author name for commits" />
          </label>
          <p style={{ marginTop: 12 }}>
            <a href="/api/docs" target="_blank" rel="noreferrer" style={{ color: "var(--ink-2)", textDecoration: "underline" }}>API reference</a>
          </p>
        </div>
      </nav>

      <div className="main" data-past={asOf ? "true" : "false"}>
        <header className="topbar">
          <BranchMenu />
          <Timeline />
        </header>
        <main className="content">
          {apiDown ? (
            <ApiDown message={apiDown} onRetry={refresh} />
          ) : (
            <>
              <div style={{ marginBottom: 18 }}>
                <h1 className="page-title">{TITLES[view].title}</h1>
                <p className="page-sub">{TITLES[view].sub}</p>
              </div>
              {/* Remount per branch so staged edits and selections never leak across branches */}
              <Current key={branch} />
            </>
          )}
        </main>
      </div>
      <Toasts />
    </div>
  );
}

function ApiDown({ message, onRetry }: { message: string; onRetry: () => void }) {
  const [checking, setChecking] = useState(false);
  return (
    <div className="panel" style={{ padding: 24, maxWidth: 640 }}>
      <h1 className="page-title">The API isn&apos;t responding</h1>
      <p className="page-sub">{message}</p>
      <pre className="code" style={{ background: "var(--panel-2)", padding: 12, borderRadius: 8, marginTop: 14, overflowX: "auto" }}>
{`# from the repository root
python3 scripts/seed_demo.py          # optional: sample data
python3 -m uvicorn api.main:app --port 8000`}
      </pre>
      <button className="btn btn-primary" style={{ marginTop: 14 }} disabled={checking}
        onClick={async () => { setChecking(true); await api.stats().catch(() => null); setChecking(false); onRetry(); }}>
        Check again
      </button>
    </div>
  );
}

export default function Page() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
