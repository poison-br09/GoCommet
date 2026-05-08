import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.pipeline import router as pipeline_router
from app.api.v1.endpoints.query import router as query_router
from app.core.logger import LOG_FILE, get_logger
from app.db.database import close_db, init_db
from app.graph.workflow import initialize_langgraph_workflow
from app.ingestion.imap_worker import imap_enabled, run_imap_worker

log = get_logger(__name__)
_imap_stop_event: asyncio.Event | None = None
_imap_task: asyncio.Task | None = None

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
    global _imap_stop_event, _imap_task
    log.info("Nova Pipeline starting up  |  log file → %s", LOG_FILE)
    try:
        await init_db()
        log.info("Database initialised successfully")
    except Exception as e:
        log.warning("Database initialisation failed: %s — continuing without DB", e)
    await initialize_langgraph_workflow()
    log.info("LangGraph workflow ready")
    if imap_enabled():
        _imap_stop_event = asyncio.Event()
        _imap_task = asyncio.create_task(run_imap_worker(_imap_stop_event))
        log.info("IMAP ingestion worker enabled")
    else:
        log.info("IMAP ingestion worker disabled")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _imap_stop_event, _imap_task
    log.info("Nova Pipeline shutting down")
    if _imap_stop_event is not None:
        _imap_stop_event.set()
    if _imap_task is not None:
        await _imap_task
        _imap_task = None
        _imap_stop_event = None
    await close_db()
    log.info("Database connections closed")


@app.get("/health", tags=["Health"], summary="Service health check")
async def health_check() -> dict[str, str]:
    log.debug("Health check requested")
    return {"status": "ok"}
