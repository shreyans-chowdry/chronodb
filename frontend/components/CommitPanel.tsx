"use client";

import { useState } from "react";
import { createCommit } from "@/lib/api";

interface CommitPanelProps {
  branchName: string;
  onCommitCreated: () => void;
}

export default function CommitPanel({
  branchName,
  onCommitCreated,
}: CommitPanelProps) {
  const [message, setMessage] = useState("");
  const [author, setAuthor] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  async function handleSubmit() {
    if (!message.trim() || !author.trim()) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      const commit = await createCommit(branchName, message.trim(), author.trim());
      setFeedback({
        type: "success",
        text: `Committed ${commit.hash.slice(0, 8)}`,
      });
      setMessage("");
      onCommitCreated();
      // Auto-clear success feedback
      setTimeout(() => setFeedback(null), 3000);
    } catch (err) {
      setFeedback({
        type: "error",
        text: err instanceof Error ? err.message : "Commit failed",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-zinc-700/40 bg-zinc-900/50 p-4 backdrop-blur-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-zinc-500">
        New Commit
      </h3>

      <div className="space-y-3">
        <input
          type="text"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          placeholder="Author name"
          className="w-full rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 outline-none transition-colors focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20"
        />

        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              handleSubmit();
            }
          }}
          placeholder="Commit message…"
          rows={2}
          className="w-full resize-none rounded-lg border border-zinc-700/50 bg-zinc-800/80 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 outline-none transition-colors focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20"
        />

        <div className="flex items-center gap-3">
          <button
            onClick={handleSubmit}
            disabled={submitting || !message.trim() || !author.trim()}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-violet-500/20 transition-all hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/30 disabled:opacity-40 disabled:shadow-none active:scale-95"
          >
            {submitting ? (
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            )}
            {submitting ? "Committing…" : "Commit"}
          </button>

          {/* Feedback toast */}
          {feedback && (
            <span
              className={`animate-in fade-in slide-in-from-left-2 text-xs font-medium ${
                feedback.type === "success"
                  ? "text-emerald-400"
                  : "text-red-400"
              }`}
            >
              {feedback.text}
            </span>
          )}
        </div>

        <p className="text-[10px] text-zinc-600">
          <kbd className="rounded border border-zinc-700 px-1 py-0.5 text-zinc-500">
            Ctrl+Enter
          </kbd>{" "}
          to commit
        </p>
      </div>
    </div>
  );
}
