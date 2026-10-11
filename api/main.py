import asyncio

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import branches, commits, maintenance, merge, query

app = FastAPI(title="ChronoDB API", version="2.0.0",
              description="Git-style version control for relational data: branches, commits, "
                          "time travel, three-way merge and a small SQL dialect.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One request at a time: the page store and buffer pool are single-writer.
_request_lock = asyncio.Lock()


@app.middleware("http")
async def serialize_requests(request: Request, call_next):
    async with _request_lock:
        return await call_next(request)


api_router = APIRouter()
for r in (branches.router, commits.router, query.router, merge.router, maintenance.router):
    api_router.include_router(r)

app.include_router(api_router)
app.include_router(api_router, prefix="/api")


@app.get("/")
@app.get("/api")
def root():
    return {
        "status": "ok",
        "service": "ChronoDB API Server",
        "version": "2.0.0",
        "docs": "/docs",
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": str(exc.status_code), "message": str(exc.detail), "details": {}}})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"error": {"code": "422", "message": "Validation Error",
                                           "details": {"errors": exc.errors()}}})


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500,
                        content={"error": {"code": "500", "message": "Internal Server Error",
                                           "details": {"exception": str(exc)}}})
