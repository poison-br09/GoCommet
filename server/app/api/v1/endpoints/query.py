from fastapi import APIRouter, HTTPException, Security, status
from pydantic import BaseModel

from app.agents.query_agent import generate_answer, generate_sql
from app.core.logger import get_logger
from app.core.security import require_api_key
from app.db.database import get_pool

log = get_logger(__name__)
router = APIRouter(tags=["Query"])

_BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "truncate",
    "alter", "create", "grant", "revoke", "execute",
}


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    sql: str
    answer: str
    rows: list[dict]
    row_count: int


def _is_safe(sql: str) -> bool:
    normalised = sql.lower().split()
    first_token = normalised[0] if normalised else ""
    has_blocked = bool(set(normalised) & _BLOCKED_KEYWORDS)
    return first_token == "select" and not has_blocked


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask a natural language question over pipeline data",
    description=(
        "Converts a plain English question into SQL, executes it against the "
        "stored pipeline results, and returns both a grounded natural language "
        "answer and the raw SQL for transparency.\n\n"
        "**Example questions:**\n"
        "- How many shipments were flagged for review this week?\n"
        "- Show all jobs where port of discharge mismatched.\n"
        "- What is the average confidence score across all jobs?\n"
        "- List the last 5 completed shipments."
    ),
)
async def natural_language_query(
    body: QueryRequest,
    _: str = Security(require_api_key),
) -> QueryResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )

    log.info("NL query  START  |  question=%r", question)

    sql = await generate_sql(question)

    if not _is_safe(sql):
        log.warning("NL query  BLOCKED  |  non-SELECT query rejected: %s", sql)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated query is not a safe read-only SELECT. Please rephrase your question.",
        )

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(sql)
        rows = [dict(r) for r in records]
        log.info("NL query  SQL_OK  |  row_count=%d", len(rows))
    except Exception as exc:
        log.exception("NL query  SQL_FAIL  |  %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query execution failed: {exc}",
        )

    answer = await generate_answer(question, sql, rows)

    log.info("NL query  DONE  |  answer=%r", answer)
    return QueryResponse(
        question=question,
        sql=sql,
        answer=answer,
        rows=rows,
        row_count=len(rows),
    )
