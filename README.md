# GoComet Assignment — Nova Trade Document Workflow

An AI-powered trade document validation workflow for Cargo Group (CG) operators. The system accepts a normalized incoming-email event, processes all attached shipment documents, cross-validates them, drafts a reply to the Shipping Unit (SU), and pauses for human approval before any mock send.

![Architecture Diagram](arch_diagram_small.png)

---

## Overview

The Part 2 workflow extends the Part 1 document pipeline into an event-driven CG review desk:

1. **Trigger** — a simulated email source posts a stable `EmailPayload` webhook containing sender, subject, and local attachment paths.
2. **Extract** — Mistral OCR + GPT-4o-mini extract structured fields from every attachment concurrently.
3. **Cross-validate** — pure Python checks fields that must match across documents in the same email, currently `hs_code` and `consignee_name`.
4. **Validate rules** — existing customer rules validation checks required fields such as port of discharge and Incoterms.
5. **Decide & draft** — the Router Agent drafts an approval or amendment email.
6. **Human review** — LangGraph pauses before `send_email_node`; CG edits the draft and clicks approve.
7. **Store & query** — graph state is stored in PostgreSQL and remains queryable through the natural-language query layer.

The frontend is a React CG Workflow screen with live queue updates via Server-Sent Events (SSE). New incoming emails appear without refreshing the page, while the selected review pane is never replaced unless the operator clicks **Load update**.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python 3.12+, FastAPI, Uvicorn |
| AI Agents | LangGraph, OpenAI GPT-4o-mini, Mistral OCR |
| Database | PostgreSQL 14+, asyncpg |
| Ingestion | Stable FastAPI webhook, mock trigger script, optional IMAP adapter |

---

## Project Structure

```text
GoComet_Assignment/
├── client/                 # React CG Workflow + query UI
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       └── types.ts
├── scripts/
│   ├── mock_trigger.py     # Interactive local email-event simulator
│   └── imap_trigger.py     # Optional IMAP source adapter
└── server/
    ├── app/
    │   ├── agents/         # Extractor, validator, router, query agent
    │   ├── api/v1/         # Webhook, status, queue, resume endpoints
    │   ├── core/           # Config, auth, state, logging
    │   ├── db/             # PostgreSQL persistence
    │   └── graph/          # LangGraph workflow
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
```

Create the database if needed:

```bash
psql -U postgres -c "CREATE DATABASE Nova;"
```

Run the API:

```bash
cd server
source gocometvenv/bin/activate
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`; Swagger is at `http://localhost:8000/docs`.

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

## Running The Part 2 Demo

### Option 1 — Mock Email Trigger

Use this for the assignment demo. It simulates one SU email with any number of selected attachments.

```bash
cd /home/poison/Downloads/GoComet_Assignment
API_KEY=1234567890 python3 scripts/mock_trigger.py
```

The script lists supported local files and lets you choose numbers like:

```text
1,3
```

or:

```text
1-3
```

You can also pass files directly:

```bash
API_KEY=1234567890 python3 scripts/mock_trigger.py Bill_of_lading.pdf commercial-invoice.png
```

### Option 2 — API-Only Multipart Upload

This is not exposed in the frontend, but remains useful for testing. Upload multiple documents as one shipment:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/process \
  -H "x-api-key: 1234567890" \
  -F "files=@/path/to/Bill_of_lading.pdf" \
  -F "files=@/path/to/commercial-invoice.png" \
  -F "files=@/path/to/packing-list.pdf"
```

### Option 3 — Optional IMAP Adapter

Add IMAP settings to `server/.env`:

```env
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your_email@example.com
IMAP_PASSWORD=your_app_password
IMAP_FOLDER=INBOX
IMAP_SEARCH_CRITERIA=UNSEEN
```

Then run:

```bash
python3 scripts/imap_trigger.py
```

To mark processed messages as seen:

```bash
python3 scripts/imap_trigger.py --mark-seen
```

The IMAP adapter is intentionally separate from the pipeline. It preprocesses mailbox emails into the same stable webhook contract used by the mock trigger.

---

## CG Workflow UI

The React app has two tabs:

- **CG Workflow** — live queue, verification results, discrepancy detail, editable draft reply, approve & mock-send.
- **Query Data** — natural-language questions over stored pipeline state.

The CG screen covers the required four states:

- **Incoming** — a new SU email appears in the queue while the agent processes attachments.
- **Verification result** — field-by-field view of matches, mismatches, uncertainties, and confidence scores.
- **Discrepancy detail** — clicking a row shows found value, expected value, document name, and source snippet.
- **Draft reply** — editable email to SU. The agent never sends automatically; CG must approve.

Live updates only change the queue. If the operator is reading a selected review, the detail pane is not replaced automatically. A **Load update** banner appears when new results are available for that thread.

---

## API Reference

All non-stream endpoints require `x-api-key: <API_KEY>`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/api/v1/webhook/incoming-email` | Stable email event contract: sender, subject, attachment paths |
| `POST` | `/api/v1/pipeline/process` | API-only multipart upload with `files=@...`, supports multiple docs |
| `GET` | `/api/v1/pipeline/review-queue` | Incoming, failed, and pending CG workflow threads |
| `GET` | `/api/v1/pipeline/review-queue/stream?api_key=...` | SSE queue updates for the frontend |
| `GET` | `/api/v1/pipeline/status/{thread_id}` | Full state for a pipeline thread |
| `POST` | `/api/v1/pipeline/resume/{thread_id}` | Resume paused graph with edited email text |
| `POST` | `/api/v1/query` | Natural-language query over stored state |

Webhook payload:

```json
{
  "sender": "shipping.unit@example.com",
  "subject": "Shipment documents for validation",
  "attachment_paths": [
    "/tmp/bol.pdf",
    "/tmp/invoice.png"
  ]
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

Pipeline state is stored in PostgreSQL table `graph_threads`.

Stored state includes:

- incoming email metadata
- per-document extracted data
- cross-document and customer-rule validation results
- draft email
- human review status
- edited email text
- mock send result
- failure message, if any

LangGraph uses `MemorySaver` for the POC interrupt, with a DB fallback on resume so pending review threads can still complete after server restart.

---

## Useful Commands

Backend checks:

```bash
cd server
source gocometvenv/bin/activate
python -m compileall app
```

Frontend build:

```bash
cd client
npm run build
```

Run mock trigger:

```bash
cd /home/poison/Downloads/GoComet_Assignment
API_KEY=1234567890 python3 scripts/mock_trigger.py
```

---

## Notes

- Real email sending is mocked by `send_email_node`.
- The agent never sends without CG approval.
- IMAP ingestion is an adapter, not part of the core pipeline contract.
- If Mistral/OpenAI network calls fail, the thread is marked `failed` and the error is shown in the CG queue.
