# GoComet Assignment — Trade Document Processing Pipeline

An AI-powered trade document processing system with a multi-agent backend and a React frontend. Upload shipping/trade documents, extract structured fields via OCR + LLM, validate them against business rules, and query the processed data in natural language.

![Architecture Diagram](arch_diagram_small.png)

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Setup](#setup)
  - [1. Clone the repository](#1-clone-the-repository)
  - [2. Database setup](#2-database-setup)
  - [3. Backend setup](#3-backend-setup)
  - [4. Frontend setup](#4-frontend-setup)
- [Running the App](#running-the-app)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Features](#features)

---

## Overview

The pipeline processes trade documents (invoices, bills of lading, etc.) through a three-stage LangGraph workflow:

1. **Extract** — Mistral OCR converts the document to markdown; GPT-4o-mini extracts 8 structured fields plus line items.
2. **Validate** — GPT-4o-mini checks each field against customer rules and flags anomalies.
3. **Route** — The router decides: auto-approve, flag for human review, or draft an amendment email.

A React + TypeScript frontend lets you upload documents, poll for results, and query stored data with natural language.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python 3.12+, FastAPI, Uvicorn |
| AI Agents | LangGraph, OpenAI (GPT-4o-mini), Mistral (OCR) |
| Database | PostgreSQL 14+, asyncpg |

---

## Prerequisites

Make sure the following are installed before proceeding:

- **Node.js** v18+ and **npm** v9+
- **Python** 3.12+
- **PostgreSQL** 14+ running locally
- An **OpenAI API key** (GPT-4o-mini access)
- A **Mistral API key**

---

## Project Structure

```
GoComet_Assignment/
├── client/               # React + TypeScript frontend (Vite, port 3000)
│   ├── src/
│   │   ├── App.tsx       # Main UI — two-tab interface
│   │   ├── api.ts        # HTTP client for backend
│   │   └── types.ts      # TypeScript interfaces
│   ├── .env.example
│   └── package.json
└── server/               # FastAPI backend (port 8000)
    ├── app/
    │   ├── main.py       # App init, CORS, route registration
    │   ├── agents/       # Extract, Validate, Route, Query agents
    │   ├── graph/        # LangGraph workflow orchestration
    │   ├── api/v1/       # REST endpoints
    │   ├── db/           # asyncpg pool & DB helpers
    │   └── core/         # Config, logging, auth
    ├── .env.example
    └── requirements.txt
```

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd GoComet_Assignment
```

### 2. Database setup

Start PostgreSQL and create the database:

```bash
psql -U postgres -c "CREATE DATABASE Nova;"
```

> The `graph_threads` table is created automatically when the server starts. No manual migrations needed.

### 3. Backend setup

```bash
cd server

# Create and activate a virtual environment
python3 -m venv gocometvenv
source gocometvenv/bin/activate        # macOS/Linux
# gocometvenv\Scripts\activate.bat    # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and fill in all values (see Environment Variables section below)
```

### 4. Frontend setup

```bash
cd client

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env
# Edit .env and fill in all values (see Environment Variables section below)
```

---

## Running the App

Open two terminals and run each service:

**Terminal 1 — Backend**

```bash
cd server
source gocometvenv/bin/activate
uvicorn app.main:app --reload
# Server runs at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

**Terminal 2 — Frontend**

```bash
cd client
npm run dev
# App runs at http://localhost:3000
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Production build (frontend)

```bash
cd client
npm run build      # outputs to client/dist/
npm run preview    # serves the build locally for verification
```

---

## Environment Variables

### Server — `server/.env`

Copy `server/.env.example` to `server/.env` and fill in:

```env
OPENAI_API_KEY=sk-...          # OpenAI key with GPT-4o-mini access
MISTRAL_API_KEY=...            # Mistral key for OCR
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/Nova
API_KEY=your_secret_api_key    # Any string — used to authenticate all requests
```

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Used by Extractor, Validator, Router, and Query agents |
| `MISTRAL_API_KEY` | Used for document OCR via Mistral |
| `DATABASE_URL` | asyncpg-compatible PostgreSQL connection string |
| `API_KEY` | Shared secret sent as the `x-api-key` header |

### Client — `client/.env`

Copy `client/.env.example` to `client/.env` and fill in:

```env
VITE_API_KEY=your_secret_api_key   # Must match server's API_KEY
VITE_API_BASE_URL=http://localhost:8000
```

| Variable | Description |
|---|---|
| `VITE_API_KEY` | Must be the same value as the server's `API_KEY` |
| `VITE_API_BASE_URL` | Base URL of the FastAPI server |

---

## API Reference

All endpoints require an `x-api-key` header set to the value of `API_KEY`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/pipeline/process` | Upload a document (multipart/form-data). Returns `{ job_id }` immediately. |
| `GET` | `/api/v1/pipeline/status/{job_id}` | Poll for processing results. Returns full pipeline output when complete. |
| `POST` | `/api/v1/query` | Run a natural language query over processed data. |

Full interactive documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs) once the server is running.

### Example: process a document

```bash
# Upload
curl -X POST http://localhost:8000/api/v1/pipeline/process \
  -H "x-api-key: your_secret_api_key" \
  -F "file=@invoice.pdf"
# → { "job_id": "abc123" }

# Poll for result
curl http://localhost:8000/api/v1/pipeline/status/abc123 \
  -H "x-api-key: your_secret_api_key"
```

### Example: natural language query

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "x-api-key: your_secret_api_key" \
  -H "Content-Type: application/json" \
  -d '{"question": "Which documents had a gross weight above 500 kg?"}'
```

---

## Features

### Document processing pipeline

- Accepts PDF and image documents via file upload
- Extracts 8 structured fields: `consignee_name`, `hs_code`, `port_of_loading`, `port_of_discharge`, `incoterms`, `description_of_goods`, `gross_weight`, `invoice_number`
- Extracts line items: description, quantity, HS code, origin, incoterms, unit price, currency, net/gross weight
- Each field includes a confidence score
- Routing decisions: **Auto-approve**, **Flag for review**, or **Draft amendment email**

### Natural language querying

- Ask questions in plain English about processed documents
- The query agent converts them to SQL and returns a human-readable answer

### Frontend UI

- **Process Document tab** — upload a file or look up a previous job by ID; view extracted fields, line items, validation results, and routing outcome
- **Query Data tab** — type a question and get a plain-English answer

### Observability

- Rotating log file at `server/logs/nova_pipeline.log` (10 MB per file, 5 backups)
- DEBUG-level logging to file; INFO to console
- All agent inputs/outputs are logged for inspection
