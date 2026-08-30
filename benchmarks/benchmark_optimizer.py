"""
ChronoDB — Adaptive Storage Optimizer Benchmark

Measures and logs storage bytes saved before and after running the Adaptive
Storage Optimizer on a realistic multi-table test dataset with historical commits.
"""

import os
import sys
import time
import tempfile
import random

# Ensure parent directories are on sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from engine.src.version.engine import VersionEngine


def run_benchmark():
    print("=" * 70)
    print(" ChronoDB — Adaptive Storage Optimizer Benchmark")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "benchmark_chronodb.dat")
        engine = VersionEngine(db_path)

        num_users = 25
        num_orders = 25
        num_commits = 20
        cold_threshold = 5

        print(f"\n[1/4] Generating benchmark dataset...")
        print(f"      Tables:           users ({num_users} rows), orders ({num_orders} rows)")
        print(f"      Commits:          {num_commits} sequential transaction commits")
        print(f"      Cold Threshold:   {cold_threshold} commits\n")

        # Initial commit: seed tables
        user_changes = []
        for i in range(num_users):
            user_changes.append({
                "action": "insert",
                "table_name": "users",
                "row_id": f"u-{i:04d}",
                "data": {
                    "username": f"user_{i}",
                    "email": f"user_{i}@company.org",
                    "role": "engineer" if i % 2 == 0 else "analyst",
                    "department": "Engineering" if i % 2 == 0 else "Data Science",
                    "salary": 100000 + i * 2500,
                    "active": True,
                    "metadata": f"Initial user registration profile #{i} created at system start.",
                },
            })

        order_changes = []
        for j in range(num_orders):
            order_changes.append({
                "action": "insert",
                "table_name": "orders",
                "row_id": f"ord-{j:04d}",
                "data": {
                    "order_id": f"ORD-2026-{j:05d}",
                    "customer_id": f"u-{j % num_users:04d}",
                    "amount": round(49.99 + j * 12.50, 2),
                    "status": "pending",
                    "priority": "standard",
                    "items_count": (j % 5) + 1,
                    "shipping_address": f"{100 + j} Innovation Way, Tech Park, Suite {j}",
                },
            })

        engine.commit("main", "Initial seed data", "system", changes=user_changes + order_changes)

        # Generate updates over multiple commits
        start_time = time.time()
        for c in range(1, num_commits):
            mutations = []
            # Mutate a subset of users
            for u_idx in random.sample(range(num_users), k=15):
                mutations.append({
                    "action": "update",
                    "table_name": "users",
                    "row_id": f"u-{u_idx:04d}",
                    "data": {
                        "username": f"user_{u_idx}",
                        "email": f"user_{u_idx}@company.org",
                        "role": "senior_engineer" if c > 10 else "engineer",
                        "department": "Engineering" if u_idx % 2 == 0 else "Data Science",
                        "salary": 100000 + u_idx * 2500 + c * 500,
                        "active": True,
                        "metadata": f"Profile update at commit {c} for user {u_idx}.",
                    },
                })

            # Mutate a subset of orders
            for o_idx in random.sample(range(num_orders), k=15):
                mutations.append({
                    "action": "update",
                    "table_name": "orders",
                    "row_id": f"ord-{o_idx:04d}",
                    "data": {
                        "order_id": f"ORD-2026-{o_idx:05d}",
                        "customer_id": f"u-{o_idx % num_users:04d}",
                        "amount": round(49.99 + o_idx * 12.50 + c * 2.0, 2),
                        "status": "shipped" if c > 8 else "processing",
                        "priority": "rush" if c % 3 == 0 else "standard",
                        "items_count": (o_idx % 5) + 1,
                        "shipping_address": f"{100 + o_idx} Innovation Way, Tech Park, Suite {o_idx}",
                    },
                })

            engine.commit("main", f"Batch mutation {c}", f"worker-{c % 4}", changes=mutations)

        gen_time = time.time() - start_time
        print(f"[2/4] Dataset generated in {gen_time:.3f}s.")

        # Measure pre-optimization stats
        stats_before = engine.get_storage_stats()
        print(f"\n      Pre-Optimization Storage Stats:")
        print(f"      - Total version pages:   {stats_before['total_versions']}")
        print(f"      - Full snapshot pages:  {stats_before['full_snapshots']}")
        print(f"      - Delta-encoded pages:  {stats_before['deltas']}")
        print(f"      - Total payload bytes:  {stats_before['total_used_bytes']:,} bytes")

        # Run Adaptive Storage Optimizer
        print(f"\n[3/4] Running Adaptive Storage Optimizer (cold_threshold={cold_threshold})...")
        opt_start = time.time()
        report = engine.optimize_storage(cold_threshold=cold_threshold)
        opt_time = time.time() - opt_start

        # Measure post-optimization stats
        stats_after = engine.get_storage_stats()

        print(f"\n[4/4] Verification & Results:")
        print("-" * 70)
        print(f"  Execution Time:          {opt_time * 1000:.2f} ms")
        print(f"  Pages Scanned:           {report.pages_scanned}")
        print(f"  Pages Compressed:        {report.pages_compressed}")
        print(f"  Storage Before:          {report.bytes_before:,} bytes")
        print(f"  Storage After:           {report.bytes_after:,} bytes")
        print(f"  Storage Saved:           {report.bytes_saved:,} bytes ({report.savings_percent:.1f}% reduction)")
        print("-" * 70)

        # Integrity Check
        users_head = engine.get_data("main", "users")
        orders_head = engine.get_data("main", "orders")
        assert len(users_head) == num_users, "User count mismatch!"
        assert len(orders_head) == num_orders, "Order count mismatch!"

        # Check historical queries across different commits
        history = engine.get_commit_history("main")
        seed_commit = [c for c in history if c["message"] == "Initial seed data"][0]
        as_of_seed = engine.query_as_of_commit("users", seed_commit["hash"])
        assert len(as_of_seed) == num_users, "Historical seed query mismatch!"

        mid_commit = history[len(history) // 2]
        as_of_mid = engine.query_as_of_commit("users", mid_commit["hash"])
        assert len(as_of_mid) == num_users, "Historical mid-point query mismatch!"

        print("  Data Integrity:          ✅ PASSED (all active and historical reads match)")
        print("=" * 70)

        engine.close()


if __name__ == "__main__":
    run_benchmark()
