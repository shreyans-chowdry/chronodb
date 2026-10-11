"""
Correctness suite (paper, Table 7) plus regression tests for defects fixed in
the engine overhaul. Each test is small and deterministic.

Run:  python -m pytest engine/tests/test_correctness_suite.py -v
"""

import os
import random
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.src.version.engine import VersionEngine  # noqa: E402
from engine.src.query.sql import run_sql  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "suite.db")


@pytest.fixture
def engine(db):
    e = VersionEngine(db)
    yield e
    e.close()


def ins(table, rid, data):
    return {"action": "insert", "table_name": table, "row_id": rid, "data": data}


def upd(table, rid, data):
    return {"action": "update", "table_name": table, "row_id": rid, "data": data}


def rows(engine, branch, table):
    return {r["row_id"]: {k: v for k, v in r.items() if k != "row_id"} for r in engine.get_data(branch, table)}


# ─────────────────────────────────────────────────────────────
# Table 7: the seven correctness scenarios
# ─────────────────────────────────────────────────────────────

class TestCorrectnessSuite:

    def test_1_commit_then_read_previous_version(self, engine):
        c1 = engine.commit("main", "v1", "t", [ins("acct", "a1", {"balance": 100})])
        engine.commit("main", "v2", "t", [upd("acct", "a1", {"balance": 250})])
        assert engine.query_as_of_commit("acct", c1["hash"]) == [{"row_id": "a1", "balance": 100}]
        assert engine.get_data("main", "acct") == [{"row_id": "a1", "balance": 250}]

    def test_2_branch_isolation(self, engine):
        engine.commit("main", "base", "t", [ins("acct", "a1", {"balance": 100})])
        engine.branch("left", "main")
        engine.branch("right", "main")
        engine.commit("left", "L", "t", [upd("acct", "a1", {"balance": 1})])
        engine.commit("right", "R", "t", [ins("acct", "a2", {"balance": 2})])
        assert rows(engine, "left", "acct") == {"a1": {"balance": 1}}
        assert rows(engine, "right", "acct") == {"a1": {"balance": 100}, "a2": {"balance": 2}}
        assert rows(engine, "main", "acct") == {"a1": {"balance": 100}}

    def test_3_merge_changes_to_different_rows(self, engine):
        engine.commit("main", "base", "t", [ins("acct", "a1", {"v": 0}), ins("acct", "a2", {"v": 0})])
        engine.branch("feature", "main")
        engine.commit("feature", "f", "t", [upd("acct", "a1", {"v": 1})])
        engine.commit("main", "m", "t", [upd("acct", "a2", {"v": 2})])
        res = engine.merge("feature", "main", "t")
        assert res["merged"] and res["strategy"] == "three-way"
        assert rows(engine, "main", "acct") == {"a1": {"v": 1}, "a2": {"v": 2}}
        assert res["commit"]["second_parent_id"] is not None

    def test_4_merge_conflicting_updates_to_same_row(self, engine):
        engine.commit("main", "base", "t", [ins("acct", "a1", {"v": 0})])
        engine.branch("feature", "main")
        engine.commit("feature", "f", "t", [upd("acct", "a1", {"v": 1})])
        engine.commit("main", "m", "t", [upd("acct", "a1", {"v": 2})])
        head_before = engine.catalog.get_branch("main")["head_commit_id"]
        res = engine.merge("feature", "main", "t")
        assert res["merged"] is False
        assert [(c["row_id"], c["conflicting_cells"]) for c in res["conflicting_rows"]] == [("a1", ["v"])]
        # No merge commit was written
        assert engine.catalog.get_branch("main")["head_commit_id"] == head_before
        # Resolving the conflict completes the merge
        res2 = engine.merge("feature", "main", "t", resolutions={"acct:a1": {"v": 3}})
        assert res2["merged"] and rows(engine, "main", "acct") == {"a1": {"v": 3}}

    def test_5_rollback_preserves_history(self, engine):
        c1 = engine.commit("main", "v1", "t", [ins("acct", "a1", {"v": 1})])
        engine.commit("main", "v2", "t", [upd("acct", "a1", {"v": 2}), ins("acct", "a2", {"v": 9})])
        n_before = len(engine.get_log("main")[0])
        rb = engine.rollback("main", c1["hash"], "t")
        assert rows(engine, "main", "acct") == {"a1": {"v": 1}}
        log, _ = engine.get_log("main")
        assert len(log) == n_before + 1 and log[0]["id"] == rb["id"]
        assert any(c["message"] == "v2" for c in log)  # intermediate commit still there

    def test_6_compress_then_query_history(self, engine):
        commits = []
        for i in range(30):
            commits.append(engine.commit("main", f"c{i}", "t", [upd("acct", f"a{i % 3}", {"v": i, "pad": "x" * 40})]))
        expected = {c["hash"]: engine.query_as_of_commit("acct", c["hash"]) for c in commits}
        rep = engine.optimize_storage(cold_threshold=3)
        assert rep.pages_compressed > 0
        for h, want in expected.items():
            assert engine.query_as_of_commit("acct", h) == want

    def test_7_restart_and_crash_recovery(self, db):
        # A child process commits and is killed without close(); the parent reopens.
        script = textwrap.dedent(f"""
            import sys, os
            sys.path.insert(0, {ROOT!r})
            from engine.src.version.engine import VersionEngine
            e = VersionEngine({db!r})
            for i in range(50):
                e.commit("main", f"c{{i}}", "t", [{{"action": "insert", "table_name": "acct",
                         "row_id": f"a{{i}}", "data": {{"v": i}}}}])
            os._exit(0)   # no close(), no checkpoint
        """)
        subprocess.run([sys.executable, "-c", script], check=True)
        e = VersionEngine(db)
        try:
            assert e.last_recovery["status"] == "recovered"
            assert len(e.get_data("main", "acct")) == 50
        finally:
            e.close()


# ─────────────────────────────────────────────────────────────
# Regression tests for defects found in the original engine
# ─────────────────────────────────────────────────────────────

class TestRegressions:

    def test_reopen_after_btree_root_split(self, db):
        e = VersionEngine(db)
        for i in range(300):
            e.commit("main", "c", "t", [ins("t", f"r{i}", {"v": i, "pad": "y" * 30})])
        e.close()
        e = VersionEngine(db)
        assert len(e.get_data("main", "t")) == 300
        e.close()

    def test_long_version_chain(self, engine):
        for i in range(800):
            engine.commit("main", "c", "t", [upd("t", "hot", {"v": i})])
        assert engine.get_row("main", "t", "hot") == {"row_id": "hot", "v": 799}
        first = engine.get_log("main", limit=1000)[0][-2]  # oldest commit with data
        assert engine.query_as_of_commit("t", first["hash"]) == [{"row_id": "hot", "v": 0}]

    def test_timestamp_query_respects_branch(self, engine):
        import time
        engine.commit("main", "m", "t", [ins("t", "r", {"v": "main"})])
        engine.branch("f", "main")
        engine.commit("f", "f", "t", [upd("t", "r", {"v": "feature"})])
        assert engine.query_as_of_timestamp("t", time.time(), "main") == [{"row_id": "r", "v": "main"}]
        assert engine.query_as_of_timestamp("t", time.time(), "f") == [{"row_id": "r", "v": "feature"}]

    def test_rollback_only_rewrites_changed_rows(self, engine):
        c1 = engine.commit("main", "v1", "t", [ins("t", f"r{i}", {"v": i}) for i in range(20)])
        engine.commit("main", "v2", "t", [upd("t", "r3", {"v": 99})])
        rb = engine.rollback("main", c1["hash"], "t")
        assert rb["stats"] == {"insert": 0, "update": 1, "delete": 0}

    def test_gc_keeps_deltas_whose_base_is_reclaimed(self, engine):
        engine.commit("main", "base", "t", [ins("t", "r", {"v": 0})])
        engine.branch("side", "main")
        for i in range(1, 8):
            engine.commit("side", f"s{i}", "t", [upd("t", "r", {"v": i})])
        engine.merge("side", "main", "t")           # fast-forward main onto side
        engine.optimize_storage(cold_threshold=2)    # deltas now point at older snapshots
        engine.delete_branch("side")
        engine.gc()
        for c in engine.get_log("main")[0]:
            engine.query_as_of_commit("t", c["hash"])  # every version still readable
        assert rows(engine, "main", "t") == {"r": {"v": 7}}

    def test_merge_keeps_null_values(self, engine):
        engine.commit("main", "base", "t", [ins("t", "r", {"a": 1, "b": None, "c": 0})])
        engine.branch("f", "main")
        engine.commit("f", "f", "t", [upd("t", "r", {"a": 2, "b": None, "c": 0})])
        engine.commit("main", "m", "t", [upd("t", "r", {"a": 1, "b": None, "c": 5})])
        engine.merge("f", "main", "t")
        assert rows(engine, "main", "t") == {"r": {"a": 2, "b": None, "c": 5}}

    def test_invalid_change_rejected_before_write(self, engine):
        head = engine.catalog.get_branch("main")["head_commit_id"]
        with pytest.raises(ValueError):
            engine.commit("main", "bad", "t", [{"action": "upsertt", "table_name": "t", "row_id": "1", "data": {}}])
        with pytest.raises(ValueError):
            engine.commit("main", "big", "t", [ins("t", "1", {"blob": "x" * 5000})])
        assert engine.catalog.get_branch("main")["head_commit_id"] == head

    def test_randomized_against_model(self, engine):
        """Random commits on two branches; every historical commit is compared to a dict model."""
        rnd = random.Random(7)
        model = {engine.catalog.get_branch("main")["head_commit_id"]: {}}
        engine.branch("b", "main")
        model[engine.catalog.get_branch("b")["head_commit_id"]] = {}
        for _ in range(150):
            br = rnd.choice(["main", "b"])
            head = engine.catalog.get_branch(br)["head_commit_id"]
            state = dict(model[head])
            rid = f"r{rnd.randint(0, 15)}"
            if rid in state and rnd.random() < 0.25:
                ch = {"action": "delete", "table_name": "t", "row_id": rid}
                del state[rid]
            else:
                state[rid] = {"v": rnd.randint(0, 9)}
                ch = upd("t", rid, state[rid])
            c = engine.commit(br, "x", "t", [ch])
            model[c["id"]] = state
            if rnd.random() < 0.1:
                engine.optimize_storage(cold_threshold=rnd.choice([1, 2, 4]))
        for cid, state in model.items():
            got = {r["row_id"]: {"v": r["v"]} for r in engine.read_table_at("t", cid)}
            assert got == state


class TestSQL:

    def test_sql_roundtrip_and_time_travel(self, engine):
        r = run_sql(engine, "INSERT INTO emp (id, name, salary) VALUES (1, 'Asha', 100), (2, 'Ravi', 80);")
        first = r["commit"]["hash"]
        run_sql(engine, "UPDATE emp SET salary = salary * 2 WHERE name = 'Asha'; DELETE FROM emp WHERE id = 2;")
        now = run_sql(engine, "SELECT name, salary FROM emp ORDER BY salary DESC")["results"][0]["rows"]
        then = run_sql(engine, f"SELECT name, salary FROM emp AS OF COMMIT '{first}' ORDER BY name")["results"][0]["rows"]
        assert now == [{"name": "Asha", "salary": 200}]
        assert then == [{"name": "Asha", "salary": 100}, {"name": "Ravi", "salary": 80}]

    def test_sql_script_is_one_commit(self, engine):
        before = len(engine.catalog.commits)
        run_sql(engine, "INSERT INTO t (id, v) VALUES (1, 1); INSERT INTO t (id, v) VALUES (2, 2); UPDATE t SET v = 5;")
        assert len(engine.catalog.commits) == before + 1

    def test_sql_errors_write_nothing(self, engine):
        before = len(engine.catalog.commits)
        with pytest.raises(ValueError):
            run_sql(engine, "INSERT INTO t (id) VALUES (1); INSERT INTO t (id) VALUES (1);")
        assert len(engine.catalog.commits) == before

    def test_sql_aggregates_and_refs(self, engine):
        run_sql(engine, "INSERT INTO p (id, cat, price) VALUES (1,'a',10),(2,'a',30),(3,'b',5)")
        engine.create_tag("v1.0", "main")
        run_sql(engine, "DELETE FROM p WHERE cat = 'b'")
        g = run_sql(engine, "SELECT cat, COUNT(*) AS n, AVG(price) AS avg FROM p AS OF TAG v1.0 GROUP BY cat ORDER BY cat")
        assert g["results"][0]["rows"] == [{"cat": "a", "n": 2, "avg": 20}, {"cat": "b", "n": 1, "avg": 5}]
