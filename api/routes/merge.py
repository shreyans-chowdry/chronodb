from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from api.schemas import MergeRequest
from api.dependencies import get_engine
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["merge"])


@router.post("/merge")
async def merge_branches(
    req: MergeRequest, engine: VersionEngine = Depends(get_engine)
):
    """
    Three-way merge of source_branch into target_branch.

    Returns 200 with the merge commit on success.
    Returns 409 with {"conflicting_rows": [...]} when conflicts exist.
    """
    try:
        result = engine.merge(
            source_branch=req.source_branch,
            target_branch=req.target_branch,
            author=req.author,
        )

        if not result["merged"]:
            return JSONResponse(
                status_code=409,
                content={"conflicting_rows": result["conflicting_rows"]},
            )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
