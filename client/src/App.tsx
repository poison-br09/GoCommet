import { useEffect, useRef, useState } from "react";
import { createReviewQueueStream, getPendingReview, getStatus, resumePipeline, runQuery } from "./api";
import type {
  ExtractionOutput,
  FieldValidation,
  FieldValue,
  LineItem,
  PendingReviewItem,
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
        <h2>{data.document_name ? `Extracted Fields · ${data.document_name}` : "Extracted Fields"}</h2>
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

// ── validation styles ─────────────────────────────────────────────────────────

const STATUS_STYLE: Record<FieldValidation["status"], React.CSSProperties> = {
  match:     { background: "#16a34a", color: "#fff" },
  mismatch:  { background: "#dc2626", color: "#fff" },
  uncertain: { background: "#d97706", color: "#fff" },
};

function workflowStatusLabel(status: PipelineResult["status"] | null | undefined): string {
  if (status === "processing") return "Incoming";
  if (status === "pending_review") return "Review";
  if (status === "failed") return "Failed";
  if (status === "sent") return "Sent";
  return "Complete";
}

function workflowStatusStyle(status: PipelineResult["status"] | null | undefined): React.CSSProperties {
  if (status === "processing") return { background: "#2563eb", color: "#fff" };
  if (status === "failed") return { background: "#dc2626", color: "#fff" };
  if (status === "sent") return { background: "#16a34a", color: "#fff" };
  return { background: "#d97706", color: "#fff" };
}

const CG_SELECTED_THREAD_KEY = "nova.cg.selectedThreadId";

// ── CG workflow tab ───────────────────────────────────────────────────────────

function ReviewValidationPanel({
  results,
  selected,
  onSelect,
}: {
  results: FieldValidation[];
  selected: FieldValidation | null;
  onSelect: (item: FieldValidation) => void;
}) {
  return (
    <section className="card">
      <h2>Verification Results</h2>
      <table className="tbl">
        <thead>
          <tr>
            <th>Document</th>
            <th>Check</th>
            <th>Field</th>
            <th>Found</th>
            <th>Expected</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, index) => (
            <tr
              key={`${r.validation_type}-${r.document_name}-${r.field_name}-${index}`}
              className="clickable-row"
              onClick={() => onSelect(r)}
            >
              <td>{r.document_name ?? "—"}</td>
              <td>{r.validation_type === "cross_document" ? "Cross-doc" : "Customer rules"}</td>
              <td className="td-name">{fmt(r.field_name)}</td>
              <td>{r.found_value ?? <span className="nil">—</span>}</td>
              <td>{r.expected_value ?? <span className="nil">—</span>}</td>
              <td>
                <Badge label={r.status} style={STATUS_STYLE[r.status]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && (
        <div className="detail-box">
          <div className="detail-head">
            <strong>{fmt(selected.field_name)}</strong>
            <Badge label={selected.status} style={STATUS_STYLE[selected.status]} />
          </div>
          <p><span className="td-name">Document:</span> {selected.document_name ?? "—"}</p>
          <p><span className="td-name">Found:</span> {selected.found_value ?? "—"}</p>
          <p><span className="td-name">Expected:</span> {selected.expected_value ?? "—"}</p>
          <pre className="snippet">{selected.source_snippet ?? "No source snippet captured."}</pre>
        </div>
      )}
    </section>
  );
}

function CGWorkflowTab() {
  const [queue, setQueue] = useState<PendingReviewItem[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [selectedValidation, setSelectedValidation] = useState<FieldValidation | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [selectedHasUpdate, setSelectedHasUpdate] = useState(false);
  const [draftDirty, setDraftDirty] = useState(false);
  const selectedThreadRef = useRef<string | null>(null);
  const resultStatusRef = useRef<PipelineResult["status"] | null>(null);
  const draftDirtyRef = useRef(false);

  function applyResult(data: PipelineResult, options?: { preserveDirtyDraft?: boolean }) {
    setResult(data);
    resultStatusRef.current = data.status;
    if (!options?.preserveDirtyDraft || !draftDirtyRef.current) {
      setDraft(data.decision_reasoning_or_draft ?? "");
      setDraftDirty(false);
      draftDirtyRef.current = false;
    }
    setSelectedValidation(data.validation_results?.find((r) => r.status !== "match") ?? data.validation_results?.[0] ?? null);
  }

  async function loadQueue(): Promise<PendingReviewItem[]> {
    setError(null);
    try {
      const rows = await getPendingReview();
      setQueue(rows);
      return rows;
    } catch (e) {
      setError(String(e));
      return [];
    }
  }

  async function openThread(threadId: string) {
    setLoading(true);
    setError(null);
    setSentMessage(null);
    try {
      const data = await getStatus(threadId);
      setSelectedThreadId(threadId);
      selectedThreadRef.current = threadId;
      setSelectedHasUpdate(false);
      window.localStorage.setItem(CG_SELECTED_THREAD_KEY, threadId);
      applyResult(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function approveAndSend() {
    if (!selectedThreadId || !draft.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await resumePipeline(selectedThreadId, draft);
      applyResult(data);
      setSentMessage("Mock email sent and thread completed.");
      await loadQueue();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    async function restoreQueue() {
      await loadQueue();
      const savedThreadId = window.localStorage.getItem(CG_SELECTED_THREAD_KEY);
      if (savedThreadId) {
        await openThread(savedThreadId);
      }
    }

    restoreQueue();
  }, []);

  useEffect(() => {
    const stream = createReviewQueueStream();

    stream.addEventListener("queue", async (event) => {
      try {
        const rows = JSON.parse((event as MessageEvent).data) as PendingReviewItem[];
        setQueue(rows);
        const selectedThreadId = selectedThreadRef.current;
        if (!selectedThreadId) return;

        const selectedQueueItem = rows.find((item) => item.thread_id === selectedThreadId);
        if (selectedQueueItem?.status && selectedQueueItem.status !== resultStatusRef.current) {
          setSelectedHasUpdate(true);
        }
      } catch (e) {
        setError(String(e));
      }
    });

    stream.onerror = () => {
      setError("Live queue connection interrupted. Use Refresh if the queue looks stale.");
    };

    return () => stream.close();
  }, []);

  const extractedDocs = Array.isArray(result?.extracted_data)
    ? result.extracted_data
    : result?.extracted_data
      ? [result.extracted_data]
      : [];

  return (
    <div className="cg-grid">
      <section className="card queue-card">
        <div className="card-header">
          <h2>CG Workflow Queue</h2>
          <button className="btn-link" onClick={loadQueue}>Refresh</button>
        </div>
        {queue.length === 0 ? (
          <p className="sub">No incoming or paused email threads are waiting for CG action.</p>
        ) : (
          <div className="queue-list">
            {queue.map((item) => (
              <button
                key={item.thread_id}
                className={item.thread_id === selectedThreadId ? "queue-item active" : "queue-item"}
                onClick={() => openThread(item.thread_id)}
              >
                <span>{item.incoming_email?.subject ?? "Untitled shipment"}</span>
                <Badge
                  label={workflowStatusLabel(item.status)}
                  style={workflowStatusStyle(item.status)}
                />
                <small>{item.incoming_email?.sender ?? "Unknown sender"}</small>
                <small>{item.incoming_email?.attachment_paths.length ?? 0} attachment(s)</small>
                <small>{item.thread_id}</small>
              </button>
            ))}
          </div>
        )}
        {error && <p className="lookup-error">{error}</p>}
      </section>

      <div className="review-pane">
        {selectedHasUpdate && selectedThreadId && (
          <section className="update-banner">
            <span>This thread has new results.</span>
            <button className="btn-link" onClick={() => openThread(selectedThreadId)}>
              Load update
            </button>
          </section>
        )}

        {loading && (
          <div className="inline-status">
            <div className="spinner-sm" />
            <span className="sub">Loading workflow state…</span>
          </div>
        )}

        {!result && !loading && (
          <section className="card">
            <h2>CG Workflow</h2>
            <p className="sub">Select an incoming or paused email thread to track processing, review discrepancies, and approve the draft reply.</p>
          </section>
        )}

        {result && (
          <>
            <section className="card">
              <div className="card-header">
                <h2>{result.incoming_email?.subject ?? "Shipment Review"}</h2>
                <Badge
                  label={workflowStatusLabel(result.status)}
                  style={workflowStatusStyle(result.status)}
                />
              </div>
              <p className="sub">From {result.incoming_email?.sender ?? "—"}</p>
              <p className="sub">{result.incoming_email?.attachment_paths.length ?? 0} attachment(s)</p>
              {result.status === "processing" && (
                <div className="inline-status">
                  <div className="spinner-sm" />
                  <span className="sub">New SU email received. Agent is extracting and validating attached documents.</span>
                </div>
              )}
              {result.status === "failed" && (
                <p className="lookup-error">{result.error_message ?? "The backend worker failed before completing this thread."}</p>
              )}
            </section>

            {extractedDocs.map((doc, index) => (
              <ExtractionPanel key={`${doc.path ?? index}`} data={doc} />
            ))}

            {result.validation_results?.length ? (
              <ReviewValidationPanel
                results={result.validation_results}
                selected={selectedValidation}
                onSelect={setSelectedValidation}
              />
            ) : null}

            {result.status !== "processing" && result.status !== "failed" && (
              <section className="card">
                <h2>Draft Reply</h2>
                <textarea
                  className="draft-editor"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setDraftDirty(true);
                  draftDirtyRef.current = true;
                }}
                disabled={result.status === "sent"}
              />
                <button
                  className="btn-primary"
                  onClick={approveAndSend}
                  disabled={loading || result.status === "sent" || !draft.trim()}
                >
                  {result.status === "sent" ? "Sent" : "Approve & Send"}
                </button>
                {sentMessage && <p className="success-msg">{sentMessage}</p>}
              </section>
            )}
          </>
        )}
      </div>
    </div>
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

type Tab = "cg" | "query";

export default function App() {
  const [tab, setTab] = useState<Tab>("cg");

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">Nova Pipeline</span>
        <nav className="tab-nav">
          <button
            className={tab === "cg" ? "tab active" : "tab"}
            onClick={() => setTab("cg")}
          >
            CG Workflow
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
        {tab === "cg" && <CGWorkflowTab />}
        {tab === "query" && <QueryTab />}
      </main>
    </div>
  );
}
