"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, SqlResponse } from "@/lib/api";
import { useApp } from "@/lib/store";
import { cell, download, short, stamp, toCSV } from "@/lib/format";
import { Empty, ErrorNote, Hash } from "@/components/ui";
import { IconClock, IconDownload, IconPlay } from "@/components/icons";

const EXAMPLES: { label: string; sql: (ctx: { table: string; hash: string; branch: string }) => string }[] = [
  { label: "Browse a table", sql: ({ table }) => `SELECT * FROM ${table} LIMIT 50;` },
  { label: "Filter and sort", sql: ({ table }) => `SELECT * FROM ${table}\nWHERE status != 'Inactive'\nORDER BY row_id DESC;` },
  { label: "Time travel to a commit", sql: ({ table, hash }) => `SELECT * FROM ${table} AS OF COMMIT '${hash}';` },
  { label: "Time travel to a time", sql: ({ table }) => `SELECT * FROM ${table}\nAS OF TIMESTAMP '${new Date(Date.now() - 3600_000).toISOString().slice(0, 19)}';` },
  { label: "Read another branch", sql: ({ table }) => `SELECT * FROM ${table} AS OF BRANCH 'main';` },
  { label: "Aggregate", sql: ({ table }) => `SELECT status, COUNT(*) AS n FROM ${table}\nGROUP BY status ORDER BY n DESC;` },
  { label: "Write (one commit)", sql: ({ table }) => `UPDATE ${table} SET status = 'Reviewed'\nWHERE row_id = '${table.replace(/s$/, "").slice(0, 4)}_1';` },
  { label: "Inspect the repository", sql: () => `SHOW TABLES;\nSHOW BRANCHES;\nSHOW LOG LIMIT 5;` },
];

interface HistoryItem { sql: string; at: number; ok: boolean }

export default function SqlView() {
  const { branch, asOf, log, author, refresh, toast } = useApp();
  const [sql, setSql] = useState("");
  const [message, setMessage] = useState("");
  const [res, setRes] = useState<SqlResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tables, setTables] = useState<string[]>([]);
  const [past, setPast] = useState<HistoryItem[]>([]);
  const ta = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.tables(branch).then((t) => {
      setTables(t.tables);
      if (t.tables.length) setSql((s) => s || `SELECT * FROM ${t.tables[0]} LIMIT 50;`);
    }).catch(() => {});
  }, [branch]);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- browser-only state, read after hydration
      setPast(JSON.parse(localStorage.getItem("chronodb.sqlHistory") || "[]"));
    } catch { /* ignore */ }
  }, []);

  const ctx = useMemo(() => ({ table: tables[0] ?? "users", hash: short(log[Math.min(2, log.length - 1)]?.hash) || "abc1234", branch }), [tables, log, branch]);
  const isWrite = /\b(insert|update|delete)\b/i.test(sql);

  const run = async () => {
    if (!sql.trim()) return;
    let text = sql;
    // When the timeline points at the past, plain SELECTs read that snapshot
    if (asOf && !isWrite && !/\bAS\s+OF\b/i.test(text)) {
      text = text.replace(/\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)/gi, `FROM $1 AS OF COMMIT '${asOf.hash}'`);
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await api.sql(text, branch, author, message.trim() || undefined);
      setRes(r);
      if (r.commit) {
        toast(`Committed ${short(r.commit.hash)}: ${r.changes} row change${r.changes === 1 ? "" : "s"}`);
        setMessage("");
        refresh();
      }
      remember(sql, true);
    } catch (e) {
      setErr((e as Error).message);
      setRes(null);
      remember(sql, false);
    } finally {
      setBusy(false);
    }
  };

  const remember = (s: string, ok: boolean) => {
    setPast((p) => {
      const next = [{ sql: s, at: Date.now(), ok }, ...p.filter((x) => x.sql !== s)].slice(0, 25);
      try { localStorage.setItem("chronodb.sqlHistory", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 260px", gap: 20, alignItems: "start" }} className="sql-layout">
      <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
        {asOf && (
          <div className="past-banner">
            <IconClock width={18} height={18} style={{ color: "var(--past)" }} />
            <span>SELECT statements without their own <code className="mono">AS OF</code> read the snapshot at <Hash value={asOf.hash} />. Writes always go to the latest state of {branch}.</span>
          </div>
        )}
        <section className="panel" style={{ overflow: "hidden" }}>
          <textarea
            ref={ta}
            className="sql-editor code"
            spellCheck={false}
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                run();
              }
            }}
            aria-label="SQL"
            rows={Math.min(14, Math.max(5, sql.split("\n").length + 1))}
          />
          <div className="panel-head" style={{ borderTop: "1px solid var(--rule-2)", borderBottom: 0, flexWrap: "wrap" }}>
            {isWrite ? (
              <input
                className="input"
                style={{ flex: 1, minWidth: 200 }}
                placeholder="Commit message (optional)"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                aria-label="Commit message for writes"
              />
            ) : (
              <span className="hint" style={{ flex: 1 }}>
                Runs on <b style={{ color: "var(--ink)" }}>{branch}</b>. Writes in one run become one commit. <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to run.
              </span>
            )}
            <button className="btn btn-primary" onClick={run} disabled={busy || !sql.trim()}>
              <IconPlay /> {isWrite ? "Run and commit" : "Run"}
            </button>
          </div>
        </section>

        {err && <ErrorNote message={err} />}
        {res?.commit && (
          <div className="panel" style={{ padding: "10px 14px", display: "flex", gap: 10, alignItems: "center" }}>
            <span className="chip chip-head">committed</span>
            <Hash value={res.commit.hash} />
            <span style={{ flex: 1 }}>{res.commit.message}</span>
            <span className="hint">{res.changes} row changes</span>
          </div>
        )}
        {res?.results.map((r, i) => (
          <section key={i} className="panel" style={{ overflow: "hidden" }}>
            <div className="panel-head">
              <span className="panel-title">{r.statement}</span>
              {r.as_of && (
                <span className="chip chip-past" title={r.as_of.commit_message}>
                  as of {short(r.as_of.commit_hash)} · {stamp(r.as_of.timestamp)}
                </span>
              )}
              <span className="hint num">
                {r.kind === "rows" ? `${r.rows.length} rows` : `${r.affected} rows affected`} in {r.elapsed_ms.toFixed(1)} ms
              </span>
              <span style={{ flex: 1 }} />
              {r.kind === "rows" && r.rows.length > 0 && (
                <button className="btn btn-sm" onClick={() => download(`query-${i + 1}.csv`, toCSV(r.columns, r.rows))}>
                  <IconDownload /> CSV
                </button>
              )}
            </div>
            {r.kind === "rows" ? (
              r.rows.length ? (
                <div className="grid-wrap" style={{ maxHeight: 420, borderTop: 0 }}>
                  <table className="dgrid">
                    <thead><tr>{r.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                    <tbody>
                      {r.rows.map((row, j) => (
                        <tr key={j}>
                          {r.columns.map((c) => (
                            <td key={c}>
                              <span className="cell" data-type={typeof row[c] === "number" ? "number" : row[c] == null ? "null" : "text"}>
                                {row[c] === null ? "null" : cell(row[c])}
                              </span>
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No rows" />
              )
            ) : (
              <p style={{ padding: "12px 16px", margin: 0 }} className="hint">
                {r.affected} row{r.affected === 1 ? "" : "s"} staged and included in the commit above.
              </p>
            )}
          </section>
        ))}
      </div>

      <aside style={{ display: "grid", gap: 16 }} aria-label="Examples and recent queries">
        <section className="panel">
          <div className="panel-head"><span className="panel-title">Examples</span></div>
          <div style={{ padding: 6, display: "grid" }}>
            {EXAMPLES.map((ex) => (
              <button key={ex.label} className="nav-item" onClick={() => { setSql(ex.sql(ctx)); ta.current?.focus(); }}>
                {ex.label}
              </button>
            ))}
          </div>
        </section>
        {past.length > 0 && (
          <section className="panel">
            <div className="panel-head"><span className="panel-title">Recent</span></div>
            <div style={{ padding: 6, display: "grid", maxHeight: 320, overflowY: "auto" }}>
              {past.map((p) => (
                <button key={p.at} className="nav-item mono" style={{ fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", display: "block", textOverflow: "ellipsis", color: p.ok ? undefined : "var(--del)" }} onClick={() => setSql(p.sql)} title={p.sql}>
                  {p.sql.replace(/\s+/g, " ")}
                </button>
              ))}
            </div>
          </section>
        )}
      </aside>
    </div>
  );
}
