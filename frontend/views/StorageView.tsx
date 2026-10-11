"use client";

import { useState } from "react";
import { api, GcReport, OptimizeReport } from "@/lib/api";
import { useApp, useLoad } from "@/lib/store";
import { bytes, timeAgo } from "@/lib/format";
import { Dialog, ErrorNote, Hash, SkeletonRows } from "@/components/ui";
import { IconBranch, IconTag, IconTrash } from "@/components/icons";

export default function StorageView() {
  const { version, refresh, toast, branches, branch, setBranch } = useApp();
  const stats = useLoad(() => api.stats(), [version]);
  const tags = useLoad(() => api.tags(), [version]);
  const [threshold, setThreshold] = useState(5);
  const [opt, setOpt] = useState<OptimizeReport | null>(null);
  const [gc, setGc] = useState<GcReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [rename, setRename] = useState<{ from: string; to: string } | null>(null);

  const run = async <T,>(key: string, fn: () => Promise<T>, done: (r: T) => void) => {
    setBusy(key);
    try {
      done(await fn());
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  const s = stats.data;
  const st = s?.storage;
  const totalVersions = st ? st.full_snapshots + st.deltas + st.tombstones : 0;

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {stats.error && <ErrorNote message={stats.error} onRetry={refresh} />}
      {!s ? <div className="panel"><SkeletonRows /></div> : (
        <section className="panel" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          {[
            [s.commits, "commits"],
            [s.branches, "branches"],
            [s.tables, "tables"],
            [s.row_keys, "row keys"],
            [bytes(s.live_bytes), `in use of ${bytes(s.file_bytes)} file`],
            [bytes(s.wal_bytes), "write-ahead log"],
          ].map(([v, l], i) => (
            <div key={i} className="stat" style={{ borderRight: "1px solid var(--rule-2)" }}>
              <div className="stat-value">{v}</div>
              <div className="stat-label">{l}</div>
            </div>
          ))}
        </section>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 20, alignItems: "start" }}>
        <section className="panel">
          <div className="panel-head"><span className="panel-title">Row versions</span></div>
          <div style={{ padding: 16, display: "grid", gap: 12 }}>
            {st && (
              <>
                <div className="bar" aria-hidden>
                  <span style={{ width: `${(100 * st.full_snapshots) / Math.max(1, totalVersions)}%`, background: "var(--head)" }} />
                  <span style={{ width: `${(100 * st.deltas) / Math.max(1, totalVersions)}%`, background: "var(--past)" }} />
                  <span style={{ width: `${(100 * st.tombstones) / Math.max(1, totalVersions)}%`, background: "var(--ink-3)" }} />
                </div>
                <dl style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "4px 16px", margin: 0 }}>
                  <dt><Swatch c="var(--head)" /> Full snapshots</dt><dd className="num" style={{ margin: 0 }}>{st.full_snapshots}</dd>
                  <dt><Swatch c="var(--past)" /> Delta-encoded</dt><dd className="num" style={{ margin: 0 }}>{st.deltas}</dd>
                  <dt><Swatch c="var(--ink-3)" /> Delete markers</dt><dd className="num" style={{ margin: 0 }}>{st.tombstones}</dd>
                  <dt>Payload bytes</dt><dd className="num" style={{ margin: 0 }}>{bytes(st.total_used_bytes)}</dd>
                </dl>
              </>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><span className="panel-title">Compress old versions</span></div>
          <div style={{ padding: 16, display: "grid", gap: 12 }}>
            <p className="hint" style={{ margin: 0 }}>
              Versions with at least this many newer versions of the same row are stored as small deltas against an older snapshot.
              Their 4 KB pages are freed. Queries return the same data; reading very old versions gets slightly slower.
            </p>
            <label className="field">
              <span>Keep the newest <b className="num">{threshold}</b> versions of each row as full snapshots</span>
              <input type="range" min={1} max={20} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
            </label>
            <button className="btn btn-primary" style={{ justifySelf: "start" }} disabled={busy !== null}
              onClick={() => run("opt", () => api.optimize(threshold), (r) => { setOpt(r); toast(`Compressed ${r.pages_compressed} versions`); })}>
              {busy === "opt" ? "Compressing…" : "Compress now"}
            </button>
            {opt && (
              <div className="panel" style={{ padding: 12, background: "var(--panel-2)" }}>
                <b>{opt.pages_compressed}</b> of {opt.pages_scanned} cold versions compressed in {opt.duration_ms.toFixed(0)} ms.
                Their payload shrank from {bytes(opt.bytes_before)} to {bytes(opt.bytes_after)} ({opt.savings_percent}% smaller);
                the database now uses {bytes(opt.live_bytes_after)} instead of {bytes(opt.live_bytes_before)}.
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><span className="panel-title">Reclaim deleted branches</span></div>
          <div style={{ padding: 16, display: "grid", gap: 12 }}>
            <p className="hint" style={{ margin: 0 }}>
              Garbage collection removes commits that no branch or tag can reach any more, such as the work on a deleted branch, and frees their pages.
            </p>
            <button className="btn" style={{ justifySelf: "start" }} disabled={busy !== null}
              onClick={() => run("gc", () => api.gc(), (r) => { setGc(r); toast(r.commits_removed ? `Removed ${r.commits_removed} unreachable commits` : "Nothing to reclaim"); })}>
              {busy === "gc" ? "Collecting…" : "Run garbage collection"}
            </button>
            {gc && (
              <div className="panel" style={{ padding: 12, background: "var(--panel-2)" }}>
                {gc.commits_removed
                  ? <>Removed <b>{gc.commits_removed}</b> commits and {gc.version_entries_pruned} row versions; freed {gc.pages_reclaimed} pages.</>
                  : <>Every commit is still reachable from a branch or tag ({gc.reachable_commits} commits).</>}
              </div>
            )}
          </div>
        </section>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 20, alignItems: "start" }}>
        <section className="panel" style={{ overflow: "hidden" }}>
          <div className="panel-head"><IconBranch width={16} height={16} /><span className="panel-title">Branches</span></div>
          <table className="diff-table">
            <thead><tr><th>Name</th><th>Last commit</th><th className="num">vs main</th><th /></tr></thead>
            <tbody>
              {branches.map((b) => (
                <tr key={b.name}>
                  <td>
                    <button style={{ fontWeight: 600, cursor: "pointer", color: b.name === branch ? "var(--head)" : undefined }} onClick={() => setBranch(b.name)}>{b.name}</button>
                    {b.created_from && <div className="hint">from {b.created_from}</div>}
                  </td>
                  <td><Hash value={b.head_hash} /> <span className="hint">{timeAgo(b.updated_at)}</span></td>
                  <td className="num hint">{b.name === "main" ? "—" : `+${b.ahead} −${b.behind}`}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {b.name !== "main" && (
                      <>
                        <button className="btn btn-ghost btn-sm" onClick={() => setRename({ from: b.name, to: b.name })}>Rename</button>
                        <button className="btn btn-ghost btn-sm btn-danger" onClick={() => setConfirmDelete(b.name)} aria-label={`Delete ${b.name}`}><IconTrash /></button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel" style={{ overflow: "hidden" }}>
          <div className="panel-head"><IconTag width={16} height={16} /><span className="panel-title">Tags</span></div>
          {tags.data?.tags.length ? (
            <table className="diff-table">
              <thead><tr><th>Tag</th><th>Commit</th><th /></tr></thead>
              <tbody>
                {tags.data.tags.map((t) => (
                  <tr key={t.name}>
                    <td><span className="chip chip-tag">{t.name}</span>{t.message && <div className="hint">{t.message}</div>}</td>
                    <td><Hash value={t.hash} /> <span className="hint">{t.commit_message}</span></td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn btn-ghost btn-sm btn-danger" aria-label={`Delete tag ${t.name}`}
                        onClick={() => run("tag", () => api.deleteTag(t.name), () => toast(`Deleted tag ${t.name}`))}><IconTrash /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hint" style={{ padding: 16, margin: 0 }}>No tags yet. Tag a commit from History to give it a fixed name like v1.0.</p>
          )}
        </section>
      </div>

      <section className="panel" style={{ padding: 16, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 260 }}>
          <div className="panel-title">Demo data</div>
          <div className="hint">Replace this database with the sample company dataset: four tables, six branches, a tag and a ready-made merge conflict.</div>
        </div>
        <button className="btn btn-danger" disabled={busy !== null}
          onClick={() => confirm("Replace the whole database with the demo data? This cannot be undone.") &&
            run("reset", () => api.resetDemo(), () => { setBranch("main"); toast("Demo data loaded"); })}>
          Load demo data
        </button>
        <span className="hint mono">{s?.db_path}{s && ` · last recovery: ${String(s.last_recovery?.status ?? "clean")}`}</span>
      </section>

      {confirmDelete && (
        <Dialog title={`Delete ${confirmDelete}?`} onClose={() => setConfirmDelete(null)}
          footer={<><button className="btn btn-ghost" onClick={() => setConfirmDelete(null)}>Cancel</button>
            <button className="btn btn-primary" style={{ background: "var(--del)", borderColor: "var(--del)" }}
              onClick={() => run("del", () => api.deleteBranch(confirmDelete), () => { toast(`Deleted ${confirmDelete}`); if (branch === confirmDelete) setBranch("main"); setConfirmDelete(null); })}>
              Delete branch</button></>}>
          <p>The branch pointer is removed. Commits only reachable from it stay in storage until you run garbage collection, so you can still find them by hash until then.</p>
        </Dialog>
      )}
      {rename && (
        <Dialog title={`Rename ${rename.from}`} onClose={() => setRename(null)}
          footer={<><button className="btn btn-ghost" onClick={() => setRename(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={!rename.to.trim() || rename.to === rename.from}
              onClick={() => run("ren", () => api.renameBranch(rename.from, rename.to.trim()), () => { toast(`Renamed to ${rename.to.trim()}`); if (branch === rename.from) setBranch(rename.to.trim()); setRename(null); })}>
              Rename</button></>}>
          <label className="field"><span>New name</span>
            <input className="input" value={rename.to} onChange={(e) => setRename({ ...rename, to: e.target.value })} />
          </label>
        </Dialog>
      )}
    </div>
  );
}

function Swatch({ c }: { c: string }) {
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: c, marginRight: 6 }} />;
}
