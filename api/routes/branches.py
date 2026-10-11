from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_engine
from api.routes._util import call
from api.schemas import BranchCreate, BranchRename, TagCreate
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["branches"])


@router.post("/branches")
def create_branch(branch: BranchCreate, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.branch(name=branch.name, source_branch=branch.source_branch,
                                      pull_from_main=branch.pull_from_main))


@router.get("/branches")
def list_branches(detailed: bool = True, engine: VersionEngine = Depends(get_engine)):
    return {"branches": engine.list_branches(detailed=detailed), "current": engine.get_current_branch()}


@router.post("/branches/checkout")
@router.post("/branches/{name:path}/checkout")
def checkout_branch(name: str = "", branch_name: str = "", engine: VersionEngine = Depends(get_engine)):
    target = name or branch_name
    if not target:
        raise HTTPException(status_code=400, detail="Branch name is required")
    try:
        return {"checked_out_branch": engine.checkout(branch_name=target)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/branches/{name:path}/rename")
def rename_branch(name: str, body: BranchRename, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.rename_branch(name, body.new_name))


@router.delete("/branches/{name:path}")
def delete_branch(name: str, engine: VersionEngine = Depends(get_engine)):
    ok = call(lambda: engine.delete_branch(name))
    if not ok:
        raise HTTPException(status_code=404, detail=f"Branch '{name}' does not exist")
    return {"deleted": name}


@router.get("/tags")
def list_tags(engine: VersionEngine = Depends(get_engine)):
    return {"tags": engine.list_tags()}


@router.post("/tags")
def create_tag(body: TagCreate, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.create_tag(body.name, body.ref, body.message, body.author))


@router.delete("/tags/{name:path}")
def delete_tag(name: str, engine: VersionEngine = Depends(get_engine)):
    if not engine.delete_tag(name):
        raise HTTPException(status_code=404, detail=f"Tag '{name}' does not exist")
    return {"deleted": name}
