"use client";

import { useTables, useTableData } from "@/hooks/useChronoDB";
import ErrorState from "./ErrorState";

interface TableViewerProps {
  branchName: string;
  selectedTable: string | null;
  onSelectTable: (table: string | null) => void;
}

function SkeletonRow({ cols }: { cols: number }) {
  return (
    <tr className="animate-pulse">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 w-full rounded bg-zinc-700/50" />
        </td>
      ))}
    </tr>
  );
}

export default function TableViewer({
  branchName,
  selectedTable,
  onSelectTable,
}: TableViewerProps) {
  const {
    data: tables,
    loading: tablesLoading,
    error: tablesError,
    refetch: refetchTables,
  } = useTables(branchName);

  const {
    data: rows,
    loading: rowsLoading,
    error: rowsError,
    refetch: refetchRows,
  } = useTableData(branchName, selectedTable);

  // Auto-select first table if none selected
  if (!selectedTable && tables && tables.length > 0) {
    onSelectTable(tables[0]);
  }

  // Derive column names from row data
  const columns =
    rows && rows.length > 0
      ? Object.keys(rows[0]).filter((k) => k !== "row_id")
      : [];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-700/40 bg-zinc-900/50 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-700/40 px-4 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-200">Data Viewer</h2>
          {/* Table selector */}
          {tables && tables.length > 0 && (
            <select
              value={selectedTable || ""}
              onChange={(e) => onSelectTable(e.target.value || null)}
              className="rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-2.5 py-1 text-xs text-zinc-300 outline-none focus:border-violet-500/50"
            >
              {tables.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          )}
        </div>
        <button
          onClick={() => {
            refetchTables();
            refetchRows();
          }}
          className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
          title="Refresh"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {tablesError && (
          <div className="p-4">
            <ErrorState message={tablesError} onRetry={refetchTables} />
          </div>
        )}

        {rowsError && (
          <div className="p-4">
            <ErrorState message={rowsError} onRetry={refetchRows} />
          </div>
        )}

        {!tablesError && !rowsError && tablesLoading && (
          <div className="flex items-center justify-center p-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
          </div>
        )}

        {!tablesError && tables && tables.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
            <svg className="h-10 w-10 text-zinc-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
            </svg>
            <p className="text-sm text-zinc-500">No tables yet</p>
            <p className="text-xs text-zinc-600">
              Create a commit with data to see tables here
            </p>
          </div>
        )}

        {!tablesError && !rowsError && selectedTable && !rowsLoading && rows && (
          <>
            {rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
                <p className="text-sm text-zinc-500">Table is empty</p>
              </div>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-zinc-700/40 bg-zinc-800/30">
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
                      row_id
                    </th>
                    {columns.map((col) => (
                      <th
                        key={col}
                        className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-zinc-500"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {rowsLoading
                    ? Array.from({ length: 3 }).map((_, i) => (
                        <SkeletonRow key={i} cols={columns.length + 1} />
                      ))
                    : rows.map((row, idx) => (
                        <tr
                          key={row.row_id || idx}
                          className="transition-colors hover:bg-zinc-800/30"
                        >
                          <td className="px-4 py-2.5 font-mono text-xs text-violet-400/80">
                            {row.row_id}
                          </td>
                          {columns.map((col) => (
                            <td
                              key={col}
                              className="px-4 py-2.5 text-sm text-zinc-300"
                            >
                              {String(row[col] ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      {rows && rows.length > 0 && (
        <div className="border-t border-zinc-700/40 px-4 py-2">
          <p className="text-[10px] text-zinc-500">
            {rows.length} row{rows.length !== 1 ? "s" : ""} ·{" "}
            {columns.length} column{columns.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
