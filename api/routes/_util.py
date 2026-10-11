from typing import Any, Callable

from fastapi import HTTPException

from engine.src.query.sql import SQLError


def call(fn: Callable[[], Any]) -> Any:
    """Run an engine call, mapping engine errors to HTTP errors."""
    try:
        return fn()
    except HTTPException:
        raise
    except SQLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (ValueError, KeyError) as e:
        msg = str(e).strip("'\"")
        code = 404 if ("does not exist" in msg or "not found" in msg.lower()) else 400
        raise HTTPException(status_code=code, detail=msg)
