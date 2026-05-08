# Nova Pipeline — Server

FastAPI + LangGraph backend for the Nova trade document workflow. The server ingests normalized email events, processes multiple attached documents, pauses for CG review, sends approved replies through SMTP, and stores both pipeline state and email audit records in PostgreSQL.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| PostgreSQL | 14+ |
| OpenAI API key | Required |
| Mistral API key | Required |
| Gmail app password or SMTP credentials | Required for real email send |

---

## Setup

```bash
cd server
python3 -m venv gocometvenv
source gocometvenv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create the database if needed:

```sql
CREATE DATABASE Nova;
```

Fill `.env`:

```env
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
DATABASE_URL=postgresql+asyncpg://postgres:your_password@localhost:5432/Nova
API_KEY=your_chosen_api_key

IMAP_ENABLED=true
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your_email@gmail.com
IMAP_PASSWORD=your_app_password
IMAP_FOLDER=INBOX
IMAP_SEARCH_CRITERIA=UNSEEN
IMAP_MARK_SEEN=true
IMAP_POLL_INTERVAL_SECONDS=60

SMTP_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
```

SMTP reuses IMAP credentials unless `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` are provided.

---

## Run

```bash
cd server
source gocometvenv/bin/activate
python3 -m uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

Changing `.env` requires a manual server restart.

---

## Workflow

1. Ingestion creates an `EmailPayload` with `sender`, `subject`, and `attachment_paths`.
2. Extractor runs OCR/extraction concurrently for every attachment.
3. Cross-document validator checks `hs_code` and `consignee_name` across the shipment document set.
4. Customer rule validator checks port of discharge and Incoterms.
5. Router drafts an approval or amendment email.
6. LangGraph pauses before send.
7. CG approves edited draft through `/pipeline/resume/{thread_id}`.
8. Server sends via SMTP and stores audit metadata.

---

## API Endpoints

All non-stream endpoints require `x-api-key: <API_KEY>`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/api/v1/webhook/incoming-email` | Start a thread from normalized email payload |
| `POST` | `/api/v1/pipeline/process` | API-only multipart upload; wraps files into one email event |
| `GET` | `/api/v1/pipeline/review-queue` | Processing, pending, failed, and sent workflow threads |
| `GET` | `/api/v1/pipeline/review-queue/stream?api_key=...` | SSE queue stream for frontend |
| `GET` | `/api/v1/pipeline/status/{thread_id}` | Full thread state |
| `POST` | `/api/v1/pipeline/review-action/{thread_id}` | Accept found value or mark a discrepancy resolved |
| `POST` | `/api/v1/pipeline/resume/{thread_id}` | Approve draft and send email; idempotent after sent |
| `POST` | `/api/v1/query` | NL query over graph state and email audit data |

Example webhook:

```bash
curl -X POST http://localhost:8000/api/v1/webhook/incoming-email \
  -H "x-api-key: your_chosen_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "shipping.unit@example.com",
    "subject": "Shipment docs",
    "attachment_paths": ["/tmp/bol.pdf", "/tmp/invoice.pdf", "/tmp/packing-list.pdf"]
  }'
```

Example approve/send:

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/resume/<thread_id> \
  -H "x-api-key: your_chosen_api_key" \
  -H "Content-Type: application/json" \
  -d '{"edited_email_text": "Subject: Amendment Request\n\nDear Shipping Unit,\n..."}'
```

---

## Persistence

Tables are created automatically in `init_db()`:

- `graph_threads`
  - `thread_id`
  - `state` JSONB
  - `updated_at`
- `email_audit`
  - inbound sender/subject
  - attachment names/paths
  - validation results at send time
  - outgoing recipient/subject/body
  - delivery mode/status
  - SMTP Message-ID and `sent_at`

Useful audit query:

```sql
SELECT thread_id, incoming_subject, attachment_file_names, outgoing_subject, delivery, send_status, sent_at
FROM email_audit
ORDER BY sent_at DESC;
```

---

## Project Structure

```text
server/
├── app/
│   ├── main.py                  # FastAPI app and startup/shutdown hooks
│   ├── agents/                  # Extractor, validator, router, query agent
│   ├── api/v1/endpoints/        # Pipeline and query routes
│   ├── core/                    # Settings, state, security, logging
│   ├── db/database.py           # asyncpg pool, graph_threads, email_audit
│   ├── graph/workflow.py        # LangGraph workflow and human-review resume
│   ├── ingestion/               # IMAP worker and SMTP outbound helper
│   └── schemas/                 # Pydantic request/response models
├── logs/
├── requirements.txt
├── .env
└── .env.example
```

---

## Checks

```bash
cd server
source gocometvenv/bin/activate
python3 -m compileall app
```

Logs are written to `server/logs/nova_pipeline.log` and to the console.
