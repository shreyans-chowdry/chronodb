"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Change, Row, RowData, RowVersion } from "@/lib/api";
import { useApp, useLoad } from "@/lib/store";
import { cell, download, parseCell, short, stamp, timeAgo, toCSV } from "@/lib/format";
import { Dialog, Empty, ErrorNote, Hash, SkeletonRows } from "@/components/ui";
import {
  IconClock, IconColumns, IconDownload, IconPlus, IconSearch, IconTable, IconTrash, IconUndo, IconX,
} from "@/components/icons";

type Pending =
  | { action: "insert"; data: RowData }
  | { action: "update"; data: RowData; original: RowData }
  | { action: "delete"; original: RowData };

const keyOf = (table: string, id: string) => `${table}\u0000${id}`;
const strip = (r: Row): RowData => {
  const { row_id: _drop, ...rest } = r;
  void _drop;
  return rest;
};

function typeOf(v: unknown) {
  if (v === null || v === undefined || v === "") return "null";
  if (typeof v === "number") return "number";
  return "text";
}

export default function DataView() {
  const { branch, asOf, version, refresh, toast, author, setAsOf } = useApp();
  const readOnly = !!asOf;
  const asOfHash = asOf?.hash ?? null;

  const tables = useLoad(() => api.tables(branch, asOfHash), [branch, asOfHash, version]);
  const [picked, setTable] = useState<string | null>(null);
  const [newTables, setNewTables] = useState<string[]>([]);
  // Keep the chosen table while it exists at this point in time, else show the first
  const known = tables.data?.tables ?? [];
  const table = picked && (known.includes(picked) || newTables.includes(picked)) ? picked : known[0] ?? newTables[0] ?? null;
  const rows = useLoad(
    () => (table && !newTables.includes(table) ? api.data(table, branch, asOfHash) : Promise.resolve({ rows: [] as Row[], commit: null as never })),
    [table, branch, asOfHash, version],
  );

  const [pending, setPending] = useState<Map<string, Pending>>(new Map());
  const [extraCols, setExtraCols] = useState<Record<string, string[]>>({});
  const [editing, setEditing] = useState<{ id: string; col: string } | null>(null);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ col: string; desc: boolean } | null>(null);
  const [inspect, setInspect] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<"table" | "column" | null>(null);

  const baseRows: Row[] = useMemo(() => rows.data?.rows ?? [], [rows.data]);

  const columns = useMemo(() => {
    const set = new Set<string>();
    baseRows.forEach((r) => Object.keys(r).forEach((k) => k !== "row_id" && set.add(k)));
    if (table) {
      pending.forEach((p, k) => {
        if (!k.startsWith(table + "\u0000")) return;
        if (p.action !== "delete") Object.keys(p.data).forEach((c) => set.add(c));
      });
      (extraCols[table] ?? []).forEach((c) => set.add(c));
    }
    return [...set];
  }, [baseRows, pending, extraCols, table]);

  // Rows as displayed: base + staged edits, inserts first
  const display = useMemo(() => {
    if (!table) return [];
    const out: { id: string; data: RowData; state?: Pending["action"] }[] = [];
    pending.forEach((p, k) => {
      const [t, id] = k.split("\u0000");
      if (t === table && p.action === "insert") out.push({ id, data: p.data, state: "insert" });
    });
    baseRows.forEach((r) => {
      const p = pending.get(keyOf(table, r.row_id));
      if (p?.action === "update") out.push({ id: r.row_id, data: p.data, state: "update" });
      else if (p?.action === "delete") out.push({ id: r.row_id, data: strip(r), state: "delete" });
      else out.push({ id: r.row_id, data: strip(r) });
    });
    const f = filter.trim().toLowerCase();
    let res = f
      ? out.filter((r) => r.id.toLowerCase().includes(f) || Object.values(r.data).some((v) => cell(v).toLowerCase().includes(f)))
      : out;
    if (sort) {
      const val = (r: (typeof out)[number]) => (sort.col === "row_id" ? r.id : r.data[sort.col]);
      res = [...res].sort((a, b) => {
        const x = val(a), y = val(b);
        const nx = Number(x), ny = Number(y);
        const c = !isNaN(nx) && !isNaN(ny) && x !== "" && y !== "" ? nx - ny : cell(x).localeCompare(cell(y));
        return sort.desc ? -c : c;
      });
    }
    return res;
  }, [baseRows, pending, table, filter, sort]);

  const pendingCount = pending.size;

  const stage = useCallback((t: string, id: string, next: Pending | null) => {
    setPending((m) => {
      const n = new Map(m);
      if (next) n.set(keyOf(t, id), next);
      else n.delete(keyOf(t, id));
      return n;
    });
  }, []);

  const startEdit = (id: string, col: string, value: unknown) => {
    if (readOnly) return;
    setEditing({ id, col });
    setDraft(cell(value));
  };

  const finishEdit = (save: boolean) => {
    if (!editing || !table) return setEditing(null);
    const { id, col } = editing;
    setEditing(null);
    if (!save) return;
    const k = keyOf(table, id);
    const p = pending.get(k);
    const base = baseRows.find((r) => r.row_id === id);
    const current: RowData = p && p.action !== "delete" ? p.data : base ? strip(base) : {};
    const value = parseCell(draft, current[col]);
    if (cell(value) === cell(current[col]) && typeof value === typeof current[col]) return;
    const data = { ...current, [col]: value };
    if (p?.action === "insert") stage(table, id, { action: "insert", data });
    else if (base) {
      const original = strip(base);
      const same = JSON.stringify(data) === JSON.stringify(original);
      stage(table, id, same ? null : { action: "update", data, original });
    }
  };

  const addRow = () => {
    if (!table) return;
    const existing = new Set([...baseRows.map((r) => r.row_id), ...[...pending.keys()].map((k) => k.split("\u0000")[1])]);
    let i = baseRows.length + 1;
    const prefix = table.replace(/s$/, "").slice(0, 4) || "row";
    let id = `${prefix}_${i}`;
    while (existing.has(id)) id = `${prefix}_${++i}`;
    const data: RowData = {};
    columns.forEach((c) => (data[c] = ""));
    stage(table, id, { action: "insert", data });
    if (columns[0]) startEdit(id, columns[0], "");
  };

  const toggleDelete = (id: string) => {
    if (!table) return;
    const p = pending.get(keyOf(table, id));
    if (p?.action === "insert") return stage(table, id, null);
    if (p?.action === "delete") return stage(table, id, null);
    const base = baseRows.find((r) => r.row_id === id);
    if (base) stage(table, id, { action: "delete", original: strip(base) });
  };

  const commit = async () => {
    const changes: Change[] = [];
    pending.forEach((p, k) => {
      const [t, id] = k.split("\u0000");
      if (p.action === "delete") changes.push({ action: "delete", table_name: t, row_id: id });
      else changes.push({ action: p.action, table_name: t, row_id: id, data: p.data });
    });
    const msg = message.trim() || defaultMessage(pending);
    setBusy(true);
    try {
      const c = await api.createCommit(branch, msg, author, changes);
      toast(`Committed ${short(c.hash)} to ${branch}`);
      setPending(new Map());
      setNewTables([]);
      setMessage("");
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  // Stage the changes that make the live table match this snapshot
  const restoreSnapshot = async () => {
    if (!table || !asOf) return;
    setBusy(true);
    try {
      const live = await api.data(table, branch);
      const snap = new Map(baseRows.map((r) => [r.row_id, strip(r)]));
      const next = new Map<string, Pending>();
      live.rows.forEach((r) => {
        const s = snap.get(r.row_id);
        if (!s) next.set(keyOf(table, r.row_id), { action: "delete", original: strip(r) });
        else if (JSON.stringify(s) !== JSON.stringify(strip(r))) next.set(keyOf(table, r.row_id), { action: "update", data: s, original: strip(r) });
        snap.delete(r.row_id);
      });
      snap.forEach((d, id) => next.set(keyOf(table, id), { action: "insert", data: d }));
      setAsOf(null);
      setPending(next);
      setMessage(`Restore ${table} to ${short(asOf.hash)}`);
      toast(next.size ? `Staged ${next.size} changes to restore ${table}` : `${table} already matches this snapshot`, "info");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const tableList = [...(tables.data?.tables ?? []), ...newTables.filter((t) => !(tables.data?.tables ?? []).includes(t))];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(170px, 210px) minmax(0, 1fr)", gap: 20, alignItems: "start" }} className="data-layout">
      <aside className="rail-tables" aria-label="Tables">
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <span className="rail-heading" style={{ padding: 0, flex: 1 }}>Tables</span>
          {!readOnly && (
            <button className="btn btn-ghost btn-sm" onClick={() => setDialog("table")} title="New table">
              <IconPlus />
            </button>
          )}
        </div>
        {tables.loading && !tables.data ? (
          <div className="skeleton" style={{ height: 120 }} />
        ) : tableList.length ? (
          <div style={{ display: "grid", gap: 1 }}>
            {tableList.map((t) => (
              <button
                key={t}
                className="nav-item"
                aria-current={t === table ? "page" : undefined}
                onClick={() => {
                  setTable(t);
                  setSort(null);
                  setFilter("");
                }}
              >
                <IconTable />
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{t}</span>
                <span className="hint num">{tables.data?.counts?.[t] ?? "new"}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="hint">{readOnly ? "No tables existed at this commit." : "No tables yet."}</p>
        )}
      </aside>

      <section className="panel" style={{ overflow: "hidden", minWidth: 0 }}>
        {readOnly && asOf && (
          <div className="past-banner" style={{ margin: 12 }}>
            <IconClock width={18} height={18} style={{ color: "var(--past)", flex: "none" }} />
            <span style={{ flex: 1 }}>
              You are looking at <b>{table ?? "the database"}</b> as it was at <Hash value={asOf.hash} />, “{asOf.message}”, {timeAgo(asOf.timestamp)}.
              Edits are disabled.
            </span>
            {table && (
              <button className="btn btn-sm" onClick={restoreSnapshot} disabled={busy}>
                <IconUndo /> Restore this table
              </button>
            )}
          </div>
        )}

        <div className="panel-head" style={{ flexWrap: "wrap" }}>
          <span className="panel-title">{table ?? "No table selected"}</span>
          {table && <span className="hint num">{display.length} rows · {columns.length} columns</span>}
          <span style={{ flex: 1 }} />
          <label style={{ position: "relative", display: "flex", alignItems: "center" }}>
            <IconSearch width={15} height={15} style={{ position: "absolute", left: 9, color: "var(--ink-3)" }} />
            <input
              className="input"
              style={{ paddingLeft: 30, width: 190 }}
              placeholder="Filter rows"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filter rows"
            />
          </label>
          {table && (
            <button
              className="btn"
              onClick={() => download(`${table}${asOf ? "@" + short(asOf.hash) : ""}.csv`, toCSV(["row_id", ...columns], display.map((r) => ({ row_id: r.id, ...r.data }))))}
              title="Download as CSV"
            >
              <IconDownload /> CSV
            </button>
          )}
          {!readOnly && table && (
            <>
              <button className="btn" onClick={() => setDialog("column")}><IconColumns /> Add column</button>
              <button className="btn btn-primary" onClick={addRow}><IconPlus /> Add row</button>
            </>
          )}
        </div>

        {tables.error ? (
          <div style={{ padding: 16 }}><ErrorNote message={tables.error} onRetry={refresh} /></div>
        ) : !table ? (
          <Empty
            title={readOnly ? "Nothing here at this point in time" : "Create your first table"}
            action={!readOnly && <button className="btn btn-primary" onClick={() => setDialog("table")}><IconPlus /> New table</button>}
          >
            {readOnly ? "Move the timeline forward to a later commit." : "Tables are created by committing their first row. You can also use the SQL console."}
          </Empty>
        ) : rows.loading && !rows.data ? (
          <SkeletonRows />
        ) : rows.error ? (
          <div style={{ padding: 16 }}><ErrorNote message={rows.error} onRetry={refresh} /></div>
        ) : (
          <div className="grid-wrap">
            <table className="dgrid">
              <thead>
                <tr>
                  {(["row_id", ...columns] as string[]).map((c) => (
                    <th key={c} aria-sort={sort?.col === c ? (sort.desc ? "descending" : "ascending") : "none"}>
                      <button onClick={() => setSort((s) => (s?.col === c ? (s.desc ? null : { col: c, desc: true }) : { col: c, desc: false }))}>
                        {c}
                        {sort?.col === c && <span aria-hidden>{sort.desc ? "↓" : "↑"}</span>}
                      </button>
                    </th>
                  ))}
                  <th style={{ width: 1 }}><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {display.map((r) => {
                  const p = table ? pending.get(keyOf(table, r.id)) : undefined;
                  return (
                    <tr key={r.id} data-pending={r.state} data-selected={inspect === r.id}>
                      <td className="key">
                        <button className="cell" style={{ textAlign: "left", width: "100%", cursor: "pointer" }} onClick={() => setInspect(r.id)} title="Show this row's history">
                          {r.id}
                        </button>
                      </td>
                      {columns.map((c) => {
                        const v = r.data[c];
                        const isEditing = editing?.id === r.id && editing.col === c;
                        const edited = p?.action === "update" && JSON.stringify(p.original[c]) !== JSON.stringify(p.data[c]);
                        return (
                          <td key={c} data-edited={edited} onDoubleClick={() => r.state !== "delete" && startEdit(r.id, c, v)}>
                            {isEditing ? (
                              <input
                                className="cell-edit"
                                value={draft}
                                autoFocus
                                onChange={(e) => setDraft(e.target.value)}
                                onBlur={() => finishEdit(true)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") finishEdit(true);
                                  if (e.key === "Escape") finishEdit(false);
                                  if (e.key === "Tab") {
                                    e.preventDefault();
                                    finishEdit(true);
                                    const i = columns.indexOf(c) + (e.shiftKey ? -1 : 1);
                                    if (columns[i]) setTimeout(() => startEdit(r.id, columns[i], r.data[columns[i]]), 0);
                                  }
                                }}
                                aria-label={`${c} of ${r.id}`}
                              />
                            ) : (
                              <span
                                className="cell"
                                data-type={typeOf(v)}
                                tabIndex={readOnly || r.state === "delete" ? -1 : 0}
                                onKeyDown={(e) => e.key === "Enter" && startEdit(r.id, c, v)}
                                title={cell(v)}
                              >
                                {v === null ? "null" : cell(v)}
                              </span>
                            )}
                          </td>
                        );
                      })}
                      <td>
                        {!readOnly && (
                          <div className="row-actions">
                            <button
                              className={`btn btn-ghost btn-sm ${r.state === "delete" ? "" : "btn-danger"}`}
                              onClick={() => toggleDelete(r.id)}
                              title={r.state === "delete" ? "Keep row" : r.state === "insert" ? "Remove new row" : "Delete row"}
                              aria-label={r.state === "delete" ? `Keep ${r.id}` : `Delete ${r.id}`}
                            >
                              {r.state === "delete" ? <IconUndo /> : <IconTrash />}
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!display.length && (
              <Empty title={filter ? "No rows match the filter" : "This table is empty"}>
                {filter ? "Clear the filter to see every row." : readOnly ? "" : "Add a row to start."}
              </Empty>
            )}
            {!readOnly && display.length > 0 && (
              <p className="hint" style={{ padding: "10px 14px" }}>
                Double-click a cell to edit it. Edits are staged until you commit them. Click a row id to see its history.
              </p>
            )}
          </div>
        )}
      </section>

      {pendingCount > 0 && !readOnly && (
        <div className="tray">
          <form
            className="tray-inner"
            onSubmit={(e) => {
              e.preventDefault();
              commit();
            }}
          >
            <span style={{ display: "flex", gap: 6, flex: "none" }}>
              <PendingChips pending={pending} />
            </span>
            <input
              className="input"
              style={{ flex: 1 }}
              placeholder={defaultMessage(pending)}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              aria-label="Commit message"
            />
            <button type="button" className="btn btn-ghost" onClick={() => { setPending(new Map()); setNewTables([]); }}>
              Discard
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              Commit to {branch}
            </button>
          </form>
        </div>
      )}

      {inspect && table && (
        <RowHistory
          table={table}
          rowId={inspect}
          refName={asOf ? asOf.hash : branch}
          onClose={() => setInspect(null)}
          onRestore={
            readOnly
              ? undefined
              : (data) => {
                  const base = baseRows.find((r) => r.row_id === inspect);
                  if (data === null) {
                    if (base) stage(table, inspect, { action: "delete", original: strip(base) });
                  } else if (base) stage(table, inspect, { action: "update", data, original: strip(base) });
                  else stage(table, inspect, { action: "insert", data });
                  toast("Version staged. Commit to keep it.", "info");
                }
          }
        />
      )}

      {dialog === "table" && (
        <NewTableDialog
          existing={tableList}
          onClose={() => setDialog(null)}
          onCreate={(name, cols) => {
            setNewTables((t) => [...t, name]);
            setTable(name);
            const data: RowData = {};
            cols.forEach((c) => (data[c] = ""));
            stage(name, `${name.replace(/s$/, "").slice(0, 4)}_1`, { action: "insert", data });
            setExtraCols((x) => ({ ...x, [name]: cols }));
            setDialog(null);
          }}
        />
      )}
      {dialog === "column" && table && (
        <NewColumnDialog
          existing={columns}
          onClose={() => setDialog(null)}
          onCreate={(col) => {
            setExtraCols((x) => ({ ...x, [table]: [...(x[table] ?? []), col] }));
            setDialog(null);
            toast(`Column ${col} added to the view. Fill a value and commit to save it.`, "info");
          }}
        />
      )}
    </div>
  );
}

function defaultMessage(p: Map<string, Pending>) {
  let i = 0, u = 0, d = 0;
  const tables = new Set<string>();
  p.forEach((v, k) => {
    tables.add(k.split("\u0000")[0]);
    if (v.action === "insert") i++;
    else if (v.action === "update") u++;
    else d++;
  });
  const parts = [i && `add ${i} row${i > 1 ? "s" : ""}`, u && `update ${u} row${u > 1 ? "s" : ""}`, d && `delete ${d} row${d > 1 ? "s" : ""}`].filter(Boolean);
  const s = parts.join(", ");
  return `${s.charAt(0).toUpperCase()}${s.slice(1)} in ${[...tables].join(", ")}`;
}

function PendingChips({ pending }: { pending: Map<string, Pending> }) {
  let i = 0, u = 0, d = 0;
  pending.forEach((v) => (v.action === "insert" ? i++ : v.action === "update" ? u++ : d++));
  return (
    <>
      {i > 0 && <span className="chip chip-add">+{i}</span>}
      {u > 0 && <span className="chip chip-mod">~{u}</span>}
      {d > 0 && <span className="chip chip-del">−{d}</span>}
    </>
  );
}

function RowHistory({
  table, rowId, refName, onClose, onRestore,
}: {
  table: string;
  rowId: string;
  refName: string;
  onClose: () => void;
  onRestore?: (data: RowData | null) => void;
}) {
  const { version } = useApp();
  const h = useLoad(() => api.rowHistory(table, rowId, refName), [table, rowId, refName, version]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const list: RowVersion[] = h.data?.history ?? [];
  return (
    <aside className="drawer" aria-label={`History of ${rowId}`}>
      <div className="panel-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="panel-title mono">{rowId}</div>
          <div className="hint">{table} · {list.length} versions</div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close history"><IconX /></button>
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {h.loading && !h.data ? <SkeletonRows /> : h.error ? <div style={{ padding: 16 }}><ErrorNote message={h.error} /></div> : (
          <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {list.map((v, i) => {
              const prev = list[i + 1]?.data ?? null;
              const changed = v.data && prev ? Object.keys({ ...v.data, ...prev }).filter((k) => JSON.stringify(v.data?.[k]) !== JSON.stringify(prev[k])) : [];
              return (
                <li key={v.commit_id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--rule-2)" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <Hash value={v.hash} />
                    {i === 0 && <span className="chip chip-head">current</span>}
                    {v.deleted && <span className="chip chip-del">deleted</span>}
                    {!v.deleted && !prev && i === list.length - 1 && <span className="chip chip-add">created</span>}
                    {v.storage === "delta" && <span className="chip" title="Stored as a compact delta by the storage optimizer">delta</span>}
                    <span style={{ flex: 1 }} />
                    {onRestore && i > 0 && (
                      <button className="btn btn-sm" onClick={() => onRestore(v.data)}>
                        <IconUndo /> Use this version
                      </button>
                    )}
                  </div>
                  <div style={{ fontWeight: 500, marginTop: 6 }}>{v.message}</div>
                  <div className="hint">{v.author} · {stamp(v.timestamp)} · on {v.branch_id}</div>
                  {v.data && (
                    <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 12px", marginTop: 8, fontSize: 13 }}>
                      {Object.entries(v.data).map(([k, val]) => (
                        <div key={k} style={{ display: "contents" }}>
                          <dt style={{ color: "var(--ink-3)" }}>{k}</dt>
                          <dd style={{ margin: 0, color: changed.includes(k) ? "var(--mod)" : undefined, fontWeight: changed.includes(k) ? 600 : 400 }}>
                            {cell(val) || <span style={{ color: "var(--ink-3)" }}>empty</span>}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </aside>
  );
}

function NewTableDialog({ existing, onClose, onCreate }: { existing: string[]; onClose: () => void; onCreate: (name: string, cols: string[]) => void }) {
  const [name, setName] = useState("");
  const [cols, setCols] = useState("name, email");
  const clean = name.trim();
  const err = !clean ? "" : !/^[A-Za-z_][A-Za-z0-9_]*$/.test(clean) ? "Use letters, digits and underscores, starting with a letter." : existing.includes(clean) ? "A table with this name exists." : "";
  const colList = cols.split(",").map((c) => c.trim()).filter(Boolean);
  return (
    <Dialog
      title="New table"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!clean || !!err || !colList.length} onClick={() => onCreate(clean, colList)}>Create table</button>
        </>
      }
    >
      <label className="field">
        <span>Table name</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="customers" />
        {err && <span className="hint" style={{ color: "var(--del)" }}>{err}</span>}
      </label>
      <label className="field">
        <span>Columns, separated by commas</span>
        <input className="input" value={cols} onChange={(e) => setCols(e.target.value)} />
      </label>
      <p className="hint">The table is saved when you commit its first row. Rows are schemaless, so you can add columns later.</p>
    </Dialog>
  );
}

function NewColumnDialog({ existing, onClose, onCreate }: { existing: string[]; onClose: () => void; onCreate: (col: string) => void }) {
  const [col, setCol] = useState("");
  const c = col.trim();
  const bad = !!c && (existing.includes(c) || c === "row_id");
  return (
    <Dialog
      title="Add column"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!c || bad} onClick={() => onCreate(c)}>Add column</button>
        </>
      }
    >
      <label className="field">
        <span>Column name</span>
        <input className="input" value={col} onChange={(e) => setCol(e.target.value)} placeholder="phone" onKeyDown={(e) => e.key === "Enter" && c && !bad && onCreate(c)} />
        {bad && <span className="hint" style={{ color: "var(--del)" }}>That column already exists.</span>}
      </label>
    </Dialog>
  );
}
