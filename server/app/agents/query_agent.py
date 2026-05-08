import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)
openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

_SCHEMA = """\
Table: graph_threads
  thread_id  TEXT         — unique job ID (primary key)
  updated_at TIMESTAMPTZ  — when the record was last written
  state      JSONB        — full pipeline state

JSONB fields inside `state`:
  incoming_email              JSONB  — sender, subject, attachment_paths
  human_review_status         TEXT   — "processing" | "pending" | "approved" | "sent"
  final_decision              TEXT   — "auto_approve" | "flag_for_review" | "draft_amendment" | null (null = still processing)
  decision_reasoning_or_draft TEXT   — agent reasoning or draft approval/amendment email text
  extracted_data              JSONB ARRAY — one object per attached document
    each item has document_name, path, and field objects stored as {"value": ..., "confidence": ...}
    item → consignee_name     → value  TEXT
    item → port_of_loading    → value  TEXT
    item → port_of_discharge  → value  TEXT
    item → incoterms          → value  TEXT
    item → hs_code            → value  TEXT
    item → gross_weight       → value  TEXT
    item → invoice_number     → value  TEXT
    item → description_of_goods → value TEXT
    item → global_confidence_score  FLOAT
  validation_results  JSONB ARRAY — each element: {"field_name": TEXT, "status": "match"|"mismatch"|"uncertain", "found_value": TEXT, "expected_value": TEXT, "document_name": TEXT, "validation_type": TEXT}

Common PostgreSQL JSONB patterns for this table:
  -- top-level text field
  state->>'final_decision'

  -- nested text value inside extracted_data
  (state->'extracted_data'->0->'port_of_discharge'->>'value')

  -- nested float (requires cast)
  (state->'extracted_data'->0->>'global_confidence_score')::float

  -- jobs that have any mismatched field
  state->'validation_results' @> '[{"status":"mismatch"}]'::jsonb

  -- jobs that have any uncertain field
  state->'validation_results' @> '[{"status":"uncertain"}]'::jsonb

  -- expand validation_results array into rows (for aggregating per-field stats)
  jsonb_array_elements(state->'validation_results') AS v

  -- completed jobs only (pipeline finished)
  state->>'human_review_status' = 'sent'

  -- jobs waiting for CG approval
  state->>'human_review_status' = 'pending'

  -- jobs processed today
  updated_at >= CURRENT_DATE

  -- jobs processed this week
  updated_at >= NOW() - INTERVAL '7 days'\

Table: email_audit
  thread_id              TEXT PRIMARY KEY — pipeline thread linked to graph_threads.thread_id
  incoming_sender        TEXT             — original SU sender
  incoming_subject       TEXT             — original inbound email subject
  attachment_file_names  JSONB ARRAY      — names of attached files
  attachment_paths       JSONB ARRAY      — stored local attachment paths
  final_decision         TEXT             — router decision at send time
  human_review_status    TEXT             — usually "sent"
  validation_results     JSONB ARRAY      — validation rows at send time
  outgoing_to            TEXT             — recipient of CG reply
  outgoing_subject       TEXT             — sent reply subject
  outgoing_body          TEXT             — approved reply content
  delivery               TEXT             — "smtp" or "mock"
  send_status            TEXT             — send status
  message_id             TEXT             — SMTP Message-ID / delivery receipt id
  sent_at                TIMESTAMPTZ      — send timestamp

Use email_audit for questions about sent mail, delivery IDs, sent content, inbound email subjects, and attachment file names. Join with graph_threads on thread_id when pipeline state is also needed.\
"""

_SQL_SYSTEM = """\
You are a PostgreSQL expert writing read-only queries for a trade document pipeline database. \
Given a plain English question and the schema below, write exactly one SELECT statement \
that answers it. Return ONLY the SQL — no explanation, no markdown fences, no comments.\
"""

_ANSWER_SYSTEM = """\
You are a helpful assistant for a trade document processing pipeline. \
Given a question, the SQL that was executed, and the query results, write a clear \
1–3 sentence answer grounded strictly in the data. Do not invent facts not present \
in the results. If there are no rows, say so plainly.\
"""


async def generate_sql(question: str) -> str:
    user_prompt = f"""\
Schema:
{_SCHEMA}

Question: {question}

Rules:
- Write one SELECT query only.
- For aggregate queries (COUNT, SUM, AVG, MAX, MIN) do not add LIMIT.
- For row-returning queries add LIMIT 50 unless the question implies a different limit.
- Return ONLY the SQL, nothing else.\
"""
    log.info("query_agent  SQL_GEN  START  |  question=%r", question)
    response = await openai_client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": _SQL_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_output_tokens=400,
    )
    sql = response.output_text.strip()

    # Strip markdown fences if the model wrapped the SQL anyway
    if sql.startswith("```"):
        lines = sql.splitlines()
        sql = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    log.info("query_agent  SQL_GEN  DONE  |  sql=%s", sql)
    return sql


async def generate_answer(question: str, sql: str, rows: list[dict]) -> str:
    results_text = (
        json.dumps(rows, default=str, indent=2) if rows else "No rows returned."
    )
    user_prompt = f"""\
Question: {question}

SQL executed:
{sql}

Results ({len(rows)} row(s)):
{results_text}

Answer the question in 1–3 sentences based strictly on these results.\
"""
    log.info("query_agent  ANSWER_GEN  START  |  row_count=%d", len(rows))
    response = await openai_client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_output_tokens=200,
    )
    answer = response.output_text.strip()
    log.info("query_agent  ANSWER_GEN  DONE  |  answer=%r", answer)
    return answer
