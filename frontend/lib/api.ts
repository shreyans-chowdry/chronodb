// Typed client for the ChronoDB FastAPI service.

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "/api";
}

export class ApiError extends Error {
  status: number;
  details: unknown;
  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("Can't reach the ChronoDB API. Start it with `python -m uvicorn api.main:app --port 8000`.", 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const msg = body?.error?.message || body?.detail || `Request failed (${res.status})`;
    throw new ApiError(msg, res.status, body?.error?.details);
  }
  return res.json();
}

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};
const enc = encodeURIComponent;

// ── Types ──

export type RowData = Record<string, unknown>;
export interface Row extends RowData {
  row_id: string;
}

export interface Branch {
  id: string;
  name: string;
  head_commit_id: number;
  head_hash?: string;
  head_message?: string;
  head_author?: string;
  updated_at?: number;
  created_at?: number;
  created_from?: string | null;
  commit_count?: number;
  ahead?: number;
  behind?: number;
  is_current?: boolean;
}

export interface Commit {
  id: number;
  hash: string;
  parent_id: number | null;
  second_parent_id: number | null;
  branch_id: string;
  message: string;
  timestamp: number;
  author: string;
  stats?: { insert: number; update: number; delete: number };
  branch_heads?: string[];
  tags?: string[];
}

export interface Tag {
  name: string;
  commit_id: number;
  hash: string;
  message?: string;
  author?: string;
  created_at?: number;
  commit_message?: string;
}

export interface DiffRow {
  row_id: string;
  status: "added" | "deleted" | "modified";
  data_a: RowData | null;
  data_b: RowData | null;
  changed_fields?: string[];
}
export interface DiffResult {
  tables: Record<string, { rows: DiffRow[] }>;
  summary?: { added: number; deleted: number; modified: number };
}

export interface CommitDetail extends Commit {
  changes: DiffResult;
  parent_hash: string | null;
  second_parent_hash: string | null;
}

export interface Conflict {
  table_name: string;
  row_id: string;
  ancestor_data: RowData | null;
  source_data: RowData | null;
  target_data: RowData | null;
  conflicting_cells: string[];
  conflict_type: "modify_modify" | "delete_modify" | "modify_delete" | "add_add";
}

export interface MergePreview {
  merged: boolean;
  strategy: "up-to-date" | "fast-forward" | "three-way";
  changes: { action: string; table_name: string; row_id: string; data?: RowData | null }[];
  conflicting_rows: Conflict[];
  auto_merged_rows?: { table_name: string; row_id: string; data: RowData }[];
  rows_changed_on_target?: number;
  lca?: number;
}

export interface CompareResult {
  diff: DiffResult;
  merge_preview: MergePreview | null;
  ahead: number;
  behind: number;
}

export interface RowVersion {
  commit_id: number;
  hash: string;
  message: string;
  author: string;
  timestamp: number;
  branch_id: string;
  deleted: boolean;
  data: RowData | null;
  storage: "snapshot" | "delta" | "tombstone";
}

export interface SqlStatementResult {
  kind: "rows" | "write" | "info";
  statement: string;
  columns: string[];
  rows: RowData[];
  affected: number;
  as_of: { kind: string; value: unknown; commit_hash: string; commit_message: string; timestamp: number } | null;
  elapsed_ms: number;
}
export interface SqlResponse {
  results: SqlStatementResult[];
  commit: Commit | null;
  changes: number;
  dry_run: boolean;
}

export interface Stats {
  commits: number;
  branches: number;
  tags: number;
  tables: number;
  row_keys: number;
  current_branch: string;
  pages_total: number;
  pages_free: number;
  pages_live: number;
  file_bytes: number;
  live_bytes: number;
  wal_bytes: number;
  db_path: string;
  last_recovery: Record<string, unknown>;
  storage: {
    total_versions: number;
    full_snapshots: number;
    deltas: number;
    tombstones: number;
    total_used_bytes: number;
  };
}

export interface OptimizeReport {
  pages_scanned: number;
  pages_compressed: number;
  bytes_before: number;
  bytes_after: number;
  bytes_saved: number;
  savings_percent: number;
  cold_threshold: number;
  live_bytes_before: number;
  live_bytes_after: number;
  live_bytes_saved: number;
  live_savings_percent: number;
  duration_ms: number;
}

export interface GcReport {
  reachable_commits: number;
  orphaned_commits: number;
  pages_reclaimed: number;
  version_entries_pruned: number;
  commits_removed: number;
  versions_rehydrated: number;
}

export interface Change {
  action: "insert" | "update" | "delete";
  table_name: string;
  row_id: string;
  data?: RowData;
}

// ── Endpoints ──

export const api = {
  branches: () => req<{ branches: Branch[]; current: string }>("/branches"),
  createBranch: (name: string, source: string, empty = false) =>
    req<Branch>("/branches", { method: "POST", body: JSON.stringify({ name, source_branch: source, pull_from_main: !empty }) }),
  deleteBranch: (name: string) => req<{ deleted: string }>(`/branches/${name.split("/").map(enc).join("/")}`, { method: "DELETE" }),
  renameBranch: (name: string, newName: string) =>
    req<Branch>(`/branches/${name.split("/").map(enc).join("/")}/rename`, { method: "POST", body: JSON.stringify({ new_name: newName }) }),

  tags: () => req<{ tags: Tag[] }>("/tags"),
  createTag: (name: string, ref: string, message: string, author: string) =>
    req<Tag>("/tags", { method: "POST", body: JSON.stringify({ name, ref, message, author }) }),
  deleteTag: (name: string) => req<{ deleted: string }>(`/tags/${enc(name)}`, { method: "DELETE" }),

  log: (branch: string, limit = 200, offset = 0) =>
    req<{ commits: Commit[]; total: number }>(`/commits${q({ branch_name: branch, mode: "log", limit, offset })}`),
  graph: () => req<{ commits: Commit[]; branches: Branch[]; tags: Tag[] }>("/commits/graph"),
  commit: (ref: string) => req<CommitDetail>(`/commits/${ref.split("/").map(enc).join("/")}`),
  createCommit: (branch: string, message: string, author: string, changes: Change[]) =>
    req<Commit>("/commits", { method: "POST", body: JSON.stringify({ branch_name: branch, message, author, changes }) }),
  rollback: (branch: string, hash: string, author: string) =>
    req<Commit>(`/rollback/${enc(hash)}`, { method: "POST", body: JSON.stringify({ branch_name: branch, target_commit_hash: hash, author }) }),
  revert: (branch: string, hash: string, author: string) =>
    req<{ reverted: boolean; commit?: Commit; conflicts?: { table_name: string; row_id: string }[] }>(
      `/revert/${enc(hash)}`, { method: "POST", body: JSON.stringify({ branch_name: branch, author }) }),

  tables: (branch: string, asOf?: string | null) =>
    req<{ tables: string[]; counts: Record<string, number> }>(`/tables${q({ branch_name: branch, as_of_commit: asOf, with_counts: true })}`),
  data: (table: string, branch: string, asOf?: string | null) =>
    req<{ rows: Row[]; commit: { hash: string; message: string; timestamp: number } }>(
      `/data/${enc(table)}${q({ branch_name: branch, as_of_commit: asOf })}`),
  rowHistory: (table: string, rowId: string, ref: string) =>
    req<{ history: RowVersion[] }>(`/rows/${enc(table)}/${enc(rowId)}/history${q({ ref })}`),

  sql: (sql: string, branch: string, author: string, message?: string) =>
    req<SqlResponse>("/sql", { method: "POST", body: JSON.stringify({ sql, branch_name: branch, author, message: message || null }) }),

  diff: (a: string, b: string) => req<DiffResult>(`/diff${q({ commit_a: a, commit_b: b })}`),
  compare: (base: string, head: string) => req<CompareResult>(`/compare${q({ base, head })}`),
  merge: (source: string, target: string, author: string, resolutions?: { key: string; data: RowData | null }[], message?: string) =>
    req<{ status: "ok" | "conflict"; commit?: Commit; strategy?: string; conflicts?: Conflict[] }>("/merge", {
      method: "POST",
      body: JSON.stringify({ source_branch: source, target_branch: target, author, resolutions: resolutions?.length ? resolutions : null, message: message || null }),
    }),

  stats: () => req<Stats>("/stats"),
  optimize: (cold_threshold: number) => req<OptimizeReport>("/maintenance/optimize", { method: "POST", body: JSON.stringify({ cold_threshold }) }),
  gc: () => req<GcReport>("/maintenance/gc", { method: "POST" }),
  checkpoint: () => req<{ pages_flushed: number }>("/maintenance/checkpoint", { method: "POST" }),
  resetDemo: () => req<{ status: string }>("/demo/reset", { method: "POST" }),
};
