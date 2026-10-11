"use client";

import { useMemo, useState } from "react";
import { api, Conflict, RowData } from "@/lib/api";
import { useApp, useLoad } from "@/lib/store";
import { cell, short } from "@/lib/format";
import DiffView, { DiffSummary } from "@/components/DiffView";
import { Empty, ErrorNote, SkeletonRows } from "@/components/ui";
import { IconArrowRight, IconMerge } from "@/components/icons";

type Choice = "source" | "target" | "custom" | "delete";

export default function CompareView() {
  const { branch, branches, author, refresh, toast, setBranch, setView } = useApp();
  const names = branches.map((b) => b.name);
  // Defaults: merge the current branch into main (or the first other branch into main)
  const [baseSel, setBase] = useState<string | null>(null);
  const [headSel, setHead] = useState<string | null>(null);
  const base = baseSel && names.includes(baseSel) ? baseSel : "main";
  const head = headSel && names.includes(headSel) && headSel !== base
    ? headSel
    : branch !== base ? branch : names.find((n) => n !== base) ?? "";

  const cmp = useLoad(() => (base && head && base !== head ? api.compare(base, head) : Promise.resolve(null)), [base, head, branches]);
  const preview = cmp.data?.merge_preview ?? null;
  const conflicts = useMemo(() => preview?.conflicting_rows ?? [], [preview]);

  // Decisions belong to one base/head pair and one preview; a new pair starts clean
  const pairKey = `${base}\u0000${head}\u0000${preview?.lca ?? ""}`;
  const [decided, setDecided] = useState<{ key: string; map: Record<string, { choice: Choice; custom?: RowData }> }>({ key: "", map: {} });
  const choices = decided.key === pairKey ? decided.map : {};
  const setChoices = (fn: (m: typeof choices) => typeof choices) => setDecided({ key: pairKey, map: fn(choices) });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const unresolved = conflicts.filter((c) => !choices[`${c.table_name}:${c.row_id}`]).length;

  const merge = async () => {
    setBusy(true);
    try {
      const resolutions = conflicts.map((c) => {
        const k = `${c.table_name}:${c.row_id}`;
        const ch = choices[k];
        const data = ch.choice === "source" ? c.source_data : ch.choice === "target" ? c.target_data : ch.choice === "custom" ? ch.custom ?? null : null;
        return { key: k, data };
      });
      const r = await api.merge(head, base, author, resolutions, message.trim() || undefined);
      if (r.status === "conflict") {
        toast(`Merge stopped: ${r.conflicts?.length} rows still conflict`, "error");
      } else {
        toast(r.strategy === "fast-forward" ? `${base} fast-forwarded to ${head}` : `Merged ${head} into ${base} as ${short(r.commit?.hash)}`);
        setMessage("");
        setBranch(base);
        refresh();
        setView("history");
      }
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (branches.length < 2) {
    return <Empty title="Only one branch">Create a branch from the branch menu, change some rows on it, and come back to compare and merge.</Empty>;
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel" style={{ padding: 16, display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
        <BranchSelect names={names} label="Merge into" value={base} onChange={setBase} exclude={head} />
        <IconArrowRight width={20} height={20} style={{ color: "var(--ink-3)", marginBottom: 6, transform: "scaleX(-1)" }} />
        <BranchSelect names={names} label="Changes from" value={head} onChange={setHead} exclude={base} />
        <span style={{ flex: 1 }} />
        {cmp.data && (
          <span className="hint" style={{ marginBottom: 6 }}>
            {head} is <b style={{ color: "var(--ink)" }}>{cmp.data.ahead}</b> commits ahead and <b style={{ color: "var(--ink)" }}>{cmp.data.behind}</b> behind {base}
          </span>
        )}
      </div>

      {cmp.error ? <ErrorNote message={cmp.error} /> : cmp.loading && !cmp.data ? <div className="panel"><SkeletonRows /></div> : cmp.data && preview && (
        <>
          <MergeBox
            strategy={preview.strategy}
            conflicts={conflicts.length}
            unresolved={unresolved}
            changes={preview.rows_changed_on_target ?? preview.changes.length}
            autoMerged={preview.auto_merged_rows?.length ?? 0}
            base={base}
            head={head}
            message={message}
            setMessage={setMessage}
            busy={busy}
            onMerge={merge}
          />

          {conflicts.length > 0 && (
            <section style={{ display: "grid", gap: 12 }}>
              <h2 className="panel-title" style={{ fontSize: 16 }}>Resolve {conflicts.length} conflicting row{conflicts.length > 1 ? "s" : ""}</h2>
              {conflicts.map((c) => {
                const k = `${c.table_name}:${c.row_id}`;
                return (
                  <ConflictCard key={k} c={c} base={base} head={head} value={choices[k]}
                    onChange={(v) => setChoices((m) => ({ ...m, [k]: v }))} />
                );
              })}
            </section>
          )}

          <section style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h2 className="panel-title" style={{ fontSize: 16 }}>What differs</h2>
              <DiffSummary diff={cmp.data.diff} />
            </div>
            <p className="hint" style={{ margin: 0 }}>Red is the value on {base}, green is the value on {head}.</p>
            <DiffView diff={cmp.data.diff} emptyText={`${base} and ${head} hold the same data.`} />
          </section>
        </>
      )}
    </div>
  );
}

function BranchSelect({ names, value, onChange, label, exclude }: { names: string[]; value: string; onChange: (v: string) => void; label: string; exclude: string }) {
  return (
    <label className="field" style={{ minWidth: 200 }}>
      <span>{label}</span>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {names.filter((n) => n !== exclude).map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
    </label>
  );
}

function MergeBox(p: {
  strategy: string; conflicts: number; unresolved: number; changes: number; autoMerged: number;
  base: string; head: string; message: string; setMessage: (s: string) => void; busy: boolean; onMerge: () => void;
}) {
  const upToDate = p.strategy === "up-to-date";
  const state = upToDate ? "done" : p.unresolved ? "blocked" : "ready";
  const color = state === "blocked" ? "var(--del)" : state === "ready" ? "var(--add)" : "var(--ink-3)";
  return (
    <section className="panel" style={{ padding: 16, display: "grid", gap: 12, borderLeft: `4px solid ${color}` }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <IconMerge width={22} height={22} style={{ color }} />
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontWeight: 600, fontSize: 15 }}>
            {upToDate ? `${p.base} already contains everything on ${p.head}`
              : p.strategy === "fast-forward" ? `Fast-forward: ${p.base} can simply move up to ${p.head}`
              : p.conflicts === 0 ? "No conflicts. These branches merge cleanly."
              : p.unresolved ? `${p.unresolved} of ${p.conflicts} conflicts still need a decision`
              : "All conflicts resolved. Ready to merge."}
          </div>
          <div className="hint">
            {upToDate ? "There is nothing to merge."
              : p.strategy === "fast-forward" ? `${p.base} has no commits of its own since ${p.head} branched off, so no merge commit is needed.`
              : `A merge commit on ${p.base} will change ${p.changes} row${p.changes === 1 ? "" : "s"}${p.autoMerged ? `, including ${p.autoMerged} row${p.autoMerged > 1 ? "s" : ""} where both branches edited different columns and were combined automatically` : ""}.`}
          </div>
        </div>
      </div>
      {!upToDate && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {p.strategy === "three-way" && (
            <input className="input" style={{ flex: 1, minWidth: 220 }} value={p.message} onChange={(e) => p.setMessage(e.target.value)}
              placeholder={`Merge branch '${p.head}' into '${p.base}'`} aria-label="Merge commit message" />
          )}
          <button className="btn btn-primary" disabled={p.busy || p.unresolved > 0} onClick={p.onMerge}>
            {p.strategy === "fast-forward" ? `Fast-forward ${p.base}` : `Merge into ${p.base}`}
          </button>
        </div>
      )}
    </section>
  );
}

function ConflictCard({ c, base, head, value, onChange }: {
  c: Conflict; base: string; head: string;
  value?: { choice: Choice; custom?: RowData };
  onChange: (v: { choice: Choice; custom?: RowData }) => void;
}) {
  const cols = [...new Set([...Object.keys(c.ancestor_data ?? {}), ...Object.keys(c.target_data ?? {}), ...Object.keys(c.source_data ?? {})])];
  const custom: RowData = value?.custom ?? { ...(c.target_data ?? c.source_data ?? {}) };
  const why = {
    modify_modify: `Both branches changed ${c.conflicting_cells.join(", ")}`,
    delete_modify: `${head} deleted this row, ${base} changed it`,
    modify_delete: `${head} changed this row, ${base} deleted it`,
    add_add: `Both branches added a row with this id`,
  }[c.conflict_type];

  const pick = (choice: Choice) => onChange(choice === "custom" ? { choice, custom } : { choice });
  const opt = (choice: Choice, label: string, disabled = false) => (
    <button className="btn btn-sm" aria-pressed={value?.choice === choice} disabled={disabled}
      style={value?.choice === choice ? { background: "var(--head)", color: "#fff", borderColor: "var(--head)" } : undefined}
      onClick={() => pick(choice)}>{label}</button>
  );

  return (
    <article className="panel" style={{ overflow: "hidden", borderColor: value ? "var(--rule)" : "var(--del)" }}>
      <div className="panel-head" style={{ flexWrap: "wrap" }}>
        <span className="mono" style={{ fontWeight: 600 }}>{c.table_name} / {c.row_id}</span>
        <span className="hint">{why}</span>
        <span style={{ flex: 1 }} />
        {opt("target", `Keep ${base}`)}
        {opt("source", `Take ${head}`)}
        {opt("custom", "Edit")}
        {opt("delete", "Delete row")}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="diff-table">
          <thead>
            <tr><th>column</th><th>common ancestor</th><th>{base}</th><th>{head}</th>{value?.choice === "custom" && <th>result</th>}</tr>
          </thead>
          <tbody>
            {cols.map((col) => {
              const hot = c.conflicting_cells.includes(col);
              const v = (d: RowData | null) => (d ? (col in d ? cell(d[col]) : "—") : "deleted");
              return (
                <tr key={col} style={hot ? { background: "var(--del-soft)" } : undefined}>
                  <td style={{ fontWeight: hot ? 600 : 400 }}>{col}</td>
                  <td style={{ color: "var(--ink-3)" }}>{v(c.ancestor_data)}</td>
                  <td>{v(c.target_data)}</td>
                  <td>{v(c.source_data)}</td>
                  {value?.choice === "custom" && (
                    <td style={{ padding: 3 }}>
                      <input className="input" style={{ width: "100%", height: 28 }} value={cell(custom[col])}
                        onChange={(e) => onChange({ choice: "custom", custom: { ...custom, [col]: e.target.value } })}
                        aria-label={`Resolved value for ${col}`} />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {value && (
        <p className="hint" style={{ padding: "8px 16px", margin: 0 }}>
          Decision: {value.choice === "target" ? `keep the ${base} version` : value.choice === "source" ? `take the ${head} version` : value.choice === "delete" ? "delete the row" : "use the edited values"}.
        </p>
      )}
    </article>
  );
}
