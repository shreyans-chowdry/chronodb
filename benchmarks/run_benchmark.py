#!/usr/bin/env python3
"""
ChronoDB — YCSB-Style Benchmark Harness

Runs parameterized workloads against ChronoDB and SQLite (and optionally Dolt),
captures throughput, p50/p95/p99 latency, and storage bytes.

Outputs: results/benchmark_results.csv

Usage:
    python3 run_benchmark.py [--ops N] [--workloads ...]
    python3 run_benchmark.py --ops 200 --workloads read_heavy write_heavy
"""

import argparse
import csv
import os
import sys
import time
import shutil
import tempfile
from typing import List

# Ensure benchmarks dir is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workload import (
    WorkloadProfile, BenchmarkResult, OperationResult,
    compute_percentiles, ALL_WORKLOADS,
    WORKLOAD_READ_HEAVY, WORKLOAD_WRITE_HEAVY,
    WORKLOAD_BRANCH_HEAVY, WORKLOAD_MERGE_HEAVY,
)
from adapters import BenchmarkAdapter, ChronoDBAdapter, SQLiteAdapter


WORKLOAD_MAP = {w.name: w for w in ALL_WORKLOADS}


def run_single_benchmark(
    adapter: BenchmarkAdapter,
    workload: WorkloadProfile,
    num_ops: int,
    tmp_dir: str,
) -> BenchmarkResult:
    """
    Run a single benchmark: execute num_ops operations against the adapter
    using the given workload profile.
    """
    db_path = os.path.join(tmp_dir, f"test_bench_{adapter.name().lower()}.dat")

    print(f"  [{adapter.name()}] Setting up for '{workload.name}'...")
    adapter.setup(db_path)

    op_dispatch = {
        "read": adapter.do_read,
        "write": adapter.do_write,
        "branch": adapter.do_branch,
        "merge": adapter.do_merge,
        "delete": adapter.do_delete,
    }

    results: List[OperationResult] = []
    op_counts = {"read": 0, "write": 0, "branch": 0, "merge": 0, "delete": 0}

    wall_start = time.perf_counter()

    for i in range(num_ops):
        op = workload.pick_operation()
        fn = op_dispatch[op]

        t0 = time.perf_counter()
        try:
            success = fn()
        except Exception as e:
            success = False
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000.0
        results.append(OperationResult(operation=op, latency_ms=latency_ms, success=success))
        op_counts[op] += 1

    wall_end = time.perf_counter()
    duration_s = wall_end - wall_start

    # Compute metrics
    all_latencies = [r.latency_ms for r in results]
    p50, p95, p99 = compute_percentiles(all_latencies)
    errors = sum(1 for r in results if not r.success)
    storage = adapter.get_storage_bytes()

    adapter.teardown()

    throughput = num_ops / duration_s if duration_s > 0 else 0

    return BenchmarkResult(
        engine_name=adapter.name(),
        workload_name=workload.name,
        total_ops=num_ops,
        duration_s=duration_s,
        throughput_ops_s=throughput,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        storage_bytes=storage,
        read_ops=op_counts["read"],
        write_ops=op_counts["write"],
        branch_ops=op_counts["branch"],
        merge_ops=op_counts["merge"],
        errors=errors,
    )


def write_csv(results: List[BenchmarkResult], output_path: str) -> None:
    """Write benchmark results to a CSV file."""
    if not results:
        return

    fieldnames = list(results[0].to_csv_row().keys())
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_csv_row())

    print(f"\n✅ Results written to {output_path}")


def print_summary_table(results: List[BenchmarkResult]) -> None:
    """Print a formatted summary table to stdout."""
    print("\n" + "=" * 100)
    print(f"{'Engine':<12} {'Workload':<15} {'Ops':>6} {'Duration':>10} "
          f"{'Thru(op/s)':>12} {'p50(ms)':>10} {'p95(ms)':>10} {'p99(ms)':>10} "
          f"{'Storage':>12} {'Errors':>6}")
    print("-" * 100)

    for r in results:
        storage_str = format_bytes(r.storage_bytes)
        print(f"{r.engine_name:<12} {r.workload_name:<15} {r.total_ops:>6} "
              f"{r.duration_s:>9.3f}s {r.throughput_ops_s:>12.1f} "
              f"{r.latency_p50_ms:>10.3f} {r.latency_p95_ms:>10.3f} "
              f"{r.latency_p99_ms:>10.3f} {storage_str:>12} {r.errors:>6}")

    print("=" * 100)


def format_bytes(b: int) -> str:
    """Format bytes into a human-readable string."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


def main():
    parser = argparse.ArgumentParser(description="ChronoDB YCSB-Style Benchmark")
    parser.add_argument("--ops", type=int, default=500,
                        help="Number of operations per workload (default: 500)")
    parser.add_argument("--workloads", nargs="*", default=None,
                        help="Workload names to run (default: all). "
                             "Options: read_heavy, write_heavy, branch_heavy, merge_heavy")
    parser.add_argument("--output", type=str, default="results/benchmark_results.csv",
                        help="Output CSV path (default: results/benchmark_results.csv)")
    parser.add_argument("--engines", nargs="*", default=None,
                        help="Engines to benchmark (default: chronodb sqlite). "
                             "Options: chronodb, sqlite")
    args = parser.parse_args()

    # Select workloads
    if args.workloads:
        workloads = []
        for w_name in args.workloads:
            if w_name not in WORKLOAD_MAP:
                print(f"Unknown workload: {w_name}. Available: {list(WORKLOAD_MAP.keys())}")
                sys.exit(1)
            workloads.append(WORKLOAD_MAP[w_name])
    else:
        workloads = ALL_WORKLOADS

    # Select engines
    engine_factories = {
        "chronodb": ChronoDBAdapter,
        "sqlite": SQLiteAdapter,
    }
    if args.engines:
        selected_engines = []
        for e in args.engines:
            if e.lower() not in engine_factories:
                print(f"Unknown engine: {e}. Available: {list(engine_factories.keys())}")
                sys.exit(1)
            selected_engines.append(e.lower())
    else:
        selected_engines = list(engine_factories.keys())

    print("╔══════════════════════════════════════════════════════════╗")
    print("║       ChronoDB YCSB-Style Benchmark Suite              ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Operations per workload:  {args.ops:<28} ║")
    print(f"║  Workloads:  {', '.join(w.name for w in workloads):<42} ║")
    print(f"║  Engines:    {', '.join(selected_engines):<42} ║")
    print("╚══════════════════════════════════════════════════════════╝")

    all_results: List[BenchmarkResult] = []

    for workload in workloads:
        print(f"\n▶ Workload: {workload.name} — {workload.description}")

        for engine_name in selected_engines:
            # Create fresh temp directory per (engine, workload) combo
            tmp_dir = tempfile.mkdtemp(prefix=f"chronobench_{engine_name}_{workload.name}_")
            try:
                adapter = engine_factories[engine_name]()
                result = run_single_benchmark(adapter, workload, args.ops, tmp_dir)
                all_results.append(result)
                print(f"    → {result.throughput_ops_s:.1f} ops/s | "
                      f"p50={result.latency_p50_ms:.3f}ms | "
                      f"p95={result.latency_p95_ms:.3f}ms | "
                      f"p99={result.latency_p99_ms:.3f}ms | "
                      f"storage={format_bytes(result.storage_bytes)}")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # Output
    print_summary_table(all_results)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output)
    write_csv(all_results, output_path)
    print(f"\nTo generate plots, run:\n  python3 benchmarks/plot_results.py\n")


if __name__ == "__main__":
    main()
