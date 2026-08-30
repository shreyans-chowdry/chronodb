from fastapi import APIRouter, Depends, HTTPException, Query
from api.schemas import MergeRequest
from api.dependencies import get_engine
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["merge"])


@router.get("/diff")
async def get_diff(
    commit_a: str = Query(..., description="Before commit hash (left side)"),
    commit_b: str = Query(..., description="After commit hash (right side)"),
    engine: VersionEngine = Depends(get_engine),
):
    """Compare two commits and return a per-table, per-row diff."""
    try:
        result = engine.diff(commit_hash_a=commit_a, commit_hash_b=commit_b)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/merge")
async def merge_branches(
    request: MergeRequest,
    engine: VersionEngine = Depends(get_engine),
):
    """
    Three-way merge of source_branch into target_branch.

    If conflicts exist and no resolutions are provided, returns
    { status: "conflict", conflicts: [...] } without creating a commit.

    If all conflicts are resolved (or none exist), creates a merge commit.
    """
    try:
        # Convert resolutions list to dict format expected by engine
        resolutions_dict = {}
        if request.resolutions:
            for r in request.resolutions:
                resolutions_dict[r.key] = r.data

        result = engine.merge(
            target_branch=request.target_branch,
            source_branch=request.source_branch,
            author=request.author,
            resolutions=resolutions_dict if resolutions_dict else None,
        )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
