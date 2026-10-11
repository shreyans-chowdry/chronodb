"use client";

import { useMemo, useState } from "react";
import { api, Branch, Commit, Tag } from "@/lib/api";
import { useApp, useLoad } from "@/lib/store";
import { short, timeAgo } from "@/lib/format";
import { Empty, ErrorNote, SkeletonRows } from "@/components/ui";

const LANE = 26;
const ROW = 44;
const PAD = 18;
const LANE_COLORS = ["#0f766e", "#2559c7", "#a8670f", "#9b3fb5", "#b42318", "#3d7d1f", "#0e7490", "#7c5a1b"];

interface Placed { c: Commit; lane: number; row: number }

/**
 * Commit DAG drawn as a lane graph, newest at the top. Each branch keeps a
 * lane; merge commits draw a second edge from the merged branch's lane.
 */
function layout(commits: Commit[], branches: Branch[]) {
  const sorted = [...commits].sort((a, b) => b.id - a.id); // newest first
  const laneOf = new Map<string, number>();
  const order = ["main", ...branches.map((b) => b.name).filter((n) => n !== "main")];
  order.forEach((n) => laneOf.set(n, laneOf.size));
  sorted.forEach((c) => !laneOf.has(c.branch_id) && laneOf.set(c.branch_id, laneOf.size));
  const placed = new Map<number, Placed>();
  sorted.forEach((c, row) => placed.set(c.id, { c, lane: laneOf.get(c.branch_id) ?? 0, row }));
  return { placed, sorted, lanes: laneOf };
}

export default function GraphView() {
  const { version, setBranch, setView, setFocus, branch } = useApp();
  const g = useLoad(() => api.graph(), [version]);
  const [hover, setHover] = useState<number | null>(null);

  const data = useMemo(() => (g.data ? layout(g.data.commits, g.data.branches) : null), [g.data]);
  if (g.error) return <ErrorNote message={g.error} />;
  if (!data || !g.data) return <div className="panel"><SkeletonRows rows={10} /></div>;
  if (!data.sorted.length) return <Empty title="No commits yet" />;

  const { placed, sorted, lanes } = data;
  const heads = new Map<number, string[]>();
  g.data.branches.forEach((b) => heads.set(b.head_commit_id, [...(heads.get(b.head_commit_id) ?? []), b.name]));
  const tags = new Map<number, Tag[]>();
  g.data.tags.forEach((t) => tags.set(t.commit_id, [...(tags.get(t.commit_id) ?? []), t]));

  const laneCount = lanes.size;
  const width = PAD * 2 + laneCount * LANE;
  const height = PAD * 2 + sorted.length * ROW;
  const x = (lane: number) => PAD + lane * LANE + LANE / 2;
  const y = (row: number) => PAD + row * ROW + ROW / 2;
  const color = (lane: number) => LANE_COLORS[lane % LANE_COLORS.length];

  const edges: { d: string; color: string; dashed: boolean; key: string }[] = [];
  sorted.forEach((c) => {
    const me = placed.get(c.id)!;
    [c.parent_id, c.second_parent_id].forEach((pid, idx) => {
      if (pid == null) return;
      const p = placed.get(pid);
      if (!p) return;
      const x1 = x(me.lane), y1 = y(me.row), x2 = x(p.lane), y2 = y(p.row);
      // Same lane: straight line. Branch-off (first parent elsewhere): run down
      // the child's lane, then curve into the parent. Merge: leave the commit
      // towards the merged branch's lane and run down it.
      const d = x1 === x2
        ? `M${x1},${y1} L${x2},${y2}`
        : idx === 0
          ? `M${x1},${y1} L${x1},${y2 - ROW} C${x1},${y2 - ROW * 0.2} ${x2},${y2 - ROW * 0.8} ${x2},${y2}`
          : `M${x1},${y1} C${x1},${y1 + ROW * 0.8} ${x2},${y1 + ROW * 0.2} ${x2},${y1 + ROW} L${x2},${y2}`;
      edges.push({ d, color: color(idx === 0 ? me.lane : p.lane), dashed: idx === 1, key: `${c.id}-${pid}` });
    });
  });

  const laneNames = [...lanes.entries()].sort((a, b) => a[1] - b[1]);

  return (
    <section className="panel" style={{ overflow: "hidden" }}>
      <div className="panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="panel-title">{sorted.length} commits on {g.data.branches.length} branches</span>
        <span style={{ flex: 1 }} />
        {laneNames.map(([name, lane]) => {
          const live = g.data!.branches.some((b) => b.name === name);
          return (
            <button key={name} className="chip" style={{ borderColor: color(lane), color: live ? color(lane) : "var(--ink-3)", cursor: live ? "pointer" : "default", background: "transparent" }}
              onClick={() => live && setBranch(name)} title={live ? `Switch to ${name}` : `${name} was deleted`}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: color(lane) }} /> {name}{!live && " (deleted)"}
            </button>
          );
        })}
      </div>
      <div style={{ overflow: "auto", maxHeight: "calc(100dvh - 200px)" }}>
        <div style={{ display: "grid", gridTemplateColumns: `${width}px minmax(0,1fr)`, minWidth: width + 420 }}>
          <svg width={width} height={height} role="img" aria-label="Commit graph">
            {laneNames.map(([, lane]) => (
              <line key={lane} x1={x(lane)} x2={x(lane)} y1={PAD} y2={height - PAD} stroke={color(lane)} strokeOpacity={0.08} strokeWidth={LANE - 6} />
            ))}
            {edges.map((e) => (
              <path key={e.key} d={e.d} fill="none" stroke={e.color} strokeWidth={2} strokeDasharray={e.dashed ? "5 4" : undefined} strokeOpacity={0.85} />
            ))}
            {sorted.map((c) => {
              const p = placed.get(c.id)!;
              const isMerge = c.second_parent_id != null;
              const r = hover === c.id ? 7 : 5.5;
              return isMerge ? (
                <rect key={c.id} x={x(p.lane) - r} y={y(p.row) - r} width={r * 2} height={r * 2} transform={`rotate(45 ${x(p.lane)} ${y(p.row)})`} fill="var(--panel)" stroke={color(p.lane)} strokeWidth={2.5} />
              ) : (
                <circle key={c.id} cx={x(p.lane)} cy={y(p.row)} r={r} fill={heads.has(c.id) ? color(p.lane) : "var(--panel)"} stroke={color(p.lane)} strokeWidth={2.5} />
              );
            })}
          </svg>
          <ol style={{ listStyle: "none", margin: 0, padding: `${PAD}px 0` }}>
            {sorted.map((c) => {
              const p = placed.get(c.id)!;
              return (
                <li key={c.id} style={{ height: ROW }}>
                  <button
                    className="commit-row"
                    style={{ gridTemplateColumns: "minmax(0,1fr) auto", height: ROW, padding: "0 14px", alignItems: "center", borderBottom: 0, background: hover === c.id ? "var(--panel-2)" : undefined }}
                    onMouseEnter={() => setHover(c.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => {
                      if (g.data!.branches.some((b) => b.name === c.branch_id) && c.branch_id !== branch) setBranch(c.branch_id);
                      setFocus(c.hash);
                      setView("history");
                    }}
                  >
                    <span style={{ minWidth: 0, display: "flex", gap: 8, alignItems: "center" }}>
                      {heads.get(c.id)?.map((h) => <span key={h} className="chip" style={{ background: color(lanes.get(h) ?? p.lane), color: "#fff", borderColor: "transparent" }}>{h}</span>)}
                      {tags.get(c.id)?.map((t) => <span key={t.name} className="chip chip-tag">{t.name}</span>)}
                      <span className="commit-msg">{c.message}</span>
                    </span>
                    <span className="commit-meta" style={{ marginTop: 0, flexWrap: "nowrap" }}>
                      <span className="mono">{short(c.hash)}</span>
                      <span>{c.author}</span>
                      <span style={{ minWidth: 90, textAlign: "right" }}>{timeAgo(c.timestamp)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}
