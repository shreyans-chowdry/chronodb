#!/usr/bin/env python3
"""
Experiments for the ChronoDB paper.

    python benchmarks/paper_experiments.py workload  [--ops 5000 10000] [--trials 5]
    python benchmarks/paper_experiments.py merge     [--pairs 100]
    python benchmarks/paper_experiments.py optimizer [--seeds 3]
    python benchmarks/paper_experiments.py all

Results are written to benchmarks/results/*.csv and *.json.

Fairness rules
--------------
* Operation sequences are generated *before* either system runs, from a fixed
  seed, by a generator that keeps a reference model of every branch. Both
  systems execute exactly the same list of operations.
* Every merge names an existing source branch whose common ancestor with
  main is defined (the branch was forked from main). When no branch exists the
  generator first emits the branch-creation operation that the merge needs.
* After a run, the final contents of main in both systems are compared with
  the reference model, so a system cannot look fast by doing less work.
* Both systems make each operation durable with one fsync: ChronoDB through
  its WAL, SQLite with journal_mode=WAL and synchronous=FULL.
"""

import argparse
import csv
import gc
import json
import os
import platform
import random
import shutil
import sqlite3
import statistics
import string
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from engine.src.version.engine import VersionEngine  # noqa: E402

RESULTS = os.path.join(ROOT, "benchmarks", "results")
TABLE = "bench"
SEED_ROWS = 200

WORKLOADS = {
    # name: (read, write, branch, merge, delete) percentages — same mixes as the first study
    "read_heavy": (80, 15, 5, 0, 0),
    "write_heavy": (20, 70, 5, 0, 5),
    "branch_heavy": (30, 30, 30, 10, 0),
    "merge_heavy": (20, 30, 20, 30, 0),
}

MISSING = object()


# ─────────────────────────────────────────────────────────────
# Shared three-way merge semantics (row + cell level)
# ─────────────────────────────────────────────────────────────

def three_way(base: Dict[str, dict], src: Dict[str, dict], tgt: Dict[str, dict]) -> Tuple[Optional[Dict[str, dict]], List[str]]:
    """Merge src into tgt with common ancestor base. Returns (result, conflicting_keys)."""
    out = dict(tgt)
    conflicts = []
    for k in set(base) | set(src) | set(tgt):
        a, s, t = base.get(k), src.get(k), tgt.get(k)
        if s == a:
            continue
        if t == a or s == t:
            if s is None:
                out.pop(k, None)
            else:
                out[k] = s
            continue
        if a is None or s is None or t is None:
            conflicts.append(k)
            continue
        merged, bad = {}, False
        for c in dict.fromkeys(list(t) + list(s) + list(a)):
            av, sv, tv = a.get(c, MISSING), s.get(c, MISSING), t.get(c, MISSING)
            if sv != av and tv != av and sv != tv:
                bad = True
                break
            v = sv if (sv != av) else tv
            if v is not MISSING:
                merged[c] = v
        if bad:
            conflicts.append(k)
        else:
            out[k] = merged
    return (None, sorted(conflicts)) if conflicts else (out, [])


# ─────────────────────────────────────────────────────────────
# Operation generator with a reference model
# ─────────────────────────────────────────────────────────────

def rand_row(rnd: random.Random) -> dict:
    s = lambda n: "".join(rnd.choices(string.ascii_lowercase + string.digits, k=n))  # noqa: E731
    return {
        "username": f"user_{s(6)}",
        "email": f"{s(8)}@example.com",
        "department": rnd.choice(["Engineering", "Sales", "Marketing", "Support", "Finance"]),
        "salary": rnd.randint(50000, 200000),
        "active": rnd.choice([True, False]),
        "notes": f"benchmark record {s(16)}",
    }


@dataclass
class Model:
    branches: Dict[str, Dict[str, dict]] = field(default_factory=dict)
    bases: Dict[str, Dict[str, dict]] = field(default_factory=dict)
    merged: int = 0
    conflicts: int = 0


def generate(workload: str, n_ops: int, seed: int) -> Tuple[List[tuple], Dict[str, dict], Dict[str, dict]]:
    """Return (seed_rows, ops, expected_final_main, op_counts)."""
    rnd = random.Random(seed)
    weights = WORKLOADS[workload]
    names = ["read", "write", "branch", "merge", "delete"]
    seed_rows = {f"s{i}": rand_row(rnd) for i in range(SEED_ROWS)}
    m = Model(branches={"main": dict(seed_rows)})
    ops: List[tuple] = []
    counter = 0
    nb = 0
    counts = {k: 0 for k in names}
    counts["merge_conflict"] = 0

    def emit_branch():
        nonlocal nb
        nb += 1
        name = f"b{nb}"
        m.branches[name] = dict(m.branches["main"])
        m.bases[name] = dict(m.branches["main"])
        ops.append(("branch", name))
        counts["branch"] += 1

    while len(ops) < n_ops:
        op = rnd.choices(names, weights=weights)[0]
        if op == "merge":
            live = [b for b in m.branches if b != "main"]
            if not live:
                emit_branch()
                if len(ops) >= n_ops:
                    break
                live = [f"b{nb}"]
            b = rnd.choice(live)
            res, conf = three_way(m.bases[b], m.branches[b], m.branches["main"])
            if res is None:
                counts["merge_conflict"] += 1
            else:
                m.branches["main"] = res
            del m.branches[b], m.bases[b]
            ops.append(("merge", b, res is not None))
            counts["merge"] += 1
        elif op == "branch":
            emit_branch()
        else:
            br = rnd.choice(list(m.branches))
            rows = m.branches[br]
            keys = list(rows)
            if op == "read":
                ops.append(("read", br, rnd.choice(keys) if keys else "missing"))
            elif op == "delete" and keys:
                k = rnd.choice(keys)
                del rows[k]
                ops.append(("delete", br, k))
            else:
                op = "write"
                if keys and rnd.random() < 0.4:
                    k = rnd.choice(keys)
                else:
                    counter += 1
                    k = f"r{counter}"
                data = rand_row(rnd)
                rows[k] = data
                ops.append(("write", br, k, data))
            counts[op] += 1
    return seed_rows, ops, m.branches["main"], counts


# ─────────────────────────────────────────────────────────────
# System adapters
# ─────────────────────────────────────────────────────────────

class ChronoDB:
    name = "ChronoDB"

    def __init__(self, d: str):
        self.path = os.path.join(d, "chrono.db")
        self.e = VersionEngine(self.path)

    def seed(self, rows):
        self.e.commit("main", "seed", "bench", [
            {"action": "insert", "table_name": TABLE, "row_id": k, "data": v} for k, v in rows.items()])

    def read(self, br, k):
        return self.e.get_row(br, TABLE, k)

    def write(self, br, k, data):
        self.e.commit(br, f"write {k}", "bench", [{"action": "update", "table_name": TABLE, "row_id": k, "data": data}])

    def delete(self, br, k):
        self.e.commit(br, f"delete {k}", "bench", [{"action": "delete", "table_name": TABLE, "row_id": k}])

    def branch(self, name):
        self.e.branch(name, "main")

    def merge(self, name) -> bool:
        r = self.e.merge(name, "main", "bench")
        self.e.delete_branch(name)
        return bool(r["merged"])

    def main_rows(self):
        return {r["row_id"]: {k: v for k, v in r.items() if k != "row_id"} for r in self.e.get_data("main", TABLE)}

    def close_and_size(self) -> int:
        self.e.close()
        return sum(os.path.getsize(p) for p in (self.path, self.path + ".wal") if os.path.exists(p))


class SQLiteBaseline:
    """
    Versioning simulated in SQLite (copy-on-branch).

      branches(name, fork_commit, head)        branch pointers
      commits(id, parent, second_parent, ...)  commit DAG
      cur(branch, key, data)                   materialized current state per branch
      base(branch, key, data)                  copy of main at fork time (merge base)
      hist(commit_id, branch, key, data, del)  append-only history of every row version

    Reads are point lookups in `cur`. A branch copies main's rows into `cur`
    and `base` (O(rows)). A merge runs the same three-way, cell-level merge
    as ChronoDB in Python over base/source/target. Time-travel reads are not
    indexed and are not part of the workload.
    """
    name = "SQLite"

    def __init__(self, d: str):
        self.path = os.path.join(d, "baseline.sqlite")
        self.c = sqlite3.connect(self.path, isolation_level=None)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA synchronous=FULL")
        self.c.executescript("""
            CREATE TABLE branches(name TEXT PRIMARY KEY, fork_commit INTEGER, head INTEGER);
            CREATE TABLE commits(id INTEGER PRIMARY KEY, parent INTEGER, second_parent INTEGER,
                                 branch TEXT, message TEXT, ts REAL);
            CREATE TABLE cur(branch TEXT, key TEXT, data TEXT, PRIMARY KEY(branch, key)) WITHOUT ROWID;
            CREATE TABLE base(branch TEXT, key TEXT, data TEXT, PRIMARY KEY(branch, key)) WITHOUT ROWID;
            CREATE TABLE hist(commit_id INTEGER, branch TEXT, key TEXT, data TEXT, deleted INTEGER);
            CREATE INDEX hist_key ON hist(key, commit_id);
        """)
        self._commit_tx(None, "main", "init", [], new_branch=True)

    def _commit_tx(self, parent, branch, msg, changes, second=None, new_branch=False):
        cur = self.c.execute("INSERT INTO commits(parent, second_parent, branch, message, ts) VALUES (?,?,?,?,?)",
                             (parent, second, branch, msg, time.time()))
        cid = cur.lastrowid
        for k, data in changes:
            if data is None:
                self.c.execute("DELETE FROM cur WHERE branch=? AND key=?", (branch, k))
                self.c.execute("INSERT INTO hist VALUES (?,?,?,?,1)", (cid, branch, k, None))
            else:
                js = json.dumps(data)
                self.c.execute("INSERT OR REPLACE INTO cur VALUES (?,?,?)", (branch, k, js))
                self.c.execute("INSERT INTO hist VALUES (?,?,?,?,0)", (cid, branch, k, js))
        if new_branch:
            self.c.execute("INSERT INTO branches VALUES (?,?,?)", (branch, cid, cid))
        else:
            self.c.execute("UPDATE branches SET head=? WHERE name=?", (cid, branch))
        return cid

    def _head(self, br):
        return self.c.execute("SELECT head FROM branches WHERE name=?", (br,)).fetchone()[0]

    def seed(self, rows):
        self.c.execute("BEGIN")
        self._commit_tx(self._head("main"), "main", "seed", list(rows.items()))
        self.c.execute("COMMIT")

    def read(self, br, k):
        r = self.c.execute("SELECT data FROM cur WHERE branch=? AND key=?", (br, k)).fetchone()
        return json.loads(r[0]) if r else None

    def write(self, br, k, data):
        self.c.execute("BEGIN")
        self._commit_tx(self._head(br), br, f"write {k}", [(k, data)])
        self.c.execute("COMMIT")

    def delete(self, br, k):
        self.c.execute("BEGIN")
        self._commit_tx(self._head(br), br, f"delete {k}", [(k, None)])
        self.c.execute("COMMIT")

    def branch(self, name):
        self.c.execute("BEGIN")
        head = self._head("main")
        cid = self.c.execute("INSERT INTO commits(parent, branch, message, ts) VALUES (?,?,?,?)",
                             (head, name, f"branch from main", time.time())).lastrowid
        self.c.execute("INSERT INTO branches VALUES (?,?,?)", (name, head, cid))
        self.c.execute("INSERT INTO cur SELECT ?, key, data FROM cur WHERE branch='main'", (name,))
        self.c.execute("INSERT INTO base SELECT ?, key, data FROM cur WHERE branch='main'", (name,))
        self.c.execute("COMMIT")

    def _state(self, table, br):
        return {k: json.loads(d) for k, d in self.c.execute(f"SELECT key, data FROM {table} WHERE branch=?", (br,))}

    def merge(self, name) -> bool:
        if self.c.execute("SELECT 1 FROM branches WHERE name=?", (name,)).fetchone() is None:
            raise ValueError(f"Source branch '{name}' does not exist")
        self.c.execute("BEGIN")
        res, conf = three_way(self._state("base", name), self._state("cur", name), self._state("cur", "main"))
        ok = res is not None
        if ok:
            tgt = self._state("cur", "main")
            changes = [(k, v) for k, v in res.items() if tgt.get(k) != v] + [(k, None) for k in tgt if k not in res]
            self._commit_tx(self._head("main"), "main", f"merge {name}", changes, second=self._head(name))
        self.c.execute("DELETE FROM cur WHERE branch=?", (name,))
        self.c.execute("DELETE FROM base WHERE branch=?", (name,))
        self.c.execute("DELETE FROM branches WHERE name=?", (name,))
        self.c.execute("COMMIT")
        return ok

    def main_rows(self):
        return self._state("cur", "main")

    def close_and_size(self) -> int:
        self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.c.close()
        return sum(os.path.getsize(p) for p in (self.path, self.path + "-wal") if os.path.exists(p))


# ─────────────────────────────────────────────────────────────
# Workload experiment (Tables 3/4)
# ─────────────────────────────────────────────────────────────

def pct(xs: List[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))]


def run_ops(sys_cls, seed_rows, ops, expected):
    d = tempfile.mkdtemp(prefix="cdb-bench-")
    try:
        s = sys_cls(d)
        s.seed(seed_rows)
        lat: List[float] = []
        errors = merged = conflicts = invalid = 0
        gc.collect()
        gc.disable()
        t0 = time.perf_counter()
        for op in ops:
            t = time.perf_counter()
            try:
                kind = op[0]
                if kind == "read":
                    s.read(op[1], op[2])
                elif kind == "write":
                    s.write(op[1], op[2], op[3])
                elif kind == "delete":
                    s.delete(op[1], op[2])
                elif kind == "branch":
                    s.branch(op[1])
                else:
                    if s.merge(op[1]):
                        merged += 1
                    else:
                        conflicts += 1
            except Exception as ex:  # noqa: BLE001
                errors += 1
                if op[0] == "merge":
                    invalid += 1
                if errors <= 3:
                    print(f"    {s.name} error on {op[:2]}: {ex}", file=sys.stderr)
            lat.append((time.perf_counter() - t) * 1000.0)
        total = time.perf_counter() - t0
        gc.enable()
        correct = s.main_rows() == expected
        size = s.close_and_size()
        return {
            "throughput": len(ops) / total, "p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99),
            "errors": errors, "storage_bytes": size, "merged": merged, "conflicts": conflicts,
            "invalid": invalid, "final_state_matches_model": correct, "seconds": total,
        }
    finally:
        shutil.rmtree(d, ignore_errors=True)


def exp_workload(ops_list: List[int], trials: int) -> None:
    rows = []
    for n in ops_list:
        for wl in WORKLOADS:
            for t in range(trials):
                seed = 1000 * n + 17 * t + list(WORKLOADS).index(wl)
                seed_rows, ops, expected, counts = generate(wl, n, seed)
                order = [ChronoDB, SQLiteBaseline] if t % 2 == 0 else [SQLiteBaseline, ChronoDB]
                for cls in order:
                    r = run_ops(cls, seed_rows, ops, expected)
                    row = {"ops": n, "workload": wl, "trial": t + 1, "seed": seed, "system": cls.name,
                           **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()},
                           **{f"n_{k}": v for k, v in counts.items()}}
                    rows.append(row)
                    print(f"  {n:>6} {wl:<13} t{t + 1} {cls.name:<8} {r['throughput']:8.1f} ops/s "
                          f"p50={r['p50']:.3f} p95={r['p95']:.3f} p99={r['p99']:.2f} ms "
                          f"err={r['errors']} merged={r['merged']} conf={r['conflicts']} "
                          f"size={r['storage_bytes'] / 1e6:.2f}MB ok={r['final_state_matches_model']}", flush=True)
    write_csv("workload_trials.csv", rows)
    summary = []
    for n in ops_list:
        for wl in WORKLOADS:
            for sysname in ("ChronoDB", "SQLite"):
                rs = [r for r in rows if r["ops"] == n and r["workload"] == wl and r["system"] == sysname]
                if not rs:
                    continue
                agg = {"ops": n, "workload": wl, "system": sysname, "trials": len(rs)}
                for m_ in ("throughput", "p50", "p95", "p99", "storage_bytes"):
                    vals = [r[m_] for r in rs]
                    agg[f"{m_}_mean"] = round(statistics.mean(vals), 4)
                    agg[f"{m_}_sd"] = round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0
                for m_ in ("errors", "merged", "conflicts", "invalid", "n_merge", "n_branch", "n_read", "n_write", "n_delete"):
                    agg[f"{m_}_total"] = sum(r[m_] for r in rs)
                agg["all_runs_match_model"] = all(r["final_state_matches_model"] for r in rs)
                summary.append(agg)
    write_csv("workload_summary.csv", summary)


# ─────────────────────────────────────────────────────────────
# Merge experiment (Table 6)
# ─────────────────────────────────────────────────────────────

def exp_merge(pairs: int) -> None:
    rnd = random.Random(42)
    seed_rows = {f"s{i}": rand_row(rnd) for i in range(SEED_ROWS)}
    plan = []  # (class, branch, src_key, src_data, tgt_key, tgt_data)
    for i in range(pairs):
        k1, k2 = rnd.sample(list(seed_rows), 2)
        plan.append(("non_conflicting", f"nc{i}", k1, rand_row(rnd), k2, rand_row(rnd)))
    for i in range(pairs):
        k = rnd.choice(list(seed_rows))
        a, b = rand_row(rnd), rand_row(rnd)
        b["salary"] = a["salary"] + 1  # guarantee the same cell differs
        plan.append(("conflicting", f"cf{i}", k, a, k, b))
    rnd.shuffle(plan)
    invalid_requests = [f"ghost{i}" for i in range(20)]  # control: branches that never existed

    out = []
    for cls in (ChronoDB, SQLiteBaseline):
        d = tempfile.mkdtemp(prefix="cdb-merge-")
        s = cls(d)
        s.seed(seed_rows)
        tally = {c: {"requests": 0, "merged": 0, "conflicts": 0, "invalid": 0, "lat": []}
                 for c in ("non_conflicting", "conflicting", "invalid_control")}
        for cl, br, sk, sd, tk, td in plan:
            s.branch(br)
            s.write(br, sk, sd)
            s.write("main", tk, td)
            t0 = time.perf_counter()
            try:
                ok = s.merge(br)
                tally[cl]["merged" if ok else "conflicts"] += 1
            except Exception:  # noqa: BLE001
                tally[cl]["invalid"] += 1
            tally[cl]["lat"].append((time.perf_counter() - t0) * 1000)
            tally[cl]["requests"] += 1
        for g in invalid_requests:
            t0 = time.perf_counter()
            try:
                ok = s.merge(g)
                tally["invalid_control"]["merged" if ok else "conflicts"] += 1
            except Exception:  # noqa: BLE001
                tally["invalid_control"]["invalid"] += 1
            tally["invalid_control"]["lat"].append((time.perf_counter() - t0) * 1000)
            tally["invalid_control"]["requests"] += 1
        s.close_and_size()
        shutil.rmtree(d, ignore_errors=True)
        for cl, v in tally.items():
            row = {"system": cls.name, "class": cl, "requests": v["requests"], "merged": v["merged"],
                   "conflicts": v["conflicts"], "invalid": v["invalid"],
                   "merge_p50_ms": round(pct(v["lat"], 50), 3), "merge_p95_ms": round(pct(v["lat"], 95), 3)}
            out.append(row)
            print("  ", row, flush=True)
    write_csv("merge_experiment.csv", out)


# ─────────────────────────────────────────────────────────────
# Storage optimizer experiment (Table 5)
# ─────────────────────────────────────────────────────────────

def build_optimizer_db(path: str, users: int, commits: int, seed: int) -> List[str]:
    """Same generator as the original benchmark_optimizer.py, parameterized and seeded."""
    rnd = random.Random(seed)
    e = VersionEngine(path)
    ch = []
    for i in range(users):
        ch.append({"action": "insert", "table_name": "users", "row_id": f"u-{i:04d}", "data": {
            "username": f"user_{i}", "email": f"user_{i}@company.org",
            "role": "engineer" if i % 2 == 0 else "analyst",
            "department": "Engineering" if i % 2 == 0 else "Data Science",
            "salary": 100000 + i * 2500, "active": True,
            "metadata": f"Initial user registration profile #{i} created at system start."}})
        ch.append({"action": "insert", "table_name": "orders", "row_id": f"ord-{i:04d}", "data": {
            "order_id": f"ORD-2026-{i:05d}", "customer_id": f"u-{i % users:04d}",
            "amount": round(49.99 + i * 12.50, 2), "status": "pending", "priority": "standard",
            "items_count": (i % 5) + 1, "shipping_address": f"{100 + i} Innovation Way, Tech Park, Suite {i}"}})
    hashes = [e.commit("main", "Initial seed data", "system", ch)["hash"]]
    per = max(1, round(users * 0.6))  # 15 of 25 in the original
    for c in range(1, commits):
        muts = []
        for u in rnd.sample(range(users), k=per):
            muts.append({"action": "update", "table_name": "users", "row_id": f"u-{u:04d}", "data": {
                "username": f"user_{u}", "email": f"user_{u}@company.org",
                "role": "senior_engineer" if c > 10 else "engineer",
                "department": "Engineering" if u % 2 == 0 else "Data Science",
                "salary": 100000 + u * 2500 + c * 500, "active": True,
                "metadata": f"Profile update at commit {c} for user {u}."}})
        for o in rnd.sample(range(users), k=per):
            muts.append({"action": "update", "table_name": "orders", "row_id": f"ord-{o:04d}", "data": {
                "order_id": f"ORD-2026-{o:05d}", "customer_id": f"u-{o % users:04d}",
                "amount": round(49.99 + o * 12.50 + c * 2.0, 2),
                "status": "shipped" if c > 8 else "processing",
                "priority": "rush" if c % 3 == 0 else "standard", "items_count": (o % 5) + 1,
                "shipping_address": f"{100 + o} Innovation Way, Tech Park, Suite {o}"}})
        hashes.append(e.commit("main", f"Batch mutation {c}", f"worker-{c % 4}", muts)["hash"])
    e.close()
    return hashes


def snapshot_all(e: VersionEngine, hashes: List[str]) -> Dict[str, Any]:
    return {h: {t: e.query_as_of_commit(t, h) for t in ("users", "orders")} for h in hashes}


def read_latency(e: VersionEngine, hashes: List[str], reps: int = 5) -> Tuple[float, float]:
    """Mean ms to read both tables at the head, and at the oldest quarter of history."""
    old = hashes[: max(1, len(hashes) // 4)]
    t = time.perf_counter()
    for _ in range(reps):
        for tbl in ("users", "orders"):
            e.get_data("main", tbl)
    head_ms = (time.perf_counter() - t) * 1000 / (reps * 2)
    t = time.perf_counter()
    for _ in range(reps):
        for h in old:
            for tbl in ("users", "orders"):
                e.query_as_of_commit(tbl, h)
    hist_ms = (time.perf_counter() - t) * 1000 / (reps * 2 * len(old))
    return head_ms, hist_ms


def exp_optimizer(seeds: int) -> None:
    configs = [(25, 20, k) for k in (3, 5, 10)] + [(25, 100, k) for k in (3, 5, 10)] + \
              [(250, 20, k) for k in (3, 5, 10)] + [(250, 100, k) for k in (3, 5, 10)] + [(1000, 20, 5)]
    rows = []
    for users, commits, k in configs:
        for sd in range(seeds):
            d = tempfile.mkdtemp(prefix="cdb-opt-")
            p = os.path.join(d, "opt.db")
            hashes = build_optimizer_db(p, users, commits, seed=sd)
            e = VersionEngine(p)
            before = snapshot_all(e, hashes)
            head0, hist0 = read_latency(e, hashes)
            stats0 = e.get_storage_stats()
            rep = e.optimize_storage(cold_threshold=k).to_dict()
            e.close()
            e = VersionEngine(p)  # verify after a restart, from disk
            after = snapshot_all(e, hashes)
            head1, hist1 = read_latency(e, hashes)
            stats1 = e.get_storage_stats()
            e.close()
            shutil.rmtree(d, ignore_errors=True)
            row = {"users": users, "orders": users, "commits": commits, "threshold": k, "seed": sd,
                   "versions_scanned": rep["pages_scanned"], "versions_compressed": rep["pages_compressed"],
                   "payload_before": rep["bytes_before"], "payload_after": rep["bytes_after"],
                   "payload_saved_pct": rep["savings_percent"],
                   "allocated_before": rep["live_bytes_before"], "allocated_after": rep["live_bytes_after"],
                   "allocated_saved_pct": rep["live_savings_percent"],
                   "total_payload_before": stats0["total_used_bytes"], "total_payload_after": stats1["total_used_bytes"],
                   "optimizer_ms": rep["duration_ms"],
                   "head_read_ms_before": round(head0, 3), "head_read_ms_after": round(head1, 3),
                   "hist_read_ms_before": round(hist0, 3), "hist_read_ms_after": round(hist1, 3),
                   "results_identical": before == after, "commits_checked": len(hashes)}
            rows.append(row)
            print(f"  U={users:<5} C={commits:<4} k={k:<3} seed={sd} scanned={row['versions_scanned']:>6} "
                  f"comp={row['versions_compressed']:>6} payload {row['payload_before']}->{row['payload_after']} "
                  f"({row['payload_saved_pct']}%) alloc {row['allocated_saved_pct']}% opt={row['optimizer_ms']:.0f}ms "
                  f"hist {row['hist_read_ms_before']}->{row['hist_read_ms_after']}ms ok={row['results_identical']}", flush=True)
    write_csv("optimizer_experiment.csv", rows)


# ─────────────────────────────────────────────────────────────

def write_csv(name: str, rows: List[dict]) -> None:
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def environment() -> dict:
    info = {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count()}
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
        with open("/proc/meminfo") as f:
            info["mem_kb"] = int(f.readline().split()[1])
    except OSError:
        pass
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", choices=["workload", "merge", "optimizer", "all"])
    ap.add_argument("--ops", type=int, nargs="+", default=[5000, 10000])
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--pairs", type=int, default=100)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "environment.json"), "w") as f:
        json.dump(environment(), f, indent=2)
    if a.experiment in ("merge", "all"):
        print("Merge experiment")
        exp_merge(a.pairs)
    if a.experiment in ("optimizer", "all"):
        print("Optimizer experiment")
        exp_optimizer(a.seeds)
    if a.experiment in ("workload", "all"):
        print("Workload experiment")
        exp_workload(a.ops, a.trials)


if __name__ == "__main__":
    main()
