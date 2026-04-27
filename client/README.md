# Nova Pipeline — Client

React + TypeScript frontend for the Nova Pipeline trade document processing system.

Two tabs:
- **Process Document** — upload a trade document or look up a previous job by ID
- **Query Data** — ask plain English questions about stored pipeline results

---

## Prerequisites

| Requirement | Version |
|---|---|
| Node.js | 18+ |
| npm | 9+ |
| Nova Pipeline server | Running on http://localhost:8000 |

---

## Setup

### 1. Install dependencies

```bash
cd client
npm install
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
VITE_API_KEY=your_chosen_api_key
VITE_API_BASE_URL=http://localhost:8000
```

| Variable | Description |
|---|---|
| `VITE_API_KEY` | Must match the `API_KEY` set in the server's `.env` |
| `VITE_API_BASE_URL` | Base URL of the running server |

---

## Run

```bash
npm run dev
```

App starts at **http://localhost:3000**

> The server must be running at `http://localhost:8000` before using the app.

---

## Build for production

```bash
npm run build       # outputs to dist/
npm run preview     # serve the production build locally
```

---

## Usage

### Process Document tab

**Process New Document**
1. Click **Choose File** and select a trade document (PDF, PNG, JPG)
2. Click **Process Document**
3. A spinner shows while the pipeline runs (OCR → Extract → Validate → Route)
4. Results appear automatically when complete

**Look Up by Job ID**
1. Paste a `job_id` from a previous run into the input
2. Click **Get Result**
3. Results load instantly if the job is complete

Both actions show the same results screen:
- **Extracted Fields** — all 8 fields with value and per-field confidence badge (green ≥90%, amber 60–89%, red <60%)
- **Line Items** — product table if the document has multiple line items
- **Validation Results** — per-field match / mismatch / uncertain against customer rules
- **Decision** — auto approve / flag for review / amendment required, with reasoning or draft email

Click **← Back** to return to the home screen.

### Query Data tab

Type any plain English question about your pipeline data and press **Enter** or click **Ask**.

**Example questions:**
- How many shipments were processed this week?
- How many shipments were flagged for review?
- Show all jobs where port of discharge mismatched.
- What is the average global confidence score?
- List the last 5 completed jobs with their decisions.

---

## Project Structure

```
client/
├── src/
│   ├── main.tsx        # React entry point
│   ├── App.tsx         # All components and page logic
│   ├── App.css         # Styles
│   ├── api.ts          # API client (submitDocument, getStatus, runQuery)
│   ├── types.ts        # TypeScript types matching server response schemas
│   └── vite-env.d.ts   # Vite env variable type declarations
├── index.html
├── vite.config.ts      # Vite config (port 3000)
├── tsconfig.json
├── .env                # Your config (not committed)
└── .env.example        # Template
```
