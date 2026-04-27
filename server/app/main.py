from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.pipeline import router as pipeline_router
from app.api.v1.endpoints.query import router as query_router
from app.core.logger import LOG_FILE, get_logger
from app.db.database import close_db, init_db
from app.graph.workflow import initialize_langgraph_workflow

log = get_logger(__name__)

app = FastAPI(
    title="Nova Pipeline",
    description=(
        "Asynchronous multi-agent trade document processing pipeline.\n\n"
        "All endpoints require an `x-api-key` header. "
        "Click **Authorize**, enter your key, then confirm — all requests will include it automatically."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline_router, prefix="/api/v1")
app.include_router(query_router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup() -> None:
    log.info("Nova Pipeline starting up  |  log file → %s", LOG_FILE)
    try:
        await init_db()
        log.info("Database initialised successfully")
    except Exception as e:
        log.warning("Database initialisation failed: %s — continuing without DB", e)
    await initialize_langgraph_workflow()
    log.info("LangGraph workflow ready")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    log.info("Nova Pipeline shutting down")
    await close_db()
    log.info("Database connections closed")


@app.get("/health", tags=["Health"], summary="Service health check")
async def health_check() -> dict[str, str]:
    log.debug("Health check requested")
    return {"status": "ok"}
