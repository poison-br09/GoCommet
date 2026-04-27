import { useEffect, useRef, useState } from "react";
import { getStatus, runQuery, submitDocument } from "./api";
import type { QueryResponse } from "./api";
import type {
  Decision,
  ExtractionOutput,
  FieldValidation,
  FieldValue,
  LineItem,
  PipelineResult,
} from "./types";

// ── helpers ───────────────────────────────────────────────────────────────────

function confidenceColor(c: number | null): string {
  if (c === null) return "#9ca3af";
  if (c >= 0.9) return "#16a34a";
  if (c >= 0.6) return "#d97706";
  return "#dc2626";
}

function confidenceLabel(c: number | null): string {
  if (c === null) return "—";
  return `${Math.round(c * 100)}%`;
}

function fmt(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const EXTRACTION_FIELDS: (keyof ExtractionOutput)[] = [
  "consignee_name",
  "hs_code",
  "port_of_loading",
  "port_of_discharge",
  "incoterms",
  "description_of_goods",
  "gross_weight",
  "invoice_number",
];

const LINE_ITEM_COLS: (keyof LineItem)[] = [
  "description", "quantity", "hs_code", "origin",
  "incoterms", "unit_price", "currency", "net_weight", "gross_weight",
];

// ── shared UI pieces ──────────────────────────────────────────────────────────

function Badge({
  label,
  style,
  large,
}: {
  label: string;
  style: React.CSSProperties;
  large?: boolean;
}) {
  return (
    <span className={large ? "badge badge-lg" : "badge"} style={style}>
      {label}
    </span>
  );
}

function ConfidenceBadge({ value }: { value: number | null }) {
  return (
    <Badge
      label={confidenceLabel(value)}
      style={{ background: confidenceColor(value), color: "#fff" }}
    />
  );
}

// ── extraction panel ──────────────────────────────────────────────────────────

function ExtractionPanel({ data }: { data: ExtractionOutput }) {
  return (
    <section className="card">
      <div className="card-header">
        <h2>Extracted Fields</h2>
        <span className="sub">
          Global confidence&nbsp;
          <ConfidenceBadge value={data.global_confidence_score} />
        </span>
      </div>

      <table className="tbl">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {EXTRACTION_FIELDS.map((key) => {
            const fv = data[key] as FieldValue;
            return (
              <tr key={key}>
                <td className="td-name">{fmt(key)}</td>
                <td>{fv.value ?? <span className="nil">—</span>}</td>
                <td>
                  <ConfidenceBadge value={fv.confidence} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {data.line_items && data.line_items.length > 0 && (
        <div className="line-items">
          <h3>Line Items ({data.line_items.length})</h3>
          <div className="scroll-x">
            <table className="tbl">
              <thead>
                <tr>
                  {LINE_ITEM_COLS.map((c) => (
                    <th key={c}>{fmt(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.line_items.map((item, i) => (
                  <tr key={i}>
                    {LINE_ITEM_COLS.map((c) => (
                      <td key={c}>{item[c] ?? "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

// ── validation panel ──────────────────────────────────────────────────────────

const STATUS_STYLE: Record<FieldValidation["status"], React.CSSProperties> = {
  match:     { background: "#16a34a", color: "#fff" },
  mismatch:  { background: "#dc2626", color: "#fff" },
  uncertain: { background: "#d97706", color: "#fff" },
};

function ValidationPanel({ results }: { results: FieldValidation[] }) {
  return (
    <section className="card">
      <h2>Validation Results</h2>
      <table className="tbl">
        <thead>
          <tr>
            <th>Field</th>
            <th>Found</th>
            <th>Expected</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.field_name}>
              <td className="td-name">{fmt(r.field_name)}</td>
              <td>{r.found_value ?? <span className="nil">—</span>}</td>
              <td>{r.expected_value ?? <span className="nil">—</span>}</td>
              <td>
                <Badge
                  label={r.status.replace("_", " ")}
                  style={STATUS_STYLE[r.status]}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ── decision panel ────────────────────────────────────────────────────────────

const DECISION_STYLE: Record<Decision, React.CSSProperties> = {
  auto_approve:    { background: "#16a34a", color: "#fff" },
  flag_for_review: { background: "#d97706", color: "#fff" },
  draft_amendment: { background: "#dc2626", color: "#fff" },
};

const DECISION_LABEL: Record<Decision, string> = {
  auto_approve:    "Auto Approved",
  flag_for_review: "Flagged for Review",
  draft_amendment: "Amendment Required",
};

function DecisionPanel({ decision, text }: { decision: Decision; text: string | null }) {
  return (
    <section className="card">
      <h2>Decision</h2>
      <Badge label={DECISION_LABEL[decision]} style={DECISION_STYLE[decision]} large />

      {text && (
        <div className="reasoning">
          {decision === "draft_amendment" ? (
            <>
              <h3>Draft Amendment Email</h3>
              <pre className="draft-email">{text}</pre>
            </>
          ) : (
            <>
              <h3>Reasoning</h3>
              <p>{text}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}

// ── pipeline tab ──────────────────────────────────────────────────────────────

type PipelineView = "home" | "processing" | "results";

function PipelineTab() {
  const [view, setView] = useState<PipelineView>("home");
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);

  function stopTimers() {
    if (pollRef.current) clearInterval(pollRef.current);
    if (timerRef.current) clearInterval(timerRef.current);
  }

  function goHome() {
    stopTimers();
    setView("home");
    setResult(null);
    setFile(null);
    setUploadError(null);
    setLookupId("");
    setLookupError(null);
    setElapsed(0);
  }

  function startPolling(jobId: string) {
    setElapsed(0);
    timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    pollRef.current = window.setInterval(async () => {
      try {
        const data = await getStatus(jobId);
        if (data.status === "complete") {
          stopTimers();
          setResult(data);
          setView("results");
        }
      } catch (e) {
        stopTimers();
        setUploadError(String(e));
        setView("home");
      }
    }, 2000);
  }

  useEffect(() => () => stopTimers(), []);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploadError(null);
    setView("processing");
    try {
      const { job_id } = await submitDocument(file);
      startPolling(job_id);
    } catch (e) {
      setUploadError(String(e));
      setView("home");
    }
  }

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    const id = lookupId.trim();
    if (!id) return;
    setLookupError(null);
    setLookupLoading(true);
    try {
      const data = await getStatus(id);
      setResult(data);
      setView("results");
    } catch (e) {
      setLookupError(String(e));
    } finally {
      setLookupLoading(false);
    }
  }

  // ── home ──
  if (view === "home") {
    return (
      <div className="home-grid">
        <section className="card home-card">
          <h2>Process New Document</h2>
          <p className="sub">Bill of Lading · Commercial Invoice · Packing List — PDF, PNG, JPG</p>
          <form onSubmit={handleUpload} style={{ marginTop: "1.25rem" }}>
            <label className="file-label">
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.xls,.xlsx"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <span className="file-btn">Choose File</span>
              <span className="file-name">{file ? file.name : "No file chosen"}</span>
            </label>
            <button type="submit" className="btn-primary btn-full" disabled={!file}>
              Process Document
            </button>
          </form>
          {uploadError && <p className="lookup-error">{uploadError}</p>}
        </section>

        <section className="card home-card">
          <h2>Look Up by Job ID</h2>
          <p className="sub">Retrieve results of any previous job instantly.</p>
          <form onSubmit={handleLookup} style={{ marginTop: "1.25rem" }}>
            <input
              className="ask-input"
              style={{ width: "100%", marginBottom: "0.75rem" }}
              type="text"
              placeholder="Paste job ID…"
              value={lookupId}
              onChange={(e) => { setLookupId(e.target.value); setLookupError(null); }}
            />
            <button
              type="submit"
              className="btn-primary btn-full"
              disabled={!lookupId.trim() || lookupLoading}
            >
              {lookupLoading ? "Looking up…" : "Get Result"}
            </button>
          </form>
          {lookupError && <p className="lookup-error">{lookupError}</p>}
        </section>
      </div>
    );
  }

  // ── processing ──
  if (view === "processing") {
    return (
      <div className="status-card">
        <div className="spinner" />
        <p>Running pipeline…</p>
        <p className="sub">{elapsed}s elapsed</p>
        <p className="sub">OCR → Extract → Validate → Route</p>
      </div>
    );
  }

  // ── results ──
  return (
    <>
      <div className="result-bar">
        <button className="btn-link" onClick={goHome}>← Back</button>
        <span className="mono">Job: {result?.job_id}</span>
        <span
          className="badge"
          style={{ background: result?.status === "processing" ? "#d97706" : "#16a34a", color: "#fff" }}
        >
          {result?.status}
        </span>
      </div>

      {result?.status === "processing" && (
        <div className="status-card compact">
          <div className="spinner" />
          <p>This job is still running. Check back shortly.</p>
        </div>
      )}

      {result?.extracted_data && <ExtractionPanel data={result.extracted_data} />}
      {result?.validation_results?.length ? (
        <ValidationPanel results={result.validation_results} />
      ) : null}
      {result?.final_decision && (
        <DecisionPanel
          decision={result.final_decision}
          text={result.decision_reasoning_or_draft}
        />
      )}
    </>
  );
}

// ── query tab ─────────────────────────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  "How many shipments were processed this week?",
  "How many shipments were flagged for review?",
  "Show all jobs where port of discharge mismatched.",
  "What is the average global confidence score?",
  "List the last 5 completed jobs with their decisions.",
];

function QueryTab() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk(q?: string) {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const data = await runQuery(text);
      setAnswer(data.answer);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="query-wrap">
      <section className="card">
        <h2>Ask a Question</h2>
        <p className="sub">Plain English questions about your pipeline data.</p>

        <div className="ask-row">
          <input
            className="ask-input"
            type="text"
            placeholder="e.g. How many shipments were flagged this week?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          />
          <button
            className="btn-primary"
            onClick={() => handleAsk()}
            disabled={!question.trim() || loading}
          >
            {loading ? "…" : "Ask"}
          </button>
        </div>

        <div className="examples">
          <span className="sub">Try: </span>
          {EXAMPLE_QUESTIONS.map((q) => (
            <button key={q} className="chip" onClick={() => handleAsk(q)}>
              {q}
            </button>
          ))}
        </div>

        {loading && (
          <div className="inline-status" style={{ marginTop: "1rem" }}>
            <div className="spinner-sm" />
            <span className="sub">Thinking…</span>
          </div>
        )}

        {error && <p className="lookup-error" style={{ marginTop: "0.75rem" }}>{error}</p>}

        {answer && (
          <div className="answer-box">
            <p className="answer-text">{answer}</p>
          </div>
        )}
      </section>
    </div>
  );
}

// ── app shell ─────────────────────────────────────────────────────────────────

type Tab = "pipeline" | "query";

export default function App() {
  const [tab, setTab] = useState<Tab>("pipeline");

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">Nova Pipeline</span>
        <nav className="tab-nav">
          <button
            className={tab === "pipeline" ? "tab active" : "tab"}
            onClick={() => setTab("pipeline")}
          >
            Process Document
          </button>
          <button
            className={tab === "query" ? "tab active" : "tab"}
            onClick={() => setTab("query")}
          >
            Query Data
          </button>
        </nav>
      </header>

      <main className="main">
        {tab === "pipeline" ? <PipelineTab /> : <QueryTab />}
      </main>
    </div>
  );
}
