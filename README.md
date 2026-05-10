# Nova - Trade Document Workflow

AI-assisted trade document validation for Cargo Group (CG) operators. Nova ingests Shipping Unit (SU) emails, processes all attached shipment documents, cross-validates them, drafts a reply, and waits for a human CG approval before any email is sent.

![Architecture Diagram](arch_diagram_small.png)

---

## Overview

Nova extends the Part 1 document pipeline into an event-driven review desk:

1. **Trigger** — IMAP, mock script, or API upload normalizes one email into `sender`, `subject`, and `attachment_paths`.
2. **Extract** — Mistral OCR + OpenAI extract structured fields from every attachment concurrently.
3. **Cross-validate** — Python checks shipment-critical fields across documents, currently `hs_code` and `consignee_name`.
4. **Validate rules** — customer rules check fields such as port of discharge and Incoterms.
5. **Decide & draft** — router generates an approval or amendment email draft.
6. **Human review** — CG reviews validation results, discrepancy details, and the editable draft.
7. **Send & audit** — SMTP sends only after **Approve & Send**; graph state and email audit metadata are stored in PostgreSQL.

The React UI receives live queue updates through Server-Sent Events. Incoming and completed threads appear without a page refresh, while the currently opened review is not replaced unless the operator chooses to load it.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | FastAPI, Uvicorn, LangGraph |
| AI/OCR | OpenAI GPT-4o-mini, Mistral OCR |
| Database | PostgreSQL, asyncpg |
| Email | IMAP ingestion, SMTP outbound sending |

---

## Project Structure

```text
GoComet_Assignment/
├── client/                 # React CG Workflow + query UI
├── scripts/
│   ├── mock_trigger.py     # Local normalized email-event simulator
│   └── imap_trigger.py     # Optional one-off IMAP trigger
└── server/
    ├── app/
    │   ├── agents/         # Extractor, validator, router, query agent
    │   ├── api/v1/         # Webhook, queue, status, resume, query endpoints
    │   ├── db/             # PostgreSQL persistence and email audit table
    │   ├── graph/          # LangGraph workflow
    │   └── ingestion/      # IMAP worker and outbound SMTP helper
    └── requirements.txt
```

---

## Setup

### Backend

```bash
cd server
python3 -m venv gocometvenv
source gocometvenv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `server/.env`:

```env
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/Nova
API_KEY=1234567890

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

If `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` are omitted, SMTP reuses the IMAP credentials.

Create the database if needed:

```bash
psql -U postgres -c "CREATE DATABASE Nova;"
```

Run the server:

```bash
cd server
source gocometvenv/bin/activate
python3 -m uvicorn app.main:app --reload
```

The server starts at `http://localhost:8000`. Swagger is available at `http://localhost:8000/docs`.

### Frontend

```bash
cd client
npm install
cp .env.example .env
```

Fill `client/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_API_KEY=1234567890
```

Run the UI:

```bash
cd client
npm run dev
```

Open `http://localhost:3000`.

---

## Running The Demo

### Option 1 — IMAP Inbox

With `IMAP_ENABLED=true`, the FastAPI server starts a background IMAP worker automatically. It polls the configured inbox for `UNSEEN` emails, downloads supported attachments, creates one normalized email event per message, and starts the pipeline.

This is the recommended final demo path when showing real email-triggered workflow.

### Option 2 — Mock Email Trigger

Use this when you want deterministic local testing without waiting for inbox polling:

```bash
cd /home/poison/Downloads/GoComet_Assignment
API_KEY=1234567890 python3 scripts/mock_trigger.py
```

The script lets you select any number of supported local files. It posts one email event containing all selected files.

You can also pass files directly:

```bash
API_KEY=1234567890 python3 scripts/mock_trigger.py Bill_of_lading.pdf commercial-invoice.png packing-list.pdf
```

### Option 3 — API-Only Multipart Upload

The frontend no longer exposes manual upload, but the API remains useful for testing:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/process \
  -H "x-api-key: 1234567890" \
  -F "files=@/path/to/Bill_of_lading.pdf" \
  -F "files=@/path/to/commercial-invoice.png" \
  -F "files=@/path/to/packing-list.pdf"
```

---

## CG Workflow UI

The UI has two tabs:

- **CG Workflow** — live queue, incoming processing state, verification table, discrepancy drawer, editable email draft, and approval/send action.
- **Query Data** — natural-language questions over stored graph state and sent-email audit data.

The CG workflow supports:

- **Incoming** — a new SU email appears while extraction/validation runs.
- **Verification result** — field-by-field status with confidence scores.
- **Discrepancy detail** — click a flagged validation row to inspect found value, expected value, and source snippet.
- **Draft reply** — right-side email panel; click **Email** to reopen it after viewing a discrepancy.
- **Approve & Send** — sends through SMTP only after CG approval, disables after sent, and records delivery metadata.
- **Accept found value / Mark as resolved** — lets CG resolve a flagged validation row and regenerates the draft from remaining issues.

Live queue updates do not overwrite the currently opened review. A **Load update** banner appears when the selected thread has newer results.

---

## API Reference

All non-stream endpoints require `x-api-key: <API_KEY>`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/api/v1/webhook/incoming-email` | Stable email event contract: sender, subject, attachment paths |
| `POST` | `/api/v1/pipeline/process` | API-only multipart upload, supports multiple docs |
| `GET` | `/api/v1/pipeline/review-queue` | Processing, pending, failed, and sent CG workflow threads |
| `GET` | `/api/v1/pipeline/review-queue/stream?api_key=...` | SSE queue updates for the frontend |
| `GET` | `/api/v1/pipeline/status/{thread_id}` | Full state for one pipeline thread |
| `POST` | `/api/v1/pipeline/review-action/{thread_id}` | Accept found value or mark one discrepancy as resolved |
| `POST` | `/api/v1/pipeline/resume/{thread_id}` | Approve draft and send email; idempotent after sent |
| `POST` | `/api/v1/query` | Natural-language query over stored state and email audit data |

Webhook payload:

```json
{
  "sender": "shipping.unit@example.com",
  "subject": "Shipment documents for validation",
  "attachment_paths": ["/tmp/bol.pdf", "/tmp/invoice.png"]
}
```

Resume payload:

```json
{
  "edited_email_text": "Subject: Amendment Request..."
}
```

---

## Persistence

PostgreSQL tables are created automatically at startup:

- `graph_threads` stores the full LangGraph thread state as JSONB.
- `email_audit` stores durable email audit data after approval/send:
  - inbound sender and subject
  - attachment file names and paths
  - validation results at send time
  - outgoing recipient, subject, and body
  - delivery mode, status, SMTP Message-ID, and sent timestamp

The query agent knows about both tables, so CG can ask questions such as:

- “Show sent emails with their subjects and attachment file names.”
- “Show everything pending review for customer Brightwave.”
- “Which shipments had HS code mismatches?”

LangGraph uses `MemorySaver` for the POC interrupt, with PostgreSQL state as the durable fallback for restart/resume behavior.

---

## Useful Commands

Backend checks:

```bash
cd server
source gocometvenv/bin/activate
python3 -m compileall app
```

Frontend build:

```bash
cd client
npm run build
```

Mock trigger:

```bash
cd /home/poison/Downloads/GoComet_Assignment
API_KEY=1234567890 python3 scripts/mock_trigger.py
```

Email audit check:

```sql
SELECT thread_id, incoming_subject, attachment_file_names, outgoing_subject, delivery, send_status, message_id, sent_at
FROM email_audit
ORDER BY sent_at DESC;
```

---

## Notes

- The agent never sends automatically. CG must approve with **Approve & Send**.
- Resume/send is idempotent after a thread is marked `sent`.
- IMAP and mock trigger are adapters; the stable pipeline entry contract remains the normalized email payload.
- If OCR/LLM calls fail, the thread is marked `failed` and appears in the CG queue.
