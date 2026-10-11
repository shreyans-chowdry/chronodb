from fastapi import APIRouter, Depends, Query

from api.dependencies import get_engine
from api.routes._util import call
from api.schemas import MergeRequest
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["merge"])


@router.get("/diff")
def get_diff(commit_a: str = Query(..., description="Left side: commit hash, branch or tag"),
             commit_b: str = Query(..., description="Right side: commit hash, branch or tag"),
             engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.diff(commit_hash_a=commit_a, commit_hash_b=commit_b))


@router.get("/compare")
def compare_branches(base: str, head: str, engine: VersionEngine = Depends(get_engine)):
    """Diff between two branches plus a dry-run of merging head into base."""
    def run():
        diff = engine.diff(base, head)
        preview = engine.merge(head, base, "preview", dry_run=True) if base != head else None
        b_anc = engine.catalog.ancestors(engine.resolve_ref(base))
        h_anc = engine.catalog.ancestors(engine.resolve_ref(head))
        return {"diff": diff, "merge_preview": preview,
                "ahead": len(h_anc - b_anc), "behind": len(b_anc - h_anc)}
    return call(run)


@router.post("/merge")
def merge_branches(request: MergeRequest, engine: VersionEngine = Depends(get_engine)):
    resolutions = {r.key: r.data for r in request.resolutions} if request.resolutions else None
    result = call(lambda: engine.merge(
        source_branch=request.source_branch, target_branch=request.target_branch,
        author=request.author, resolutions=resolutions, dry_run=request.dry_run,
        message=request.message))
    if request.dry_run:
        return {"status": "preview", **result}
    if result.get("merged"):
        return {"status": "ok", "commit": result.get("commit"), "strategy": result.get("strategy"),
                "applied_changes": result.get("applied_changes", 0),
                "auto_merged_rows": result.get("auto_merged_rows", [])}
    return {"status": "conflict", "conflicts": result.get("conflicting_rows", []),
            "auto_resolved": result.get("auto_merged_rows", [])}
