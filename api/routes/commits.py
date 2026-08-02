from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from api.schemas import CommitCreate, RollbackRequest
from api.dependencies import get_engine
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["commits"])

@router.post("/commits")
async def create_commit(commit: CommitCreate, engine: VersionEngine = Depends(get_engine)):
    try:
        result = engine.commit(
            branch_name=commit.branch_name,
            message=commit.message,
            author=commit.author,
            changes=commit.changes
        )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/commits")
async def get_commits(branch_name: Optional[str] = None, engine: VersionEngine = Depends(get_engine)):
    try:
        b_name = branch_name or engine.get_current_branch()
        history = engine.get_commit_history(branch_name=b_name)
        return {"commits": history}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rollback/{commit_hash}")
async def rollback_commit(commit_hash: str, request: RollbackRequest, engine: VersionEngine = Depends(get_engine)):
    if commit_hash != request.target_commit_hash:
        raise HTTPException(status_code=400, detail="Path parameter and body commit hash mismatch")
    
    try:
        result = engine.rollback(
            branch_name=request.branch_name,
            target_commit_hash=request.target_commit_hash,
            author=request.author
        )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
