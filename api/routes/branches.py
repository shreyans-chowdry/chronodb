from fastapi import APIRouter, Depends, HTTPException
from api.schemas import BranchCreate
from api.dependencies import get_engine
from engine.src.version.engine import VersionEngine

router = APIRouter(prefix="/branches", tags=["branches"])

@router.post("")
async def create_branch(branch: BranchCreate, engine: VersionEngine = Depends(get_engine)):
    try:
        result = engine.branch(name=branch.name, source_branch=branch.source_branch)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def list_branches(engine: VersionEngine = Depends(get_engine)):
    try:
        branches = engine.list_branches()
        return {"branches": branches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/checkout")
@router.post("/{name:path}/checkout")
async def checkout_branch(name: str = "", branch_name: str = "", engine: VersionEngine = Depends(get_engine)):
    target = name or branch_name
    if not target:
        raise HTTPException(status_code=400, detail="Branch name is required")
    try:
        current = engine.checkout(branch_name=target)
        return {"checked_out_branch": current}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
