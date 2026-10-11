"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import { short, stamp, timeAgo } from "@/lib/format";
import { Commit } from "@/lib/api";

const MAX_TICKS = 48;

/**
 * The time-travel scrubber. Every commit in the branch's history is a stop on
 * the line; choosing one shows the whole workspace as it was at that commit.
 */
export default function Timeline() {
  const { log, logTotal, asOf, setAsOf, branch } = useApp();
  const [hover, setHover] = useState<number | null>(null);

  const commits = useMemo(() => [...log.slice(0, MAX_TICKS)].reverse(), [log]); // oldest → newest
  const hidden = Math.max(0, logTotal - commits.length);
  const n = commits.length;
  const head = commits[n - 1];
  const selIdx = asOf ? commits.findIndex((c) => c.id === asOf.id) : n - 1;

  const pos = (i: number) => (n <= 1 ? 100 : (i / (n - 1)) * 100);
  const pick = (c: Commit) => setAsOf(c.id === head?.id ? null : c);

  const onKey = (e: React.KeyboardEvent) => {
    if (!n) return;
    if (e.key === "ArrowLeft" && selIdx > 0) {
      e.preventDefault();
      pick(commits[selIdx - 1]);
    } else if (e.key === "ArrowRight" && selIdx < n - 1) {
      e.preventDefault();
      pick(commits[selIdx + 1]);
    } else if (e.key === "End") {
      setAsOf(null);
    }
  };

  const hovered = hover !== null ? commits[hover] : null;

  return (
    <div className="timeline">
      {hidden > 0 && (
        <span className="hint" title={`${hidden} older commits are in History`} style={{ flex: "none" }}>
          +{hidden}
        </span>
      )}
      <div
        className="tl-track"
        role="group"
        aria-label={`History of ${branch}. Use left and right arrows to move through commits.`}
        onKeyDown={onKey}
        onMouseLeave={() => setHover(null)}
      >
        <div className="tl-line" />
        <div className="tl-line-live" style={{ width: `${pos(Math.max(selIdx, 0))}%`, background: asOf ? "var(--past)" : "var(--head)" }} />
        {commits.map((c, i) => {
          const state = i === selIdx ? (asOf ? "selected" : "live") : asOf && i > selIdx ? "future" : "past";
          const tag = c.tags?.[0];
          return (
            <div key={c.id}>
              {tag && (
                <span className="tl-label" data-kind="tag" style={{ left: `${pos(i)}%` }}>
                  {tag}
                </span>
              )}
              <button
                type="button"
                className="tl-tick"
                style={{ left: `${pos(i)}%` }}
                data-state={state}
                data-merge={c.second_parent_id ? "true" : "false"}
                aria-label={`${c.message} by ${c.author}, ${stamp(c.timestamp)}`}
                aria-pressed={i === selIdx}
                tabIndex={i === selIdx ? 0 : -1}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                onClick={() => pick(c)}
              >
                <span className="tl-dot" />
              </button>
            </div>
          );
        })}
        {hovered && (
          <div
            className="tl-tip"
            style={{ left: `clamp(150px, ${pos(hover!)}%, calc(100% - 150px))` }}
          >
            <div style={{ fontWeight: 600 }}>{hovered.message}</div>
            <div style={{ opacity: 0.75 }}>
              {short(hovered.hash)} · {hovered.author} · {timeAgo(hovered.timestamp)}
            </div>
          </div>
        )}
      </div>
      <div className="tl-status" aria-live="polite">
        {asOf ? (
          <>
            <span>
              <strong style={{ color: "var(--past)" }}>As of {stamp(asOf.timestamp)}</strong>
              <br />
              read-only snapshot
            </span>
            <button className="btn btn-sm btn-past" onClick={() => setAsOf(null)}>
              Back to latest
            </button>
          </>
        ) : (
          <span>
            <strong>Latest</strong> on {branch}
            <br />
            {head ? `${short(head.hash)} · ${timeAgo(head.timestamp)}` : "no commits yet"}
          </span>
        )}
      </div>
    </div>
  );
}
