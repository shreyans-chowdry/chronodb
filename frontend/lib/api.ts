// ChronoDB API Client — typed fetch wrapper
// Base URL from environment, with fallback for local development

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  const url = `${API_BASE}${path}`;
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
  sourceBranch: string = "main"
): Promise<Branch> {
  return apiFetch<Branch>("/branches", {
    method: "POST",
    body: JSON.stringify({ name, source_branch: sourceBranch }),
  });
}

export async function checkoutBranch(name: string): Promise<string> {
  const data = await apiFetch<{ checked_out_branch: string }>(
    `/branches/${encodeURIComponent(name)}/checkout`,
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
