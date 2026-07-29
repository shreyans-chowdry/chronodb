# ChronoDB

A Version-Controlled Database Engine with Git-like Branch, Commit, and Rollback Semantics.

## Overview
ChronoDB is a specialized database system designed to support immutable versioning, copy-on-write branching, zero-copy checkouts, and transactional commits directly at the storage engine level.

## Repository Structure
```
chronodb/
├── .github/
│   ├── workflows/
│   └── ISSUE_TEMPLATE/
├── engine/                     # Core storage/version engine
│   ├── src/
│   │   ├── storage/            # page manager, buffer pool
│   │   ├── wal/                # write-ahead log
│   │   ├── index/              # B+ Tree
│   │   ├── version/            # commit DAG, branches, version chains
│   │   ├── query/              # parser, planner, executor
│   │   └── merge/              # conflict detection, three-way merge
│   └── tests/
├── api/                        # FastAPI service layer
│   ├── routes/
│   ├── auth/
│   └── tests/
├── frontend/                   # Next.js dashboard
│   ├── app/
│   ├── components/
│   └── tests/
├── benchmarks/                 # workload generators, result CSVs, plots
├── research/                   # literature notes, draft paper, related work
├── docs/                       # architecture docs, API docs, ADRs
├── scripts/                    # dev setup, seed data, benchmark runners
├── docker-compose.yml
└── README.md
```

## Getting Started
Follow the documentation in `docs/` to set up and run ChronoDB locally.
