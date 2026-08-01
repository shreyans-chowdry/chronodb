"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Branch,
  Commit,
  TableRow,
  fetchBranches,
  fetchCommits,
  fetchTables,
  fetchTableData,
} from "@/lib/api";

// ── Generic async data hook ──

interface UseAsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): UseAsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState(0);

  const refetch = useCallback(() => setTrigger((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetcher()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger, ...deps]);

  return { data, loading, error, refetch };
}

// ── Domain hooks ──

export function useBranches() {
  return useAsync<Branch[]>(() => fetchBranches());
}

export function useCommits(branchName: string) {
  return useAsync<Commit[]>(
    () => fetchCommits(branchName),
    [branchName]
  );
}

export function useTables(branchName: string) {
  return useAsync<string[]>(
    () => fetchTables(branchName),
    [branchName]
  );
}

export function useTableData(branchName: string, tableName: string | null) {
  return useAsync<TableRow[]>(
    () =>
      tableName
        ? fetchTableData(branchName, tableName)
        : Promise.resolve([]),
    [branchName, tableName]
  );
}
