from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from api.schemas import QueryRequest
from api.dependencies import get_engine
from engine.src.version.engine import VersionEngine
import sqlite3

router = APIRouter(tags=["query"])

@router.post("/query")
async def execute_query(request: QueryRequest, engine: VersionEngine = Depends(get_engine)):
    try:
        # Parse table_name from simple queries like "SELECT * FROM users"
        table_name = request.query.split("FROM ")[1].strip().strip(';') if "FROM " in request.query.upper() else ""
        if request.as_of_commit:
            result = engine.query_as_of_commit(
                table_name=table_name,
                commit_hash=request.as_of_commit
            )
            return {"result": result}
        elif request.as_of_timestamp:
            result = engine.query_as_of_timestamp(
                table_name=table_name,
                timestamp=float(request.as_of_timestamp)
            )
            return {"result": result}
        else:
            raise HTTPException(status_code=400, detail="Must provide as_of_commit or as_of_timestamp")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tables/{name}")
async def get_table_data(name: str, as_of: str = Query(..., description="Commit hash"), branch_name: str = "main", engine: VersionEngine = Depends(get_engine)):
    try:
        result = engine.query_as_of_commit(
            table_name=name,
            commit_hash=as_of
        )
        return {"result": result}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── New endpoints for the frontend dashboard ──

@router.get("/tables")
async def list_tables(branch_name: str = Query("main", description="Branch to list tables for"), engine: VersionEngine = Depends(get_engine)):
    """List all table names that have data on the given branch."""
    try:
        tables = engine.get_tables(branch_name=branch_name)
        return {"tables": tables}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data/{table_name}")
async def get_data(table_name: str, branch_name: str = Query("main", description="Branch to read from"), engine: VersionEngine = Depends(get_engine)):
    """Get current data for a table on the specified branch."""
    try:
        rows = engine.get_data(branch_name=branch_name, table_name=table_name)
        return {"rows": rows}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
