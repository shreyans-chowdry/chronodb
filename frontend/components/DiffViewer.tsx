"use client";

import { DiffRow, DiffResult } from "@/lib/api";

interface DiffViewerProps {
  diffData: DiffResult;
  commitA: string;
  commitB: string;
}

function StatusBadge({ status }: { status: DiffRow["status"] }) {
  const config = {
    added: {
      bg: "bg-emerald-100",
      text: "text-emerald-800",
      label: "Added",
    },
    deleted: {
      bg: "bg-red-100",
      text: "text-red-800",
      label: "Deleted",
    },
    modified: {
      bg: "bg-amber-100",
      text: "text-amber-800",
      label: "Modified",
    },
  }[status];

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${config.bg} ${config.text}`}
    >
      {config.label}
    </span>
  );
}

function CellValue({
  value,
  highlight,
  variant,
}: {
  value: unknown;
  highlight?: boolean;
  variant?: "added" | "deleted" | "modified";
}) {
  const displayValue = value === null || value === undefined ? "—" : String(value);

  let classes = "px-3 py-2 text-xs font-mono transition-colors ";
  if (highlight && variant === "deleted") {
    classes += "bg-red-50 text-red-700 line-through decoration-red-400";
  } else if (highlight && variant === "added") {
    classes += "bg-emerald-50 text-emerald-800 font-medium";
  } else if (highlight && variant === "modified") {
    classes += "bg-amber-50 text-amber-800 font-medium";
  } else {
    classes += "text-zinc-700";
  }

  return <td className={classes}>{displayValue}</td>;
}

export default function DiffViewer({ diffData, commitA, commitB }: DiffViewerProps) {
  const tableNames = Object.keys(diffData.tables);

  if (tableNames.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-zinc-200 bg-white p-12 text-center shadow-xs">
        <svg className="h-10 w-10 text-emerald-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <p className="text-sm font-semibold text-zinc-800">No differences found</p>
        <p className="text-xs text-zinc-500">
          The two commits contain identical data
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {tableNames.map((tableName) => {
        const tableData = diffData.tables[tableName];
        const rows = tableData.rows;

        // Gather all field names across all rows
        const allFields = new Set<string>();
        rows.forEach((row) => {
          if (row.data_a) Object.keys(row.data_a).forEach((k) => allFields.add(k));
          if (row.data_b) Object.keys(row.data_b).forEach((k) => allFields.add(k));
        });
        const fields = Array.from(allFields);

        const addedCount = rows.filter((r) => r.status === "added").length;
        const deletedCount = rows.filter((r) => r.status === "deleted").length;
        const modifiedCount = rows.filter((r) => r.status === "modified").length;

        return (
          <div
            key={tableName}
            className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs"
          >
            {/* Table header */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50/50 px-4 py-3">
              <div className="flex items-center gap-2">
                <svg className="h-4 w-4 text-violet-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 0 1-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0 1 12 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M13.125 12h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125M20.625 12c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5M12 14.625v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 14.625c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m0 0v1.5" />
                </svg>
                <h3 className="text-sm font-semibold text-zinc-900">{tableName}</h3>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                {addedCount > 0 && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800">
                    +{addedCount} added
                  </span>
                )}
                {deletedCount > 0 && (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-800">
                    -{deletedCount} deleted
                  </span>
                )}
                {modifiedCount > 0 && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                    ~{modifiedCount} modified
                  </span>
                )}
              </div>
            </div>

            {/* Side-by-side diff view */}
            <div className="grid grid-cols-2 divide-x divide-zinc-200">
              {/* Left header: Before */}
              <div className="border-b border-zinc-200 bg-zinc-50/80 px-4 py-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-red-500" />
                  <span className="text-[11px] font-semibold text-zinc-700">Before</span>
                  <span className="font-mono text-[10px] text-zinc-500">{commitA.slice(0, 8)}</span>
                </div>
              </div>
              {/* Right header: After */}
              <div className="border-b border-zinc-200 bg-zinc-50/80 px-4 py-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="text-[11px] font-semibold text-zinc-700">After</span>
                  <span className="font-mono text-[10px] text-zinc-500">{commitB.slice(0, 8)}</span>
                </div>
              </div>

              {/* Column headers - Left */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-zinc-200 bg-zinc-50/40">
                      <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                        row_id
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                        status
                      </th>
                      {fields.map((f) => (
                        <th key={f} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                          {f}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200">
                    {rows.map((row) => (
                      <tr
                        key={row.row_id}
                        className={`transition-colors ${
                          row.status === "deleted"
                            ? "bg-red-50/60"
                            : row.status === "added"
                              ? "bg-zinc-50/40 opacity-40"
                              : "hover:bg-zinc-50/50"
                        }`}
                      >
                        <td className="px-3 py-2 font-mono text-xs font-medium text-violet-700">
                          {row.row_id}
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge status={row.status} />
                        </td>
                        {fields.map((f) => {
                          const isChanged = row.changed_fields?.includes(f);
                          if (row.status === "added") {
                            return (
                              <CellValue key={f} value="—" />
                            );
                          }
                          return (
                            <CellValue
                              key={f}
                              value={row.data_a?.[f]}
                              highlight={isChanged || row.status === "deleted"}
                              variant={row.status === "deleted" ? "deleted" : "modified"}
                            />
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Column headers - Right */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-zinc-200 bg-zinc-50/40">
                      <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                        row_id
                      </th>
                      <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                        status
                      </th>
                      {fields.map((f) => (
                        <th key={f} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                          {f}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200">
                    {rows.map((row) => (
                      <tr
                        key={row.row_id}
                        className={`transition-colors ${
                          row.status === "added"
                            ? "bg-emerald-50/60"
                            : row.status === "deleted"
                              ? "bg-zinc-50/40 opacity-40"
                              : "hover:bg-zinc-50/50"
                        }`}
                      >
                        <td className="px-3 py-2 font-mono text-xs font-medium text-violet-700">
                          {row.row_id}
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge status={row.status} />
                        </td>
                        {fields.map((f) => {
                          const isChanged = row.changed_fields?.includes(f);
                          if (row.status === "deleted") {
                            return (
                              <CellValue key={f} value="—" />
                            );
                          }
                          return (
                            <CellValue
                              key={f}
                              value={row.data_b?.[f]}
                              highlight={isChanged || row.status === "added"}
                              variant={row.status === "added" ? "added" : "modified"}
                            />
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Footer stats */}
            <div className="border-t border-zinc-200 bg-zinc-50/30 px-4 py-2">
              <p className="text-[10px] text-zinc-500">
                {rows.length} changed row{rows.length !== 1 ? "s" : ""} · {fields.length} column{fields.length !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
