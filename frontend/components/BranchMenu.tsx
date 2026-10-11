"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";
import { timeAgo } from "@/lib/format";
import { IconBranch, IconCheck, IconChevron, IconPlus } from "./icons";

export default function BranchMenu() {
  const { branch, setBranch, branches, refresh, toast } = useApp();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = branches.find((b) => b.name === branch);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const shown = branches.filter((b) => b.name.toLowerCase().includes(filter.toLowerCase()));

  const create = async () => {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    try {
      await api.createBranch(n, branch);
      toast(`Created ${n} from ${branch}`);
      setName("");
      setCreating(false);
      setOpen(false);
      setBranch(n);
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={ref} style={{ position: "relative", display: "flex" }}>
      <button className="branch-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="listbox">
        <IconBranch width={18} height={18} style={{ color: "var(--head)", flex: "none" }} />
        <span style={{ minWidth: 0, flex: 1 }}>
          <span className="branch-name" style={{ display: "block" }}>{branch}</span>
          <span className="branch-meta">
            {current && branch !== "main"
              ? `${current.ahead ?? 0} ahead, ${current.behind ?? 0} behind main`
              : `${current?.commit_count ?? 0} commits`}
          </span>
        </span>
        <IconChevron width={16} height={16} style={{ color: "var(--ink-3)" }} />
      </button>

      {open && (
        <div className="popover" style={{ top: "calc(100% + 6px)", left: 8, width: 360 }}>
          <div style={{ padding: 10, borderBottom: "1px solid var(--rule-2)" }}>
            <input
              className="input"
              style={{ width: "100%" }}
              placeholder="Find a branch"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              autoFocus
            />
          </div>
          <div role="listbox" aria-label="Branches" style={{ maxHeight: 320, overflowY: "auto", padding: 6 }}>
            {shown.map((b) => (
              <button
                key={b.name}
                role="option"
                aria-selected={b.name === branch}
                className="nav-item"
                style={{ width: "100%", alignItems: "flex-start" }}
                onClick={() => {
                  setBranch(b.name);
                  setOpen(false);
                }}
              >
                <span style={{ width: 16, flex: "none", color: "var(--head)", paddingTop: 2 }}>
                  {b.name === branch && <IconCheck width={16} height={16} />}
                </span>
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ display: "block", color: "var(--ink)", fontWeight: 600 }}>{b.name}</span>
                  <span className="hint" style={{ display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {b.head_message} — {timeAgo(b.updated_at)}
                  </span>
                </span>
                {b.name !== "main" && (
                  <span className="hint num" style={{ flex: "none" }} title="Commits ahead / behind main">
                    +{b.ahead} −{b.behind}
                  </span>
                )}
              </button>
            ))}
            {!shown.length && <div className="hint" style={{ padding: 10 }}>No branch matches “{filter}”.</div>}
          </div>
          <div style={{ padding: 10, borderTop: "1px solid var(--rule-2)" }}>
            {creating ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  create();
                }}
                style={{ display: "grid", gap: 8 }}
              >
                <label className="field">
                  <span>New branch from {branch}</span>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="feature/new-pricing" autoFocus />
                </label>
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                  <button type="button" className="btn btn-ghost" onClick={() => setCreating(false)}>Cancel</button>
                  <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>Create branch</button>
                </div>
              </form>
            ) : (
              <button className="btn" style={{ width: "100%" }} onClick={() => setCreating(true)}>
                <IconPlus /> New branch from {branch}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
