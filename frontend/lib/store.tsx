"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, Branch, Commit } from "./api";

export type View = "data" | "sql" | "history" | "graph" | "compare" | "storage";
export const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "data", label: "Data", hint: "Browse and edit tables" },
  { id: "sql", label: "SQL", hint: "Query with time travel" },
  { id: "history", label: "History", hint: "Commits, rollback, revert" },
  { id: "graph", label: "Graph", hint: "Branch and merge topology" },
  { id: "compare", label: "Compare & merge", hint: "Diff branches, resolve conflicts" },
  { id: "storage", label: "Storage", hint: "Optimizer, GC, branches, tags" },
];

export interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  text: string;
}

interface Ctx {
  view: View;
  setView: (v: View) => void;
  branch: string;
  setBranch: (b: string) => void;
  branches: Branch[];
  /** Commit being viewed; null means the branch head (live, editable). */
  asOf: Commit | null;
  setAsOf: (c: Commit | null) => void;
  log: Commit[];
  logTotal: number;
  author: string;
  setAuthor: (a: string) => void;
  version: number;
  refresh: () => void;
  toast: (text: string, kind?: Toast["kind"]) => void;
  toasts: Toast[];
  dismiss: (id: number) => void;
  apiDown: string | null;
  /** A commit another view asked History to open. */
  focus: string | null;
  setFocus: (hash: string | null) => void;
}

const AppContext = createContext<Ctx | null>(null);

function readLocal(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function writeLocal(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [view, setViewState] = useState<View>("data");
  const [focus, setFocus] = useState<string | null>(null);
  const [branch, setBranchState] = useState("main");
  const [branches, setBranches] = useState<Branch[]>([]);
  const [asOf, setAsOf] = useState<Commit | null>(null);
  const [log, setLog] = useState<Commit[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [author, setAuthorState] = useState("you");
  const [version, setVersion] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [apiDown, setApiDown] = useState<string | null>(null);
  const toastId = useRef(0);

  // Restore view from the URL hash and the author from local storage. These
  // exist only in the browser, so they are read after hydration.
  useEffect(() => {
    const fromHash = () => {
      const h = window.location.hash.replace("#", "") as View;
      if (VIEWS.some((v) => v.id === h)) setViewState(h);
    };
    fromHash();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser-only state, read after hydration
    setAuthorState(readLocal("chronodb.author", "you"));
    const b = readLocal("chronodb.branch", "main");
    setBranchState(b);
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, []);

  const setView = useCallback((v: View) => {
    setViewState(v);
    if (v !== "history") setFocus(null);
    if (window.location.hash !== `#${v}`) history.replaceState(null, "", `#${v}`);
  }, []);

  const setBranch = useCallback((b: string) => {
    setBranchState(b);
    setAsOf(null);
    writeLocal("chronodb.branch", b);
  }, []);

  const setAuthor = useCallback((a: string) => {
    setAuthorState(a);
    writeLocal("chronodb.author", a);
  }, []);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const toast = useCallback(
    (text: string, kind: Toast["kind"] = "ok") => {
      const id = ++toastId.current;
      setToasts((t) => [...t.slice(-3), { id, kind, text }]);
      setTimeout(() => dismiss(id), kind === "error" ? 7000 : 3500);
    },
    [dismiss],
  );

  // Branch list + log of the current branch, reloaded on every change
  useEffect(() => {
    let live = true;
    Promise.all([api.branches(), api.log(branch, 300)])
      .then(([b, l]) => {
        if (!live) return;
        setApiDown(null);
        setBranches(b.branches);
        setLog(l.commits);
        setLogTotal(l.total);
      })
      .catch((e: Error & { status?: number }) => {
        if (!live) return;
        if (e.status === 404 && branch !== "main") {
          setBranch("main");
          return;
        }
        setApiDown(e.message);
      });
    return () => {
      live = false;
    };
  }, [branch, version, setBranch]);

  const value = useMemo<Ctx>(
    () => ({
      view, setView, branch, setBranch, branches, asOf, setAsOf, log, logTotal,
      author, setAuthor, version, refresh, toast, toasts, dismiss, apiDown, focus, setFocus,
    }),
    [view, setView, branch, setBranch, branches, asOf, log, logTotal, author, setAuthor, version, refresh, toast, toasts, dismiss, apiDown, focus],
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): Ctx {
  const c = useContext(AppContext);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}

/**
 * Small async helper: reruns when deps change. `data` keeps the last result
 * while a new request is in flight; `loading` is true until the result for
 * the current deps arrives.
 */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const key = JSON.stringify(deps);
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null, data: null, error: null,
  });
  useEffect(() => {
    let live = true;
    fn()
      .then((d) => live && setState({ key, data: d, error: null }))
      .catch((e: Error) => live && setState((s) => ({ key, data: s.data, error: e.message })));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { data: state.data, error: state.key === key ? state.error : null, loading: state.key !== key };
}
