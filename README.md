# ChronoDB

A relational database engine with Git-style version control built into the storage layer: commits, branches, tags, non-destructive rollback, time-travel queries and three-way merge, behind a FastAPI service and a Next.js dashboard.

## What it does

- **Every write is a commit.** Rows are never overwritten; each change adds a version to the row's version chain in a version-aware B+ tree.
- **Branches cost O(1).** A branch is a pointer into the commit DAG; nothing is copied.
- **Time travel.** Read any table as of a commit, branch, tag or timestamp (`AS OF ...` in SQL, or the timeline in the dashboard).
- **Three-way merge** with cell-level auto-merge. Rows changed differently on both sides are returned as conflicts for you to resolve.
- **Rollback and revert.** Roll a branch back to any earlier commit, or undo one commit, without rewriting history.
- **Storage optimizer.** Old versions are delta-encoded and packed into shared pages, which frees their 4 KB snapshot pages.
- **Crash safety.** Each operation is one WAL transaction (group-committed with one fsync) and is replayed on restart.
- **SQL.** `SELECT` (WHERE, ORDER BY, GROUP BY, COUNT/SUM/AVG/MIN/MAX, LIMIT), `INSERT`, `UPDATE`, `DELETE`, `SHOW TABLES|BRANCHES|TAGS|LOG`, `DESCRIBE`. All writes in one request become one commit.

## Run it

```bash
pip install -e .                       # fastapi, uvicorn, pydantic, pytest
python3 scripts/seed_demo.py           # optional: sample company data with branches, a tag and a merge conflict
python3 -m uvicorn api.main:app --port 8000

cd frontend && npm install && npm run dev   # http://localhost:3000
```

Or run both with `./scripts/start.sh`. API docs are at http://localhost:8000/docs.

### Dashboard

| View | What you can do |
|---|---|
| Data | Edit cells in place, add/delete rows and columns, stage changes and commit them together; click a row id for its full history |
| Timeline (top bar) | Scrub through the branch's commits; the whole workspace shows the database as of that commit |
| SQL | Run queries with time travel; writes become one commit; examples and recent queries |
| History | Every commit with its row-level diff; roll back, revert one commit, tag |
| Graph | The commit DAG with branch lanes and merge edges |
| Compare & merge | Diff two branches, preview the merge, resolve conflicts cell by cell |
| Storage | Version statistics, delta compression, garbage collection, branch and tag management |

## Layout

```
engine/src/storage   pages, disk manager (free list), buffer pool, delta encoding, packed delta heap, optimizer
engine/src/wal       write-ahead log and redo recovery
engine/src/index     version-aware B+ tree with overflow pages for long version chains
engine/src/version   catalog (append-only commit log), version engine, garbage collector
engine/src/merge     three-way merge
engine/src/query     SQL parser and executor
api/                 FastAPI service
frontend/            Next.js dashboard
benchmarks/          paper experiments and results
```

## Tests

```bash
python3 -m pytest            # 167 tests: unit, API, the seven-case correctness suite and regression tests
```

`engine/tests/test_correctness_suite.py` contains the correctness suite reported in the paper (commit and read back, branch isolation, clean merge, conflicting merge, rollback, compression with historical reads, crash recovery in a killed child process).

## Reproducing the paper's experiments

```bash
python3 benchmarks/paper_experiments.py merge --pairs 100
python3 benchmarks/paper_experiments.py optimizer --seeds 3
python3 benchmarks/paper_experiments.py workload --ops 5000 10000 --trials 5
```

Results are written to `benchmarks/results/` (`environment.json` records the machine). Operation sequences are generated from fixed seeds before either system runs, so ChronoDB and the SQLite baseline execute identical operations, and each run's final state is checked against a reference model.
