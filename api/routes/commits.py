from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_engine
from api.routes._util import call
from api.schemas import CommitCreate, RevertRequest, RollbackRequest
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["commits"])


@router.post("/commits")
def create_commit(commit: CommitCreate, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.commit(branch_name=commit.branch_name, message=commit.message,
                                      author=commit.author, changes=commit.changes))


@router.get("/commits/graph")
def get_commit_graph(engine: VersionEngine = Depends(get_engine)):
    """All commits across all branches, for the DAG view."""
    return {"commits": engine.get_all_commits(), "branches": engine.list_branches(detailed=True),
            "tags": engine.list_tags()}


@router.get("/commits")
def get_commits(
    branch_name: Optional[str] = None,
    mode: str = Query("own", description="'own' = commits made on the branch, 'log' = full ancestry"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    engine: VersionEngine = Depends(get_engine),
):
    ref = branch_name or engine.get_current_branch()
    if mode == "log":
        commits, total = call(lambda: engine.get_log(ref, limit=limit, offset=offset))
        return {"commits": commits, "total": total}
    try:
        return {"commits": engine.get_commit_history(branch_name=ref, limit=limit)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/commits/{ref:path}")
def get_commit(ref: str, engine: VersionEngine = Depends(get_engine)):
    """Commit metadata plus the row-level changes it introduced."""
    return call(lambda: engine.get_commit(ref))


@router.post("/rollback/{commit_hash}")
def rollback_commit(commit_hash: str, request: RollbackRequest, engine: VersionEngine = Depends(get_engine)):
    if commit_hash != request.target_commit_hash:
        raise HTTPException(status_code=400, detail="Path parameter and body commit hash mismatch")
    return call(lambda: engine.rollback(branch_name=request.branch_name,
                                        target_commit_hash=request.target_commit_hash,
                                        author=request.author))


@router.post("/revert/{commit_hash}")
def revert_commit(commit_hash: str, request: RevertRequest, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.revert_commit(request.branch_name, commit_hash, request.author))
