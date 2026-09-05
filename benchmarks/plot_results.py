#!/usr/bin/env python3
"""
ChronoDB — Benchmark Results Plotter

Reads benchmark_results.csv and generates publication-quality charts:
  1. Throughput comparison (grouped bar chart)
  2. Latency comparison (p50/p95/p99 grouped bars)
  3. Storage comparison (bar chart)
  4. Combined summary dashboard (2×2 grid)

Usage:
    python3 plot_results.py [--input results/benchmark_results.csv]
"""

import argparse
import csv
import os
import sys
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for headless rendering
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# ── Color palette (vibrant, modern) ──
COLORS = {
    "ChronoDB": "#6C5CE7",    # vivid purple
    "SQLite":   "#00B894",    # emerald green
    "Dolt":     "#E17055",    # coral
}
FALLBACK_COLORS = ["#0984E3", "#FDCB6E", "#E84393", "#636E72"]

BG_COLOR = "#F8F9FA"
GRID_COLOR = "#E9ECEF"
TEXT_COLOR = "#2D3436"


def load_csv(path: str) -> List[Dict[str, Any]]:
    """Load benchmark results CSV."""
    if not os.path.exists(path):
        print(f"Error: CSV file not found: {path}")
        sys.exit(1)

    with open(path, "r") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # Convert numeric fields
            for key in row:
                if key in ("engine", "workload"):
                    continue
                try:
                    row[key] = float(row[key])
                except (ValueError, TypeError):
                    pass
            rows.append(row)
    return rows


def get_color(engine: str, idx: int) -> str:
    return COLORS.get(engine, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])


def setup_style():
    """Apply consistent plot styling."""
    plt.rcParams.update({
        "figure.facecolor": BG_COLOR,
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": GRID_COLOR,
        "axes.grid": True,
        "grid.color": GRID_COLOR,
        "grid.alpha": 0.7,
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
    })


def plot_throughput(rows: List[Dict], output_dir: str) -> str:
    """Bar chart: throughput (ops/s) by workload and engine."""
    engines = sorted(set(r["engine"] for r in rows))
    workloads = sorted(set(r["workload"] for r in rows))

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads))
    width = 0.8 / max(len(engines), 1)

    for i, engine in enumerate(engines):
        values = []
        for wl in workloads:
            match = [r for r in rows if r["engine"] == engine and r["workload"] == wl]
            values.append(match[0]["throughput_ops_s"] if match else 0)

        bars = ax.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                      label=engine, color=get_color(engine, i),
                      edgecolor="white", linewidth=0.5, zorder=3)

        # Add value labels
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{val:.0f}", ha="center", va="bottom", fontsize=9,
                        fontweight="bold", color=TEXT_COLOR)

    ax.set_xlabel("Workload Profile")
    ax.set_ylabel("Throughput (ops/s)")
    ax.set_title("Throughput Comparison — Higher is Better")
    ax.set_xticks(x)
    ax.set_xticklabels([wl.replace("_", " ").title() for wl in workloads])
    ax.legend(framealpha=0.9, edgecolor=GRID_COLOR)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    path = os.path.join(output_dir, "throughput_comparison.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 {path}")
    return path


def plot_latency(rows: List[Dict], output_dir: str) -> str:
    """Grouped bar chart: p50/p95/p99 latency by workload and engine."""
    engines = sorted(set(r["engine"] for r in rows))
    workloads = sorted(set(r["workload"] for r in rows))
    percentiles = ["latency_p50_ms", "latency_p95_ms", "latency_p99_ms"]
    labels = ["p50", "p95", "p99"]

    fig, axes = plt.subplots(1, len(workloads), figsize=(5 * len(workloads), 6),
                              sharey=False)
    if len(workloads) == 1:
        axes = [axes]

    for wi, wl in enumerate(workloads):
        ax = axes[wi]
        x = np.arange(len(percentiles))
        width = 0.8 / max(len(engines), 1)

        for i, engine in enumerate(engines):
            match = [r for r in rows if r["engine"] == engine and r["workload"] == wl]
            if not match:
                continue
            r = match[0]
            values = [r[p] for p in percentiles]

            bars = ax.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                          label=engine if wi == 0 else "", color=get_color(engine, i),
                          edgecolor="white", linewidth=0.5, zorder=3)

            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=8, color=TEXT_COLOR)

        ax.set_title(wl.replace("_", " ").title())
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Latency (ms)" if wi == 0 else "")
        ax.set_ylim(bottom=0)

    axes[0].legend(framealpha=0.9, edgecolor=GRID_COLOR)
    fig.suptitle("Latency Distribution — Lower is Better", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    path = os.path.join(output_dir, "latency_comparison.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 {path}")
    return path


def plot_storage(rows: List[Dict], output_dir: str) -> str:
    """Bar chart: storage bytes by workload and engine."""
    engines = sorted(set(r["engine"] for r in rows))
    workloads = sorted(set(r["workload"] for r in rows))

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads))
    width = 0.8 / max(len(engines), 1)

    for i, engine in enumerate(engines):
        values = []
        for wl in workloads:
            match = [r for r in rows if r["engine"] == engine and r["workload"] == wl]
            val = match[0]["storage_bytes"] if match else 0
            values.append(val / 1024)  # Convert to KB

        bars = ax.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                      label=engine, color=get_color(engine, i),
                      edgecolor="white", linewidth=0.5, zorder=3)

        for bar, val in zip(bars, values):
            if val > 0:
                label = f"{val:.1f}KB" if val < 1024 else f"{val / 1024:.2f}MB"
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        label, ha="center", va="bottom", fontsize=9, color=TEXT_COLOR)

    ax.set_xlabel("Workload Profile")
    ax.set_ylabel("Storage (KB)")
    ax.set_title("Storage Usage Comparison")
    ax.set_xticks(x)
    ax.set_xticklabels([wl.replace("_", " ").title() for wl in workloads])
    ax.legend(framealpha=0.9, edgecolor=GRID_COLOR)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    path = os.path.join(output_dir, "storage_comparison.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 {path}")
    return path


def plot_dashboard(rows: List[Dict], output_dir: str) -> str:
    """Combined 2×2 dashboard with all key metrics."""
    engines = sorted(set(r["engine"] for r in rows))
    workloads = sorted(set(r["workload"] for r in rows))

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("ChronoDB Benchmark Dashboard", fontsize=18, fontweight="bold", y=0.98)

    x = np.arange(len(workloads))
    width = 0.8 / max(len(engines), 1)
    wl_labels = [wl.replace("_", " ").title() for wl in workloads]

    # ── Panel 1: Throughput ──
    for i, engine in enumerate(engines):
        values = [next((r["throughput_ops_s"] for r in rows
                        if r["engine"] == engine and r["workload"] == wl), 0)
                  for wl in workloads]
        ax1.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                label=engine, color=get_color(engine, i),
                edgecolor="white", linewidth=0.5, zorder=3)
    ax1.set_title("Throughput (ops/s) ↑")
    ax1.set_xticks(x)
    ax1.set_xticklabels(wl_labels, fontsize=9)
    ax1.legend(fontsize=9)
    ax1.set_ylim(bottom=0)

    # ── Panel 2: p50 Latency ──
    for i, engine in enumerate(engines):
        values = [next((r["latency_p50_ms"] for r in rows
                        if r["engine"] == engine and r["workload"] == wl), 0)
                  for wl in workloads]
        ax2.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                label=engine, color=get_color(engine, i),
                edgecolor="white", linewidth=0.5, zorder=3)
    ax2.set_title("Median Latency — p50 (ms) ↓")
    ax2.set_xticks(x)
    ax2.set_xticklabels(wl_labels, fontsize=9)
    ax2.set_ylim(bottom=0)

    # ── Panel 3: p99 Latency ──
    for i, engine in enumerate(engines):
        values = [next((r["latency_p99_ms"] for r in rows
                        if r["engine"] == engine and r["workload"] == wl), 0)
                  for wl in workloads]
        ax3.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                label=engine, color=get_color(engine, i),
                edgecolor="white", linewidth=0.5, zorder=3)
    ax3.set_title("Tail Latency — p99 (ms) ↓")
    ax3.set_xticks(x)
    ax3.set_xticklabels(wl_labels, fontsize=9)
    ax3.set_ylim(bottom=0)

    # ── Panel 4: Storage ──
    for i, engine in enumerate(engines):
        values = [next((r["storage_bytes"] / 1024 for r in rows
                        if r["engine"] == engine and r["workload"] == wl), 0)
                  for wl in workloads]
        ax4.bar(x + i * width - (len(engines) - 1) * width / 2, values, width,
                label=engine, color=get_color(engine, i),
                edgecolor="white", linewidth=0.5, zorder=3)
    ax4.set_title("Storage Usage (KB)")
    ax4.set_xticks(x)
    ax4.set_xticklabels(wl_labels, fontsize=9)
    ax4.set_ylim(bottom=0)

    plt.tight_layout(rect=(0, 0, 1, 0.96))
    path = os.path.join(output_dir, "benchmark_dashboard.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Plot ChronoDB benchmark results")
    parser.add_argument("--input", type=str, default="results/benchmark_results.csv",
                        help="Input CSV path")
    parser.add_argument("--output-dir", type=str, default="results",
                        help="Output directory for plots")
    args = parser.parse_args()

    input_path = args.input
    # Resolve relative to benchmarks/ dir
    if not os.path.isabs(input_path):
        input_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), input_path)

    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_dir)

    os.makedirs(output_dir, exist_ok=True)

    setup_style()

    print("📈 Loading benchmark results...")
    rows = load_csv(input_path)
    print(f"   Found {len(rows)} result rows\n")

    print("Generating plots:")
    plot_throughput(rows, output_dir)
    plot_latency(rows, output_dir)
    plot_storage(rows, output_dir)
    plot_dashboard(rows, output_dir)

    print(f"\n✅ All plots saved to {output_dir}/")


if __name__ == "__main__":
    main()
