"use client";

import { DiffResult, DiffRow, RowData } from "@/lib/api";
import { cell } from "@/lib/format";
import { Empty } from "./ui";

function columnsOf(rows: DiffRow[]): string[] {
  const set = new Set<string>();
  rows.forEach((r) => {
    Object.keys(r.data_a || {}).forEach((k) => set.add(k));
    Object.keys(r.data_b || {}).forEach((k) => set.add(k));
  });
  return [...set];
}

const label: Record<DiffRow["status"], string> = { added: "Added", deleted: "Removed", modified: "Changed" };
const chip: Record<DiffRow["status"], string> = { added: "chip-add", deleted: "chip-del", modified: "chip-mod" };

function Value({ row, col }: { row: DiffRow; col: string }) {
  const a = (row.data_a as RowData | null)?.[col];
  const b = (row.data_b as RowData | null)?.[col];
  if (row.status === "added") return <span className="diff-new">{cell(b)}</span>;
  if (row.status === "deleted") return <span className="diff-old">{cell(a)}</span>;
  if (row.changed_fields?.includes(col)) {
    return (
      <span>
        {a !== undefined && <span className="diff-old">{cell(a)}</span>}
        {a !== undefined && b !== undefined && " "}
        {b !== undefined && <span className="diff-new">{cell(b)}</span>}
      </span>
    );
  }
  return <span style={{ color: "var(--ink-3)" }}>{cell(b ?? a)}</span>;
}

export function DiffSummary({ diff }: { diff: DiffResult }) {
  let add = 0, del = 0, mod = 0;
  Object.values(diff.tables).forEach((t) =>
    t.rows.forEach((r) => (r.status === "added" ? add++ : r.status === "deleted" ? del++ : mod++)),
  );
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      {add > 0 && <span className="chip chip-add">+{add} added</span>}
      {mod > 0 && <span className="chip chip-mod">{mod} changed</span>}
      {del > 0 && <span className="chip chip-del">−{del} removed</span>}
      {add + del + mod === 0 && <span className="chip">no row changes</span>}
    </span>
  );
}

export default function DiffView({ diff, emptyText = "The two versions hold identical data." }: { diff: DiffResult; emptyText?: string }) {
  const tables = Object.entries(diff.tables).sort(([a], [b]) => a.localeCompare(b));
  if (!tables.length) return <Empty title="No differences">{emptyText}</Empty>;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {tables.map(([name, t]) => {
        const cols = columnsOf(t.rows);
        return (
          <section key={name} className="panel" style={{ overflow: "hidden" }}>
            <div className="panel-head">
              <span className="panel-title">{name}</span>
              <DiffSummary diff={{ tables: { [name]: t } }} />
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="diff-table">
                <thead>
                  <tr>
                    <th>row_id</th>
                    <th>Change</th>
                    {cols.map((c) => <th key={c}>{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r) => (
                    <tr key={r.row_id} className={`diff-row-${r.status}`}>
                      <td className="mono">{r.row_id}</td>
                      <td><span className={`chip ${chip[r.status]}`}>{label[r.status]}</span></td>
                      {cols.map((c) => <td key={c}><Value row={r} col={c} /></td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}
