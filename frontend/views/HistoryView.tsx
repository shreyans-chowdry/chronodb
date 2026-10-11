"use client";

import { useMemo, useState } from "react";
import { api, Commit } from "@/lib/api";
import { useApp, useLoad } from "@/lib/store";
import { short, stamp, timeAgo } from "@/lib/format";
import DiffView, { DiffSummary } from "@/components/DiffView";
import { Dialog, Empty, ErrorNote, Hash, SkeletonRows } from "@/components/ui";
import { IconClock, IconMerge, IconSearch, IconTag, IconUndo } from "@/components/icons";

export default function HistoryView() {
  const { branch, log, logTotal, setAsOf, setView, author, refresh, toast, focus } = useApp();
  const [picked, setSelected] = useState<string | null>(focus);
  const selected = picked ?? log[0]?.hash ?? null;
  const [filter, setFilter] = useState("");
  const [confirm, setConfirm] = useState<"rollback" | "revert" | "tag" | null>(null);
  const [tagName, setTagName] = useState("");
  const [busy, setBusy] = useState(false);


  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return f ? log.filter((c) => [c.message, c.author, c.hash, c.branch_id].some((s) => s.toLowerCase().includes(f))) : log;
  }, [log, filter]);

  const detail = useLoad(() => (selected ? api.commit(selected) : Promise.resolve(null)), [selected]);
  const c = detail.data;
  const isHead = c && log[0]?.id === c.id;

  const act = async (kind: "rollback" | "revert" | "tag") => {
    if (!c) return;
    setBusy(true);
    try {
      if (kind === "rollback") {
        const r = await api.rollback(branch, c.hash, author);
        toast(`Rolled ${branch} back to ${short(c.hash)} as new commit ${short(r.hash)}`);
        setSelected(r.hash);
      } else if (kind === "revert") {
        const r = await api.revert(branch, c.hash, author);
        if (!r.reverted) {
          toast(`Can't revert: ${r.conflicts?.length} rows changed again later (${r.conflicts?.map((x) => x.row_id).join(", ")})`, "error");
          return;
        }
        toast(`Reverted ${short(c.hash)} as ${short(r.commit?.hash)}`);
        setSelected(r.commit?.hash ?? null);
      } else {
        await api.createTag(tagName.trim(), c.hash, "", author);
        toast(`Tagged ${short(c.hash)} as ${tagName.trim()}`);
        setTagName("");
      }
      setConfirm(null);
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 400px) minmax(0, 1fr)", gap: 20, alignItems: "start" }} className="history-layout">
      <section className="panel" style={{ overflow: "hidden" }}>
        <div className="panel-head">
          <label style={{ position: "relative", display: "flex", alignItems: "center", flex: 1 }}>
            <IconSearch width={15} height={15} style={{ position: "absolute", left: 9, color: "var(--ink-3)" }} />
            <input className="input" style={{ paddingLeft: 30, width: "100%" }} placeholder="Search message, author or hash" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
        </div>
        <div className="hint" style={{ padding: "8px 14px", borderBottom: "1px solid var(--rule-2)" }}>
          {logTotal} commits reachable from {branch}{logTotal > log.length ? `, newest ${log.length} shown` : ""}
        </div>
        <div role="listbox" aria-label="Commits" style={{ maxHeight: "calc(100dvh - 260px)", overflowY: "auto" }}>
          {shown.map((cm: Commit) => (
            <button key={cm.id} role="option" aria-selected={cm.hash === selected} className="commit-row" onClick={() => setSelected(cm.hash)}>
              <span style={{ paddingTop: 3 }} title={cm.second_parent_id ? "Merge commit" : "Commit"}>
                {cm.second_parent_id ? <IconMerge width={16} height={16} style={{ color: "var(--mod)" }} /> : <span style={{ display: "block", width: 9, height: 9, margin: "3px 3px", borderRadius: "50%", border: "2px solid var(--ink-3)" }} />}
              </span>
              <span style={{ minWidth: 0 }}>
                <span className="commit-msg" style={{ display: "block" }}>{cm.message}</span>
                <span className="commit-meta">
                  <span className="mono">{short(cm.hash)}</span>
                  <span>{cm.author}</span>
                  <span>{timeAgo(cm.timestamp)}</span>
                  {cm.branch_heads?.map((b) => <span key={b} className="chip chip-head">{b}</span>)}
                  {cm.tags?.map((t) => <span key={t} className="chip chip-tag">{t}</span>)}
                </span>
              </span>
              {cm.branch_id !== branch && <span className="chip" title="Commit was made on another branch">{cm.branch_id}</span>}
            </button>
          ))}
          {!shown.length && <Empty title="No commits match" />}
        </div>
      </section>

      <section style={{ display: "grid", gap: 16, minWidth: 0 }}>
        {detail.error ? <ErrorNote message={detail.error} /> : !c ? (
          detail.loading ? <div className="panel"><SkeletonRows /></div> : <Empty title="Select a commit" />
        ) : (
          <>
            <div className="panel" style={{ padding: 18 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Hash value={c.hash} full />
                {isHead && <span className="chip chip-head">latest on {branch}</span>}
                {c.second_parent_id && <span className="chip chip-mod">merge</span>}
                <DiffSummary diff={c.changes} />
              </div>
              <h2 className="page-title" style={{ marginTop: 12 }}>{c.message}</h2>
              <p className="page-sub">
                {c.author} committed on {c.branch_id}, {stamp(c.timestamp)} ({timeAgo(c.timestamp)})
              </p>
              <p className="hint" style={{ marginTop: 6 }}>
                Parent {c.parent_hash ? <Hash value={c.parent_hash} /> : "none (root commit)"}
                {c.second_parent_hash && <> and merged parent <Hash value={c.second_parent_hash} /></>}
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14 }}>
                <button className="btn" onClick={() => { setAsOf(isHead ? null : (log.find((x) => x.id === c.id) ?? c)); setView("data"); }}>
                  <IconClock /> Open data at this commit
                </button>
                {!isHead && (
                  <button className="btn" onClick={() => setConfirm("rollback")}><IconUndo /> Roll back to here</button>
                )}
                {c.parent_id && <button className="btn" onClick={() => setConfirm("revert")}><IconUndo /> Revert this commit</button>}
                <button className="btn" onClick={() => setConfirm("tag")}><IconTag /> Tag</button>
              </div>
            </div>
            <DiffView diff={c.changes} emptyText="This commit records an event (branch creation, merge or empty commit) without row changes." />
          </>
        )}
      </section>

      {confirm === "rollback" && c && (
        <Dialog title={`Roll ${branch} back to ${short(c.hash)}?`} onClose={() => setConfirm(null)}
          footer={<><button className="btn btn-ghost" onClick={() => setConfirm(null)}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={() => act("rollback")}>Roll back</button></>}>
          <p>Every table on <b>{branch}</b> returns to the state of “{c.message}”. Nothing is deleted: the rollback is recorded as a new commit, so you can undo it the same way.</p>
        </Dialog>
      )}
      {confirm === "revert" && c && (
        <Dialog title={`Revert ${short(c.hash)}?`} onClose={() => setConfirm(null)}
          footer={<><button className="btn btn-ghost" onClick={() => setConfirm(null)}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={() => act("revert")}>Revert commit</button></>}>
          <p>Only the rows this commit changed are put back the way they were before it. Later commits stay. If any of those rows changed again afterwards, the revert stops and lists them.</p>
        </Dialog>
      )}
      {confirm === "tag" && c && (
        <Dialog title={`Tag ${short(c.hash)}`} onClose={() => setConfirm(null)}
          footer={<><button className="btn btn-ghost" onClick={() => setConfirm(null)}>Cancel</button><button className="btn btn-primary" disabled={busy || !tagName.trim()} onClick={() => act("tag")}>Create tag</button></>}>
          <label className="field">
            <span>Tag name</span>
            <input className="input" value={tagName} onChange={(e) => setTagName(e.target.value)} placeholder="v1.1" onKeyDown={(e) => e.key === "Enter" && tagName.trim() && act("tag")} />
          </label>
          <p className="hint">Tags are fixed names for a commit. Use them in SQL with <code className="mono">AS OF TAG name</code>.</p>
        </Dialog>
      )}
    </div>
  );
}
