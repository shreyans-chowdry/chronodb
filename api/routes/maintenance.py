import os
import sys

from fastapi import APIRouter, Depends

from api.dependencies import _lock, db_path, get_engine, reset_engine
from api.routes._util import call
from api.schemas import OptimizeRequest
from engine.src.version.engine import VersionEngine

router = APIRouter(tags=["maintenance"])


@router.get("/stats")
def stats(engine: VersionEngine = Depends(get_engine)):
    overview = engine.get_overview()
    overview["storage"] = engine.get_storage_stats()
    overview["db_path"] = os.path.basename(engine.db_path)
    return overview


@router.post("/maintenance/optimize")
def optimize(req: OptimizeRequest, engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.optimize_storage(cold_threshold=req.cold_threshold).to_dict())


@router.post("/maintenance/gc")
def gc(engine: VersionEngine = Depends(get_engine)):
    return call(lambda: engine.gc().to_dict())


@router.post("/maintenance/checkpoint")
def checkpoint(engine: VersionEngine = Depends(get_engine)):
    return engine.checkpoint()


@router.post("/demo/reset")
def reset_demo():
    """Recreate the demo database from scripts/seed_demo.py."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.seed_demo import seed
    with _lock:
        reset_engine()
        seed(db_path(), quiet=True)
    return {"status": "ok"}
