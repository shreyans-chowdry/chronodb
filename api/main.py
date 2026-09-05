from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from api.routes import branches, commits, query, merge

app = FastAPI(title="ChronoDB API")

# CORS — allow Next.js dev server and any local network origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(branches.router)
app.include_router(commits.router)
app.include_router(query.router)
app.include_router(merge.router)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "ChronoDB API Server",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/branches", "/commits", "/tables", "/data/{table_name}", "/diff", "/merge"]
    }

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": str(exc.status_code),
                "message": str(exc.detail),
                "details": {}
            }
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "422",
                "message": "Validation Error",
                "details": {"errors": exc.errors()}
            }
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "500",
                "message": "Internal Server Error",
                "details": {"exception": str(exc)}
            }
        },
    )
