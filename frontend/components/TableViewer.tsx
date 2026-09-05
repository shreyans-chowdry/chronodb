"use client";

import { useState, useEffect, useMemo } from "react";
import { useTables, useTableData } from "@/hooks/useChronoDB";
import { createCommit } from "@/lib/api";
import ErrorState from "./ErrorState";

interface TableViewerProps {
  branchName: string;
  selectedTable: string | null;
  onSelectTable: (table: string | null) => void;
}

type ModalMode = "add" | "edit" | "delete_row" | "delete_table" | null;

export default function TableViewer({
  branchName,
  selectedTable,
  onSelectTable,
}: TableViewerProps) {
  const { data: tables, loading: tablesLoading, error: tablesError, refetch: refetchTables } = useTables(branchName);
  const { data: rows, loading: rowsLoading, error: rowsError, refetch: refetchRows } = useTableData(branchName, selectedTable);

  const [isNewTableModalOpen, setIsNewTableModalOpen] = useState(false);
  const [newTableName, setNewTableName] = useState("");

  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [newRowId, setNewRowId] = useState("");
  const [newRowData, setNewRowData] = useState<Record<string, string>>({});
  const [newFieldName, setNewFieldName] = useState("");
  
  // Commit state
  const [commitMsgInput, setCommitMsgInput] = useState("");
  const [authorInput, setAuthorInput] = useState("Developer");
  const [isSaving, setIsSaving] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);

  // Auto-select first table if none selected
  useEffect(() => {
    if (!selectedTable && tables && tables.length > 0) {
      onSelectTable(tables[0]);
    }
  }, [selectedTable, tables, onSelectTable]);

  // Derive column names from row data
  const columns = useMemo(() => {
    const allCols = new Set<string>();
    if (rows) {
      rows.forEach(row => {
        Object.keys(row).forEach(k => k !== "row_id" && allCols.add(k));
      });
    }
    return Array.from(allCols);
  }, [rows]);

  const handleCreateTable = () => {
    if (newTableName.trim()) {
      onSelectTable(newTableName.trim());
      setIsNewTableModalOpen(false);
      setNewTableName("");
    }
  };

  const handleOpenAddRow = () => {
    setNewRowId(`row_${Date.now().toString().slice(-4)}`);
    const initialData: Record<string, string> = {};
    columns.forEach(c => initialData[c] = "");
    setNewRowData(initialData);
    setCommitMsgInput(`Add row to ${selectedTable}`);
    setAuthorInput("Developer");
    setCommitError(null);
    setModalMode("add");
  };

  const handleOpenEditRow = (row: any) => {
    setNewRowId(row.row_id);
    const data: Record<string, string> = {};
    columns.forEach(c => data[c] = row[c] !== undefined && row[c] !== null ? String(row[c]) : "");
    setNewRowData(data);
    setCommitMsgInput(`Edit row ${row.row_id} in ${selectedTable}`);
    setAuthorInput("Developer");
    setCommitError(null);
    setModalMode("edit");
  };

  const handleOpenDeleteRow = (rowId: string) => {
    setNewRowId(rowId);
    setCommitMsgInput(`Delete row ${rowId} from ${selectedTable}`);
    setAuthorInput("Developer");
    setCommitError(null);
    setModalMode("delete_row");
  };

  const handleOpenDeleteTable = () => {
    setCommitMsgInput(`Delete table ${selectedTable}`);
    setAuthorInput("Developer");
    setCommitError(null);
    setModalMode("delete_table");
  };

  const handleSaveAction = async () => {
    if (!selectedTable) return;
    setIsSaving(true);
    setCommitError(null);
    
    try {
      let changes: any[] = [];
      
      if (modalMode === "add" || modalMode === "edit") {
        if (!newRowId.trim()) throw new Error("Row ID cannot be empty.");
        changes = [{
          action: modalMode === "add" ? "insert" : "update",
          table_name: selectedTable,
          row_id: newRowId.trim(),
          data: newRowData
        }];
      } else if (modalMode === "delete_row") {
        changes = [{
          action: "delete",
          table_name: selectedTable,
          row_id: newRowId,
          data: {}
        }];
      } else if (modalMode === "delete_table") {
        if (!rows || rows.length === 0) throw new Error("Table is already empty.");
        changes = rows.map(r => ({
          action: "delete",
          table_name: selectedTable,
          row_id: r.row_id,
          data: {}
        }));
      }

      await createCommit(
        branchName,
        commitMsgInput || `Action on ${selectedTable}`,
        authorInput || "User",
        changes
      );
      
      setModalMode(null);
      if (modalMode === "delete_table") {
        onSelectTable(null);
      }
      refetchTables();
      refetchRows();
    } catch (err) {
      setCommitError(err instanceof Error ? err.message : "Failed to commit changes");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 px-5 py-3 bg-white">
        <div className="flex items-center gap-4">
          <h2 className="text-sm font-semibold text-zinc-900">Data Viewer</h2>
          {/* Table selector */}
          {(tables?.length || selectedTable) ? (
            <div className="relative">
              <select
                value={selectedTable || ""}
                onChange={(e) => {
                  if (e.target.value === "--new--") setIsNewTableModalOpen(true);
                  else onSelectTable(e.target.value || null);
                }}
                className="appearance-none rounded-lg border border-zinc-200 bg-zinc-50 pl-3 pr-8 py-1.5 text-xs font-medium text-zinc-700 outline-none hover:border-zinc-300 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/20 cursor-pointer transition-colors"
              >
                {selectedTable && tables && !tables.includes(selectedTable) && (
                  <option key={selectedTable} value={selectedTable}>
                    {selectedTable}
                  </option>
                )}
                {tables?.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
                <option value="--new--">+ Create New Table</option>
              </select>
              <svg className="absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400 pointer-events-none" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
              </svg>
            </div>
          ) : (
            <button onClick={() => setIsNewTableModalOpen(true)} className="text-xs font-medium text-violet-600 hover:text-violet-700">
              + Create First Table
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {selectedTable && (
            <>
              <button
                onClick={handleOpenDeleteTable}
                className="flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition-all hover:bg-red-100 hover:border-red-300 active:scale-95 shadow-sm"
                title="Delete Table"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
                Delete Table
              </button>
              <button
                onClick={handleOpenAddRow}
                className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white transition-all hover:bg-zinc-800 active:scale-95 shadow-sm"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add Row
              </button>
            </>
          )}
          <button
            onClick={() => {
              refetchTables();
              refetchRows();
            }}
            className="rounded-lg border border-zinc-200 p-1.5 text-zinc-500 transition-colors hover:bg-zinc-50 hover:text-zinc-800"
            title="Refresh"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
            </svg>
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto bg-white">
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

        {!tablesError && !rowsError && (tablesLoading || (Boolean(selectedTable) && rowsLoading)) && (
          <div className="flex items-center justify-center p-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
          </div>
        )}

        {!tablesError && !rowsError && !tablesLoading && !selectedTable && (!tables || tables.length === 0) && (
          <div className="flex flex-col items-center justify-center p-16 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-50 text-violet-600 mb-4 shadow-xs">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
            </div>
            <h3 className="text-sm font-semibold text-zinc-900 mb-1">No Tables in this Branch</h3>
            <p className="text-xs text-zinc-500 max-w-xs mb-4">
              Get started by creating your first table or running a script in the SQL Runner tab.
            </p>
            <button
              onClick={() => setIsNewTableModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:bg-violet-500 transition-all active:scale-95"
            >
              + Create First Table
            </button>
          </div>
        )}

        {!tablesError && !rowsError && selectedTable && !rowsLoading && rows && (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50/80 sticky top-0 z-10">
                <th className="px-5 py-3 text-xs font-semibold text-zinc-500 uppercase tracking-wider w-40">
                  row_id
                </th>
                {columns.map((col) => (
                  <th
                    key={col}
                    className="px-5 py-3 text-xs font-semibold text-zinc-500 uppercase tracking-wider"
                  >
                    {col}
                  </th>
                ))}
                <th className="px-5 py-3 text-xs font-semibold text-zinc-500 uppercase tracking-wider text-right w-24">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length + 2} className="py-12 text-center text-sm text-zinc-400">
                    This table is empty. Click "Add Row" to create your first record.
                  </td>
                </tr>
              ) : (
                rows.map((row, idx) => (
                  <tr key={row.row_id || idx} className="hover:bg-zinc-50/50 transition-colors group">
                    <td className="px-5 py-3 text-xs font-mono font-medium text-zinc-900">
                      {row.row_id}
                    </td>
                    {columns.map((col) => (
                      <td key={col} className="px-5 py-3 text-sm text-zinc-600 truncate max-w-xs">
                        {row[col] !== undefined && row[col] !== null ? String(row[col]) : <span className="text-zinc-300 italic">null</span>}
                      </td>
                    ))}
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleOpenEditRow(row)}
                          className="p-1.5 text-zinc-400 hover:text-violet-600 hover:bg-violet-50 rounded-md transition-colors"
                          title="Edit Row"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
                          </svg>
                        </button>
                        <button
                          onClick={() => handleOpenDeleteRow(row.row_id)}
                          className="p-1.5 text-zinc-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                          title="Delete Row"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer */}
      {selectedTable && rows && (
        <div className="flex items-center justify-between border-t border-zinc-100 bg-white px-5 py-2">
          <p className="text-[11px] font-medium text-zinc-500">
            {rows.length} record{rows.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}

      {/* New Table Modal */}
      {isNewTableModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl animate-in zoom-in-95 overflow-hidden">
            <div className="px-6 py-5">
              <h3 className="text-lg font-semibold text-zinc-900 mb-1">Create Table</h3>
              <p className="text-xs text-zinc-500 mb-5">Enter a name for your new table. It will be initialized once you add the first row.</p>
              
              <div className="space-y-1">
                <label className="text-xs font-medium text-zinc-700">Table Name</label>
                <input
                  type="text"
                  value={newTableName}
                  onChange={(e) => setNewTableName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateTable()}
                  className="w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all"
                  placeholder="e.g. users, products"
                  autoFocus
                />
              </div>
            </div>
            <div className="border-t border-zinc-100 bg-zinc-50/50 px-6 py-4 flex gap-2 justify-end">
              <button
                onClick={() => setIsNewTableModalOpen(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-600 hover:bg-zinc-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateTable}
                disabled={!newTableName.trim()}
                className="px-4 py-2 rounded-lg bg-violet-600 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50 transition-all shadow-sm"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action Modal (Add/Edit/Delete Row & Delete Table) */}
      {modalMode !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/40 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="w-full max-w-md max-h-[90vh] flex flex-col rounded-2xl bg-white shadow-2xl animate-in zoom-in-95 overflow-hidden">
            <div className="px-6 py-5 border-b border-zinc-100">
              <h3 className="text-lg font-semibold text-zinc-900">
                {modalMode === "add" && `Add Row to ${selectedTable}`}
                {modalMode === "edit" && `Edit Row in ${selectedTable}`}
                {modalMode === "delete_row" && `Delete Row from ${selectedTable}`}
                {modalMode === "delete_table" && `Delete Table ${selectedTable}`}
              </h3>
            </div>
            
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
              {commitError && (
                <div className="rounded-lg bg-red-50 p-3 text-xs text-red-600 border border-red-100">
                  {commitError}
                </div>
              )}

              {modalMode === "delete_row" && (
                <p className="text-sm text-zinc-700">Are you sure you want to delete row <strong className="font-mono">{newRowId}</strong>? This will create a deletion commit.</p>
              )}

              {modalMode === "delete_table" && (
                <p className="text-sm text-zinc-700">Are you sure you want to completely delete table <strong>{selectedTable}</strong>? This will delete all {rows?.length || 0} rows.</p>
              )}

              {(modalMode === "add" || modalMode === "edit") && (
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-zinc-700 uppercase tracking-wider">row_id <span className="text-red-500">*</span></label>
                  <input
                    type="text"
                    value={newRowId}
                    disabled={modalMode === "edit"}
                    onChange={(e) => setNewRowId(e.target.value)}
                    className="w-full rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm font-mono outline-none focus:border-violet-500 focus:bg-white transition-all disabled:opacity-70"
                    placeholder="Unique identifier"
                  />
                </div>
              )}

              {(modalMode === "add" || modalMode === "edit") && (
                <div className="space-y-3 pt-2">
                  <h4 className="text-xs font-semibold text-zinc-700 uppercase tracking-wider border-b border-zinc-100 pb-2">Columns</h4>
                  
                  {Object.keys(newRowData).length === 0 && (
                    <p className="text-xs text-zinc-500 italic">No columns yet. Add one below.</p>
                  )}

                  {Object.keys(newRowData).map(col => (
                    <div key={col} className="space-y-1 relative group">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-medium text-zinc-600">{col}</label>
                        <button
                          onClick={() => {
                            const data = { ...newRowData };
                            delete data[col];
                            setNewRowData(data);
                          }}
                          className="text-[10px] text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          Remove
                        </button>
                      </div>
                      <input
                        type="text"
                        value={newRowData[col] || ""}
                        onChange={(e) => setNewRowData({...newRowData, [col]: e.target.value})}
                        className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/20 transition-all"
                        placeholder="..."
                      />
                    </div>
                  ))}

                  <div className="flex gap-2 items-center mt-4 border-t border-zinc-100 pt-3">
                    <input 
                      type="text" 
                      value={newFieldName}
                      onChange={e => setNewFieldName(e.target.value)}
                      placeholder="New column name"
                      className="flex-1 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs outline-none focus:border-violet-500 transition-all"
                    />
                    <button 
                      onClick={() => {
                        if (newFieldName.trim() && newFieldName.trim().toLowerCase() !== "row_id") {
                          setNewRowData({ ...newRowData, [newFieldName.trim()]: "" });
                          setNewFieldName("");
                        }
                      }}
                      disabled={!newFieldName.trim()}
                      className="rounded-lg bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-200 disabled:opacity-50 transition-colors"
                    >
                      Add Field
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-3 pt-4">
                <h4 className="text-xs font-semibold text-zinc-700 uppercase tracking-wider border-b border-zinc-100 pb-2">Commit Details</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-zinc-600">Author</label>
                    <input
                      type="text"
                      value={authorInput}
                      onChange={(e) => setAuthorInput(e.target.value)}
                      className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-violet-500 transition-all"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-zinc-600">Message</label>
                    <input
                      type="text"
                      value={commitMsgInput}
                      onChange={(e) => setCommitMsgInput(e.target.value)}
                      className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-violet-500 transition-all"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-zinc-100 bg-zinc-50/50 px-6 py-4 flex gap-2 justify-end shrink-0">
              <button
                onClick={() => setModalMode(null)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-600 hover:bg-zinc-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAction}
                disabled={isSaving}
                className={`px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50 transition-all shadow-sm flex items-center gap-2 ${
                  modalMode?.startsWith("delete") ? "bg-red-600 hover:bg-red-700" : "bg-zinc-900 hover:bg-zinc-800"
                }`}
              >
                {isSaving && <div className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />}
                {isSaving ? "Committing..." : modalMode?.startsWith("delete") ? "Delete & Commit" : "Save & Commit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
