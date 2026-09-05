"use client";

import { useState } from "react";
import {
  MergeConflict,
  MergeResolution,
  MergeResponse,
  executeMerge,
} from "@/lib/api";

interface MergePanelProps {
  targetBranch: string;
  sourceBranch: string;
  conflicts: MergeConflict[];
  onMergeComplete: (result: MergeResponse) => void;
}

type ChoiceType = "target" | "source";

export default function MergePanel({
  targetBranch,
  sourceBranch,
  conflicts,
  onMergeComplete,
}: MergePanelProps) {
  const [choices, setChoices] = useState<Record<string, ChoiceType>>({});
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allResolved = conflicts.every(
    (c) => choices[`${c.table_name}:${c.row_id}`] !== undefined
  );

  const handleChoice = (key: string, choice: ChoiceType) => {
    setChoices((prev) => ({ ...prev, [key]: choice }));
  };

  const handleMerge = async () => {
    setMerging(true);
    setError(null);
    try {
      const resolutions: MergeResolution[] = conflicts.map((c) => {
        const key = `${c.table_name}:${c.row_id}`;
        const choice = choices[key];
        return {
          key,
          data: choice === "target" ? c.data_target : c.data_source,
        };
      });

      const result = await executeMerge(
        targetBranch,
        sourceBranch,
        "dashboard-user",
        resolutions
      );
      onMergeComplete(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setMerging(false);
    }
  };

  // Gather all field names across all conflicts
  const allFields = new Set<string>();
  conflicts.forEach((c) => {
    if (c.data_ancestor) Object.keys(c.data_ancestor).forEach((k) => allFields.add(k));
    if (c.data_target) Object.keys(c.data_target).forEach((k) => allFields.add(k));
    if (c.data_source) Object.keys(c.data_source).forEach((k) => allFields.add(k));
  });
  const fields = Array.from(allFields);

  return (
    <div className="overflow-hidden rounded-xl border border-amber-300 bg-white shadow-xs animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-amber-200 bg-amber-50/80 px-4 py-3">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
          <h3 className="text-sm font-semibold text-amber-900">
            Merge Conflicts — {conflicts.length} conflict{conflicts.length !== 1 ? "s" : ""} detected
          </h3>
        </div>
        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[10px] font-medium text-amber-800">
          {Object.keys(choices).length}/{conflicts.length} resolved
        </span>
      </div>

      {/* Conflict description */}
      <div className="border-b border-zinc-200 bg-zinc-50/30 px-4 py-2.5">
        <p className="text-xs text-zinc-600">
          Both <span className="font-semibold text-violet-700">{targetBranch}</span> and{" "}
          <span className="font-semibold text-violet-700">{sourceBranch}</span> modified the
          following rows. Choose which version to keep for each conflict.
        </p>
      </div>

      {/* Conflicts list */}
      <div className="divide-y divide-zinc-200">
        {conflicts.map((conflict) => {
          const key = `${conflict.table_name}:${conflict.row_id}`;
          const currentChoice = choices[key];

          return (
            <div key={key} className="p-4 space-y-3">
              {/* Conflict row header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="rounded border border-zinc-200 bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-700">
                    {conflict.table_name}
                  </span>
                  <span className="font-mono text-xs font-semibold text-violet-700">
                    {conflict.row_id}
                  </span>
                </div>
                {currentChoice && (
                  <span className="text-[10px] font-semibold text-emerald-700">✓ Resolved</span>
                )}
              </div>

              {/* Side-by-side options */}
              <div className="grid grid-cols-2 gap-3">
                {/* Ours (target) */}
                <button
                  onClick={() => handleChoice(key, "target")}
                  className={`group rounded-lg border p-3 text-left transition-all ${
                    currentChoice === "target"
                      ? "border-violet-600 bg-violet-50/70 ring-1 ring-violet-500 shadow-xs"
                      : "border-zinc-200 bg-zinc-50/50 hover:border-zinc-300 hover:bg-zinc-100/60"
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                      Ours ({targetBranch})
                    </span>
                    <div
                      className={`h-4 w-4 rounded-full border-2 transition-colors ${
                        currentChoice === "target"
                          ? "border-violet-600 bg-violet-600"
                          : "border-zinc-400 group-hover:border-zinc-500"
                      }`}
                    >
                      {currentChoice === "target" && (
                        <svg className="h-full w-full text-white" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                        </svg>
                      )}
                    </div>
                  </div>
                  <div className="space-y-1">
                    {conflict.data_target ? (
                      fields.map((f) => (
                        <div key={f} className="flex items-center gap-2 text-xs">
                          <span className="w-20 shrink-0 truncate text-zinc-500">{f}:</span>
                          <span className="truncate font-mono font-medium text-zinc-800">
                            {String(conflict.data_target?.[f] ?? "—")}
                          </span>
                        </div>
                      ))
                    ) : (
                      <span className="text-xs italic text-red-600">(deleted)</span>
                    )}
                  </div>
                </button>

                {/* Theirs (source) */}
                <button
                  onClick={() => handleChoice(key, "source")}
                  className={`group rounded-lg border p-3 text-left transition-all ${
                    currentChoice === "source"
                      ? "border-emerald-600 bg-emerald-50/70 ring-1 ring-emerald-500 shadow-xs"
                      : "border-zinc-200 bg-zinc-50/50 hover:border-zinc-300 hover:bg-zinc-100/60"
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                      Theirs ({sourceBranch})
                    </span>
                    <div
                      className={`h-4 w-4 rounded-full border-2 transition-colors ${
                        currentChoice === "source"
                          ? "border-emerald-600 bg-emerald-600"
                          : "border-zinc-400 group-hover:border-zinc-500"
                      }`}
                    >
                      {currentChoice === "source" && (
                        <svg className="h-full w-full text-white" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                        </svg>
                      )}
                    </div>
                  </div>
                  <div className="space-y-1">
                    {conflict.data_source ? (
                      fields.map((f) => (
                        <div key={f} className="flex items-center gap-2 text-xs">
                          <span className="w-20 shrink-0 truncate text-zinc-500">{f}:</span>
                          <span className="truncate font-mono font-medium text-zinc-800">
                            {String(conflict.data_source?.[f] ?? "—")}
                          </span>
                        </div>
                      ))
                    ) : (
                      <span className="text-xs italic text-red-600">(deleted)</span>
                    )}
                  </div>
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Error display */}
      {error && (
        <div className="border-t border-red-200 bg-red-50 px-4 py-2.5">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center justify-between border-t border-zinc-200 bg-zinc-50/50 px-4 py-3">
        <p className="text-[11px] text-zinc-600">
          {allResolved
            ? "All conflicts resolved — ready to merge"
            : `Resolve ${conflicts.length - Object.keys(choices).length} remaining conflict${
                conflicts.length - Object.keys(choices).length !== 1 ? "s" : ""
              }`}
        </p>
        <button
          onClick={handleMerge}
          disabled={!allResolved || merging}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all active:scale-95 ${
            allResolved
              ? "bg-violet-600 text-white shadow-md shadow-violet-500/20 hover:bg-violet-500"
              : "cursor-not-allowed bg-zinc-200 text-zinc-400"
          }`}
        >
          {merging ? (
            <>
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Merging…
            </>
          ) : (
            <>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
              Finalize Merge
            </>
          )}
        </button>
      </div>
    </div>
  );
}
