"""
ChronoDB — YCSB-Style Benchmark Workload Generator

Defines parameterized workload profiles (read-heavy, write-heavy, branch-heavy,
merge-heavy) and provides a common interface for running them against different
database backends.

Each workload is a sequence of operations drawn from a weighted mix:
  - read:   read a random row from the active branch
  - write:  insert or update a random row
  - branch: create a new branch from the current state
  - merge:  merge a random branch into the target
  - delete: delete a random row
"""

import random
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class WorkloadProfile:
    """Defines the operation mix for a YCSB-style benchmark."""
    name: str
    description: str
    # Weights for each operation type (must sum to 100)
    read_pct: int
    write_pct: int
    branch_pct: int
    merge_pct: int
    delete_pct: int = 0

    def __post_init__(self):
        total = self.read_pct + self.write_pct + self.branch_pct + self.merge_pct + self.delete_pct
        if total != 100:
            raise ValueError(f"Workload weights must sum to 100, got {total}")

    def pick_operation(self) -> str:
        """Pick a random operation based on the workload weights."""
        r = random.randint(1, 100)
        cumulative = 0
        for op, pct in [
            ("read", self.read_pct),
            ("write", self.write_pct),
            ("branch", self.branch_pct),
            ("merge", self.merge_pct),
            ("delete", self.delete_pct),
        ]:
            cumulative += pct
            if r <= cumulative:
                return op
        return "read"  # fallback


# ── Predefined workload profiles ──

WORKLOAD_READ_HEAVY = WorkloadProfile(
    name="read_heavy",
    description="Read-heavy (80% read, 15% write, 5% branch)",
    read_pct=80, write_pct=15, branch_pct=5, merge_pct=0,
)

WORKLOAD_WRITE_HEAVY = WorkloadProfile(
    name="write_heavy",
    description="Write-heavy (20% read, 70% write, 5% branch, 5% delete)",
    read_pct=20, write_pct=70, branch_pct=5, merge_pct=0, delete_pct=5,
)

WORKLOAD_BRANCH_HEAVY = WorkloadProfile(
    name="branch_heavy",
    description="Branch-heavy (30% read, 30% write, 30% branch, 10% merge)",
    read_pct=30, write_pct=30, branch_pct=30, merge_pct=10,
)

WORKLOAD_MERGE_HEAVY = WorkloadProfile(
    name="merge_heavy",
    description="Merge-heavy (20% read, 30% write, 20% branch, 30% merge)",
    read_pct=20, write_pct=30, branch_pct=20, merge_pct=30,
)

ALL_WORKLOADS = [
    WORKLOAD_READ_HEAVY,
    WORKLOAD_WRITE_HEAVY,
    WORKLOAD_BRANCH_HEAVY,
    WORKLOAD_MERGE_HEAVY,
]


@dataclass
class OperationResult:
    """Result of a single benchmark operation."""
    operation: str
    latency_ms: float
    success: bool


@dataclass
class BenchmarkResult:
    """Aggregated results from a full benchmark run."""
    engine_name: str
    workload_name: str
    total_ops: int
    duration_s: float
    throughput_ops_s: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    storage_bytes: int
    read_ops: int = 0
    write_ops: int = 0
    branch_ops: int = 0
    merge_ops: int = 0
    errors: int = 0

    def to_csv_row(self) -> Dict[str, Any]:
        return {
            "engine": self.engine_name,
            "workload": self.workload_name,
            "total_ops": self.total_ops,
            "duration_s": round(self.duration_s, 4),
            "throughput_ops_s": round(self.throughput_ops_s, 2),
            "latency_p50_ms": round(self.latency_p50_ms, 4),
            "latency_p95_ms": round(self.latency_p95_ms, 4),
            "latency_p99_ms": round(self.latency_p99_ms, 4),
            "storage_bytes": self.storage_bytes,
            "read_ops": self.read_ops,
            "write_ops": self.write_ops,
            "branch_ops": self.branch_ops,
            "merge_ops": self.merge_ops,
            "errors": self.errors,
        }


def compute_percentiles(latencies: List[float]) -> Tuple[float, float, float]:
    """Compute p50, p95, p99 from a list of latency values."""
    if not latencies:
        return 0.0, 0.0, 0.0
    s = sorted(latencies)
    n = len(s)
    p50 = s[int(n * 0.50)]
    p95 = s[min(int(n * 0.95), n - 1)]
    p99 = s[min(int(n * 0.99), n - 1)]
    return p50, p95, p99


def random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def random_row_data() -> Dict[str, Any]:
    """Generate a random row payload."""
    return {
        "username": f"user_{random_string(6)}",
        "email": f"{random_string(8)}@example.com",
        "department": random.choice(["Engineering", "Sales", "Marketing", "Support", "Finance"]),
        "salary": random.randint(50000, 200000),
        "active": random.choice([True, False]),
        "notes": f"Auto-generated benchmark record {random_string(16)}",
    }
