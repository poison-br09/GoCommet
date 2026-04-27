# Nova Pipeline — Server

Async multi-agent trade document processing pipeline.  
Accepts Bills of Lading, Commercial Invoices, and Packing Lists (PDF / PNG / JPG) and runs them through three agents:

1. **Extractor** — Mistral OCR + OpenAI GPT-4o-mini → structured JSON with per-field confidence scores  
2. **Validator** — GPT-4o-mini checks extracted fields against customer rules (port of discharge, Incoterms)  
3. **Router** — GPT-4o-mini decides: auto-approve, flag for review, or draft amendment email

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| PostgreSQL | 14+ (running locally) |
| OpenAI API key | — |
| Mistral API key | — |

---

## Setup

### 1. Create and activate a virtual environment

```bash
cd server
python3 -m venv gocometvenv
source gocometvenv/bin/activate      # macOS / Linux
# gocometvenv\Scripts\activate       # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create the database

Connect to PostgreSQL and create the database:

```sql
CREATE DATABASE Nova;
```

The `graph_threads` table is created automatically on first startup.

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
DATABASE_URL=postgresql+asyncpg://postgres:your_password@localhost:5432/Nova
API_KEY=your_chosen_api_key
```

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key (used by Extractor, Validator, Router, Query agents) |
| `MISTRAL_API_KEY` | Mistral API key (used for OCR) |
| `DATABASE_URL` | PostgreSQL connection string using `asyncpg` driver |
| `API_KEY` | Secret key required in the `x-api-key` header for all API requests |

---

## Run

```bash
cd server
source gocometvenv/bin/activate
uvicorn app.main:app --reload
```

Server starts at **http://localhost:8000**

> **Note:** `uvicorn --reload` only watches `.py` files. If you change `.env`, restart the server manually with `Ctrl+C` then re-run.

---

## API Endpoints

Interactive docs available at **http://localhost:8000/docs** — click **Authorize** and enter your `API_KEY` before making requests.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/api/v1/pipeline/process` | Upload a trade document — returns `job_id` immediately (async) |
| `GET` | `/api/v1/pipeline/status/{job_id}` | Poll for pipeline result |
| `POST` | `/api/v1/query` | Ask a natural language question over stored pipeline data |

### Submit a document

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/process \
  -H "x-api-key: your_chosen_api_key" \
  -F "file=@/path/to/bill_of_lading.pdf"
```

Response:
```json
{ "job_id": "a3f9c2d1e4b8..." }
```

### Check result

```bash
curl http://localhost:8000/api/v1/pipeline/status/a3f9c2d1e4b8 \
  -H "x-api-key: your_chosen_api_key"
```

Response when complete:
```json
{
  "job_id": "a3f9c2d1e4b8...",
  "status": "complete",
  "extracted_data": {
    "consignee_name": { "value": "AL NASER TRADING COMPANY LLC", "confidence": 0.95 },
    "port_of_discharge": { "value": "Jebel Ali", "confidence": 0.92 },
    "incoterms": { "value": null, "confidence": null },
    "global_confidence_score": 0.85,
    "line_items": null
  },
  "validation_results": [
    { "field_name": "port_of_discharge", "status": "mismatch", "found_value": "Jebel Ali", "expected_value": "Los Angeles" },
    { "field_name": "incoterms", "status": "uncertain", "found_value": null, "expected_value": "CIF" }
  ],
  "final_decision": "draft_amendment",
  "decision_reasoning_or_draft": "Subject: Amendment Request..."
}
```

### Natural language query

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "x-api-key: your_chosen_api_key" \
  -H "Content-Type: application/json" \
  -d '{"question": "How many shipments were flagged for review this week?"}'
```

Response:
```json
{
  "question": "How many shipments were flagged for review this week?",
  "sql": "SELECT COUNT(*) FROM graph_threads WHERE state->>'final_decision' = 'flag_for_review' AND updated_at >= NOW() - INTERVAL '7 days'",
  "answer": "3 shipments were flagged for human review this week.",
  "rows": [{ "count": 3 }],
  "row_count": 1
}
```

---

## Project Structure

```
server/
├── app/
│   ├── main.py                      # FastAPI app, CORS, router registration
│   ├── core/
│   │   ├── config.py                # Pydantic settings (reads .env)
│   │   ├── logger.py                # Rotating file + console logger
│   │   ├── security.py              # x-api-key authentication
│   │   └── state.py                 # LangGraph GraphState TypedDict
│   ├── agents/
│   │   ├── extractor_cascade.py     # Mistral OCR → OpenAI structured extraction
│   │   ├── validator.py             # LLM field validation against customer rules
│   │   ├── router.py                # LLM routing decision + amendment email
│   │   └── query_agent.py           # NL → SQL → NL answer
│   ├── graph/
│   │   └── workflow.py              # LangGraph pipeline: extract → validate → route
│   ├── api/v1/endpoints/
│   │   ├── pipeline.py              # /pipeline/process and /pipeline/status
│   │   └── query.py                 # /query
│   ├── db/
│   │   └── database.py              # asyncpg pool, graph_threads table
│   └── schemas/
│       ├── extraction.py            # ExtractionOutput, FieldValue, LineItem
│       ├── validation.py            # FieldValidation
│       └── routing.py               # RouterDecision
├── logs/
│   └── nova_pipeline.log            # Rotating log file (auto-created)
├── requirements.txt
├── .env                             # Your secrets (not committed)
└── .env.example                     # Template
```

---

## Logs

All agent inputs and outputs are logged to `server/logs/nova_pipeline.log` (DEBUG level) and to the console (INFO level). The log file rotates at 10 MB, keeping 5 backups.
