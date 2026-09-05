function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  return "/api";
}

// ── Types ──

export interface Branch {
  id: number;
  name: string;
  head_commit_id: number;
}

export interface Commit {
  id: number;
  hash: string;
  parent_id: number | null;
  second_parent_id: number | null;
  branch_id: number;
  message: string;
  timestamp: number;
  author: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface TableRow {
  row_id: string;
  [key: string]: unknown;
}

// ── Internal fetch helper ──

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${getApiBase()}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message =
      body?.error?.message || body?.detail || `API error ${res.status}`;
    throw new Error(message);
  }

  return res.json();
}

// ── Branch endpoints ──

export async function fetchBranches(): Promise<Branch[]> {
  const data = await apiFetch<{ branches: Branch[] }>("/branches");
  return data.branches;
}

export async function createBranch(
  name: string,
  sourceBranch: string = "main",
  pullFromMain: boolean = false
): Promise<Branch> {
  return apiFetch<Branch>("/branches", {
    method: "POST",
    body: JSON.stringify({ name, source_branch: sourceBranch, pull_from_main: pullFromMain }),
  });
}

export async function checkoutBranch(name: string): Promise<string> {
  const data = await apiFetch<{ checked_out_branch: string }>(
    `/branches/checkout?name=${encodeURIComponent(name)}`,
    { method: "POST" }
  );
  return data.checked_out_branch;
}

// ── Commit endpoints ──

export async function fetchCommits(branchName: string): Promise<Commit[]> {
  const data = await apiFetch<{ commits: Commit[] }>(
    `/commits?branch_name=${encodeURIComponent(branchName)}`
  );
  return data.commits;
}

export async function createCommit(
  branchName: string,
  message: string,
  author: string,
  changes?: Array<{
    action: string;
    table_name: string;
    row_id: string;
    data?: Record<string, unknown>;
  }>
): Promise<Commit> {
  return apiFetch<Commit>("/commits", {
    method: "POST",
    body: JSON.stringify({
      branch_name: branchName,
      message,
      author,
      changes,
    }),
  });
}

export async function rollbackToCommit(
  commitHash: string,
  branchName: string,
  author: string
): Promise<Commit> {
  return apiFetch<Commit>(
    `/rollback/${encodeURIComponent(commitHash)}`,
    {
      method: "POST",
      body: JSON.stringify({
        branch_name: branchName,
        target_commit_hash: commitHash,
        author,
      }),
    }
  );
}

// ── Table / Data endpoints ──

export async function fetchTables(branchName: string): Promise<string[]> {
  const data = await apiFetch<{ tables: string[] }>(
    `/tables?branch_name=${encodeURIComponent(branchName)}`
  );
  return data.tables;
}

export async function fetchTableData(
  branchName: string,
  tableName: string
): Promise<TableRow[]> {
  const data = await apiFetch<{ rows: TableRow[] }>(
    `/data/${encodeURIComponent(tableName)}?branch_name=${encodeURIComponent(branchName)}`
  );
  return data.rows;
}

// ── Diff & Merge types ──

export interface DiffRow {
  row_id: string;
  status: "added" | "deleted" | "modified";
  data_a: Record<string, unknown> | null;
  data_b: Record<string, unknown> | null;
  changed_fields?: string[];
}

export interface DiffTableResult {
  rows: DiffRow[];
}

export interface DiffResult {
  tables: Record<string, DiffTableResult>;
}

export interface MergeConflict {
  table_name: string;
  row_id: string;
  data_ancestor: Record<string, unknown> | null;
  data_target: Record<string, unknown> | null;
  data_source: Record<string, unknown> | null;
}

export interface MergeAutoResolved {
  table_name: string;
  row_id: string;
  resolution: string;
  data: Record<string, unknown> | null;
}

export interface MergeResolution {
  key: string;
  data: Record<string, unknown> | null;
}

export interface MergeResponse {
  status: "ok" | "conflict";
  commit?: Commit;
  conflicts?: MergeConflict[];
  auto_resolved?: MergeAutoResolved[];
}

// ── Diff & Merge endpoints ──

export async function fetchDiff(
  commitA: string,
  commitB: string
): Promise<DiffResult> {
  return apiFetch<DiffResult>(
    `/diff?commit_a=${encodeURIComponent(commitA)}&commit_b=${encodeURIComponent(commitB)}`
  );
}

export async function executeMerge(
  targetBranch: string,
  sourceBranch: string,
  author: string,
  resolutions?: MergeResolution[]
): Promise<MergeResponse> {
  return apiFetch<MergeResponse>("/merge", {
    method: "POST",
    body: JSON.stringify({
      target_branch: targetBranch,
      source_branch: sourceBranch,
      author,
      resolutions: resolutions || null,
    }),
  });
}

