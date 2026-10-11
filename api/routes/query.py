from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_engine
from api.routes._util import call
from api.schemas import QueryRequest, SQLRequest
from engine.src.query.sql import parse_timestamp, run_sql
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["data"])


def _commit_for(engine: VersionEngine, branch_name: str, as_of_commit: Optional[str],
                as_of_timestamp: Optional[str], ref: Optional[str]) -> int:
    if as_of_commit:
        return engine._resolve_commit_id(as_of_commit)
    if as_of_timestamp:
        return engine.commit_at_timestamp(parse_timestamp(as_of_timestamp), branch_name)
    if ref:
        return engine.resolve_ref(ref)
    return engine._head(branch_name)


@router.post("/sql")
def execute_sql(req: SQLRequest, engine: VersionEngine = Depends(get_engine)):
    """Run SQL against a branch. Writes in one request become one commit."""
    return call(lambda: run_sql(engine, req.sql, branch=req.branch_name, author=req.author,
                                message=req.message, dry_run=req.dry_run))


@router.post("/query")
def execute_query(request: QueryRequest, engine: VersionEngine = Depends(get_engine)):
    """Legacy time-travel endpoint: SELECT * FROM <table> with as_of_commit / as_of_timestamp."""
    upper = request.query.upper()
    table_name = request.query[upper.index("FROM ") + 5:].strip().strip(";").split()[0] if "FROM " in upper else ""
    if request.as_of_commit:
        return {"result": call(lambda: engine.query_as_of_commit(table_name, request.as_of_commit))}
    if request.as_of_timestamp:
        return {"result": call(lambda: engine.query_as_of_timestamp(
            table_name, parse_timestamp(request.as_of_timestamp), request.branch_name or "main"))}
    raise HTTPException(status_code=400, detail="Must provide as_of_commit or as_of_timestamp")


@router.get("/tables/{name}")
def get_table_data(name: str, as_of: str = Query(..., description="Commit hash"),
                   engine: VersionEngine = Depends(get_engine)):
    return {"result": call(lambda: engine.query_as_of_commit(table_name=name, commit_hash=as_of))}


@router.get("/tables")
def list_tables(branch_name: str = Query("main"), as_of_commit: Optional[str] = None,
                ref: Optional[str] = None, with_counts: bool = False,
                engine: VersionEngine = Depends(get_engine)):
    def run():
        cid = _commit_for(engine, branch_name, as_of_commit, None, ref)
        tables = engine.tables_at(cid)
        if with_counts:
            return {"tables": tables,
                    "counts": {t: len(engine.read_table_at(t, cid)) for t in tables}}
        return {"tables": tables}
    return call(run)


@router.get("/schema/{table_name}")
def table_schema(table_name: str, branch_name: str = "main", ref: Optional[str] = None,
                 engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.table_schema(table_name, _commit_for(engine, branch_name, None, None, ref)))


@router.get("/data/{table_name}")
def get_data(table_name: str, branch_name: str = Query("main"),
             as_of_commit: Optional[str] = None, as_of_timestamp: Optional[str] = None,
             ref: Optional[str] = None, engine: VersionEngine = Depends(get_engine)):
    def run():
        cid = _commit_for(engine, branch_name, as_of_commit, as_of_timestamp, ref)
        c = engine.catalog.get_commit(cid) or {}
        return {"rows": engine.read_table_at(table_name, cid),
                "commit": {"hash": c.get("hash"), "message": c.get("message"), "timestamp": c.get("timestamp")}}
    return call(run)


@router.get("/rows/{table_name}/{row_id}/history")
def row_history(table_name: str, row_id: str, ref: str = "main", engine: VersionEngine = Depends(get_engine)):
    return {"history": call(lambda: engine.row_history(table_name, row_id, ref))}
