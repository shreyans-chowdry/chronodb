"use client";

import { useState } from "react";
import { Branch } from "@/lib/api";
import { createBranch, checkoutBranch } from "@/lib/api";
import StatusBadge from "./StatusBadge";

interface BranchSwitcherProps {
  branches: Branch[];
  activeBranch: string;
  onBranchChange: (branchName: string) => void;
  onRefresh: () => void;
}

export default function BranchSwitcher({
  branches,
  activeBranch,
  onBranchChange,
  onRefresh,
}: BranchSwitcherProps) {
  const [showCreate, setShowCreate] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  async function handleCreate() {
    if (!newBranchName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await createBranch(newBranchName.trim(), activeBranch);
      await checkoutBranch(newBranchName.trim());
      onBranchChange(newBranchName.trim());
      onRefresh();
      setNewBranchName("");
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create branch");
    } finally {
      setCreating(false);
    }
  }

  async function handleSwitch(name: string) {
    setIsOpen(false);
    try {
      await checkoutBranch(name);
      onBranchChange(name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to switch branch");
    }
  }

  return (
    <div className="relative">
      {/* Branch selector button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-800/60 px-3 py-2 text-sm font-medium text-zinc-200 backdrop-blur-sm transition-all hover:border-violet-500/40 hover:bg-zinc-700/60"
      >
        {/* Git branch icon */}
        <svg className="h-4 w-4 text-violet-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 3v12m0 0a3 3 0 1 0 3 3M6 15a3 3 0 0 1 3 3m0 0h6a3 3 0 0 0 3-3V6a3 3 0 0 0-3-3H9a3 3 0 0 0-3 3v6" />
        </svg>
        <span>{activeBranch}</span>
        <svg className={`h-3.5 w-3.5 text-zinc-500 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-64 overflow-hidden rounded-xl border border-zinc-700/50 bg-zinc-900/95 shadow-2xl shadow-black/50 backdrop-blur-xl">
          <div className="border-b border-zinc-700/50 px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
              Branches
            </p>
          </div>
          <div className="max-h-48 overflow-y-auto p-1">
            {branches.map((b) => (
              <button
                key={b.id}
                onClick={() => handleSwitch(b.name)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  b.name === activeBranch
                    ? "bg-violet-500/10 text-violet-300"
                    : "text-zinc-300 hover:bg-zinc-800/80 hover:text-zinc-100"
                }`}
              >
                <span className="flex-1 truncate">{b.name}</span>
                {b.name === activeBranch && (
                  <StatusBadge label="active" variant="success" />
                )}
              </button>
            ))}
          </div>

          {/* Create branch */}
          <div className="border-t border-zinc-700/50 p-2">
            {!showCreate ? (
              <button
                onClick={() => setShowCreate(true)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-zinc-400 transition-colors hover:bg-zinc-800/80 hover:text-zinc-200"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                New branch
              </button>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={newBranchName}
                  onChange={(e) => setNewBranchName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  placeholder="branch-name"
                  className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20"
                  autoFocus
                />
                <div className="flex gap-1.5">
                  <button
                    onClick={handleCreate}
                    disabled={creating || !newBranchName.trim()}
                    className="flex-1 rounded-lg bg-violet-600/80 px-3 py-1.5 text-xs font-medium text-white transition-all hover:bg-violet-600 disabled:opacity-40 active:scale-95"
                  >
                    {creating ? "Creating…" : "Create"}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreate(false);
                      setNewBranchName("");
                      setError(null);
                    }}
                    className="rounded-lg px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200"
                  >
                    Cancel
                  </button>
                </div>
                {error && (
                  <p className="text-xs text-red-400">{error}</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Backdrop to close dropdown */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setIsOpen(false)}
        />
      )}
    </div>
  );
}
