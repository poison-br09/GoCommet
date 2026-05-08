import React, { useEffect, useRef, useState, useMemo } from "react";
import {
  createReviewQueueStream,
  applyReviewAction,
  getPendingReview,
  getStatus,
  resumePipeline,
  runQuery,
} from "./api";
import type { FieldValidation, PendingReviewItem, PipelineResult } from "./types";

// ─── helpers ──────────────────────────────────────────────────────────────────

function formatRelTime(iso: string): string {
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

const FIELD_LABELS: Record<string, string> = {
  consignee_name: "Consignee",
  invoice_number: "Invoice #",
  hs_code: "HS code",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  incoterms: "Incoterms",
  description_of_goods: "Goods",
  gross_weight: "Gross weight",
};
const FIELD_KEYS = Object.keys(FIELD_LABELS);

// ─── StatusDot ────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    match: "var(--ok)", mismatch: "var(--err)", uncertain: "var(--warn)",
    processing: "var(--info)", pending_review: "var(--warn)",
    sent: "var(--ok)", complete: "var(--ok)", failed: "var(--err)",
  };
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: 999,
      background: map[status] || "var(--text-muted)", flexShrink: 0,
    }} />
  );
}

// ─── StatusBadge ──────────────────────────────────────────────────────────────

function StatusBadge({ status, size = "md" }: { status: string; size?: "sm" | "md" }) {
  const meta: Record<string, { label: string; bg: string; border: string; color: string }> = {
    match:          { label: "Match",        bg: "var(--ok-bg)",   border: "var(--ok-border)",   color: "var(--ok)"   },
    mismatch:       { label: "Mismatch",     bg: "var(--err-bg)",  border: "var(--err-border)",  color: "var(--err)"  },
    uncertain:      { label: "Uncertain",    bg: "var(--warn-bg)", border: "var(--warn-border)", color: "var(--warn)" },
    processing:     { label: "Processing",   bg: "var(--info-bg)", border: "var(--info-border)", color: "var(--info)" },
    pending_review: { label: "Needs review", bg: "var(--warn-bg)", border: "var(--warn-border)", color: "var(--warn)" },
    sent:           { label: "Sent",         bg: "var(--ok-bg)",   border: "var(--ok-border)",   color: "var(--ok)"   },
    complete:       { label: "Complete",     bg: "var(--ok-bg)",   border: "var(--ok-border)",   color: "var(--ok)"   },
    failed:         { label: "Failed",       bg: "var(--err-bg)",  border: "var(--err-border)",  color: "var(--err)"  },
    incoming:       { label: "Incoming",     bg: "var(--info-bg)", border: "var(--info-border)", color: "var(--info)" },
  };
  const m = meta[status] || meta.processing;
  const padY = size === "sm" ? 1 : 2;
  const padX = size === "sm" ? 6 : 8;
  const fs = size === "sm" ? 11 : 11.5;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: `${padY}px ${padX}px`, borderRadius: 4,
      background: m.bg, border: `1px solid ${m.border}`, color: m.color,
      fontSize: fs, fontWeight: 500, letterSpacing: 0.1, lineHeight: 1.4, whiteSpace: "nowrap",
    }}>
      <StatusDot status={status} />
      {m.label}
    </span>
  );
}

// ─── Icon ─────────────────────────────────────────────────────────────────────

function Icon({ name, size = 16, color = "currentColor", strokeWidth = 1.6 }: {
  name: string; size?: number; color?: string; strokeWidth?: number;
}) {
  const p = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: color, strokeWidth, strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const, style: { flexShrink: 0, display: "block" as const },
  };
  switch (name) {
    case "mail":         return <svg {...p}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>;
    case "paperclip":   return <svg {...p}><path d="M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 6"/></svg>;
    case "check":       return <svg {...p}><path d="M5 12.5l4 4 10-10"/></svg>;
    case "x":           return <svg {...p}><path d="M6 6l12 12M6 18L18 6"/></svg>;
    case "alert":       return <svg {...p}><path d="M12 9v4M12 17h.01M10.3 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>;
    case "clock":       return <svg {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
    case "search":      return <svg {...p}><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>;
    case "send":        return <svg {...p}><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>;
    case "refresh":     return <svg {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>;
    case "doc":         return <svg {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>;
    case "chevron-right": return <svg {...p}><path d="M9 6l6 6-6 6"/></svg>;
    case "filter":      return <svg {...p}><path d="M3 5h18l-7 9v6l-4-2v-4L3 5z"/></svg>;
    case "lock":        return <svg {...p}><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>;
    case "sparkles":    return <svg {...p}><path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 16l-1.8-4.8L6 9.4l4.2-1.8z"/><path d="M19 14l.7 1.7L21 16.5l-1.3.8L19 19l-.7-1.7L17 16.5l1.3-.8z"/></svg>;
    case "logo":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ display: "block", flexShrink: 0 }}>
          <circle cx="12" cy="12" r="10" stroke="var(--accent)" strokeWidth="1.6"/>
          <path d="M7 14a6 6 0 0 1 10-4" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round"/>
          <circle cx="12" cy="12" r="2" fill="var(--accent)"/>
        </svg>
      );
    default: return null;
  }
}

// ─── Confidence pill ──────────────────────────────────────────────────────────

function Confidence({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const tone =
    pct >= 90 ? { c: "var(--ok)",   bg: "var(--ok-bg)",   b: "var(--ok-border)"   } :
    pct >= 75 ? { c: "var(--info)", bg: "var(--info-bg)", b: "var(--info-border)" } :
                { c: "var(--warn)", bg: "var(--warn-bg)", b: "var(--warn-border)" };
  return (
    <span className="mono" title={`Confidence: ${pct}%`} style={{
      display: "inline-flex", alignItems: "center", padding: "1px 5px",
      fontSize: 10.5, borderRadius: 3, background: tone.bg,
      color: tone.c, border: `1px solid ${tone.b}`, lineHeight: 1.4, fontWeight: 500,
    }}>
      {pct}%
    </span>
  );
}

// ─── Btn ──────────────────────────────────────────────────────────────────────

function Btn({ variant = "secondary", size = "md", icon, children, disabled, onClick, style }: {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "subtle";
  size?: "sm" | "md";
  icon?: string;
  children?: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
}) {
  const base: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: 6,
    fontWeight: 500, border: "1px solid transparent", borderRadius: 6,
    padding: size === "sm" ? "4px 10px" : "6px 12px",
    fontSize: size === "sm" ? 12.5 : 13,
    transition: "background 80ms, border-color 80ms, color 80ms, box-shadow 80ms, transform 80ms",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.55 : 1,
    whiteSpace: "nowrap", lineHeight: 1.3,
    userSelect: "none",
  };
  const v: React.CSSProperties =
    variant === "primary"   ? { background: "var(--accent)", color: "#fff", borderColor: "var(--accent)", boxShadow: "0 1px 0 rgba(0,0,0,0.04),inset 0 1px 0 rgba(255,255,255,0.08)" } :
    variant === "secondary" ? { background: "var(--surface)", color: "var(--text)", borderColor: "var(--border-strong)" } :
    variant === "ghost"     ? { background: "transparent", color: "var(--text-secondary)", borderColor: "transparent" } :
    variant === "danger"    ? { background: "var(--surface)", color: "var(--err)", borderColor: "var(--err-border)" } :
    /* subtle */              { background: "var(--surface-sunken)", color: "var(--text)", borderColor: "var(--border)" };

  const hoverBg: Record<string, string> = {
    primary: "var(--accent-hover)", secondary: "var(--hover)",
    ghost: "var(--hover)", subtle: "var(--hover)", danger: "var(--hover)",
  };
  const leaveBg: Record<string, string> = {
    primary: "var(--accent)", secondary: "var(--surface)",
    ghost: "transparent", subtle: "var(--surface-sunken)", danger: "var(--surface)",
  };

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{ ...base, ...v, ...style }}
      onMouseEnter={(e) => { if (!disabled) e.currentTarget.style.background = hoverBg[variant]; }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = leaveBg[variant];
        e.currentTarget.style.transform = "translateY(0)";
      }}
      onMouseDown={(e) => {
        if (disabled) return;
        e.currentTarget.style.transform = "translateY(1px) scale(0.98)";
        e.currentTarget.style.boxShadow = "inset 0 1px 2px rgba(15, 23, 42, 0.16)";
      }}
      onMouseUp={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = String((v.boxShadow ?? ""));
      }}
    >
      {icon && <Icon name={icon} size={14} />}
      {children}
    </button>
  );
}

// ─── Progress bar ─────────────────────────────────────────────────────────────

function Progress({ pct }: { pct: number }) {
  return (
    <div style={{ height: 4, background: "var(--surface-sunken)", borderRadius: 2, overflow: "hidden", position: "relative" }}>
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`,
        background: "linear-gradient(90deg, var(--accent), #818cf8)",
        borderRadius: 2, transition: "width 600ms ease",
      }} />
    </div>
  );
}

// ─── TopNav ───────────────────────────────────────────────────────────────────

function TopNav({ tab, setTab }: { tab: string; setTab: (t: string) => void }) {
  return (
    <div style={{
      height: 52, borderBottom: "1px solid var(--border)", background: "var(--surface)",
      display: "flex", alignItems: "stretch", paddingLeft: 16, paddingRight: 16, flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, paddingRight: 24, borderRight: "1px solid var(--border)" }}>
        <Icon name="logo" size={20} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontWeight: 600, letterSpacing: -0.1 }}>Nova Pipeline</span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "stretch", marginLeft: 8 }}>
        {([{ id: "workflow", label: "CG Workflow" }, { id: "query", label: "Query Data" }] as const).map((t) => {
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              border: "none", background: "transparent", padding: "0 14px", fontSize: 13,
              fontWeight: active ? 600 : 500,
              color: active ? "var(--text)" : "var(--text-secondary)",
              borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
              marginBottom: -1, cursor: "pointer",
            }}>
              {t.label}
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--text-tertiary)" }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--ok)", display: "inline-block" }} />
          Agent online
        </div>
      </div>
    </div>
  );
}

// ─── QueueItem ────────────────────────────────────────────────────────────────

function QueueItem({ item, selected, onClick, isNew }: {
  item: PendingReviewItem; selected: boolean; onClick: () => void; isNew: boolean;
}) {
  const att = item.incoming_email?.attachment_paths.length || 0;
  const flagged = item.validation_results?.filter((v) => v.status !== "match").length || 0;
  const relTime = item.received_at || item.updated_at;
  return (
    <button onClick={onClick} style={{
      display: "block", textAlign: "left", width: "100%",
      background: selected ? "var(--selected)" : "transparent",
      border: "1px solid", borderColor: selected ? "var(--selected-border)" : "transparent",
      borderRadius: 6, padding: "10px 12px", cursor: "pointer", position: "relative",
    }}
      onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = "var(--hover)"; }}
      onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = "transparent"; }}
    >
      {isNew && (
        <span style={{ position: "absolute", left: 4, top: 14, width: 4, height: 4, borderRadius: 999, background: "var(--accent)" }} />
      )}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>
          {item.incoming_email?.sender_name || item.incoming_email?.sender || "Unknown"}
        </span>
        {relTime && <span className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>{formatRelTime(relTime)}</span>}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 7 }}>
        {item.incoming_email?.subject || "Untitled"}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <StatusBadge status={item.status || "processing"} size="sm" />
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "var(--text-tertiary)" }}>
          {flagged > 0 && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "var(--err)" }}>
              <Icon name="alert" size={11} /> {flagged}
            </span>
          )}
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <Icon name="paperclip" size={11} /> {att}
          </span>
        </div>
      </div>
    </button>
  );
}

// ─── QueueSidebar ─────────────────────────────────────────────────────────────

function QueueSidebar({ items, selectedId, onSelect, onSync, newThreadIds }: {
  items: PendingReviewItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onSync: () => void;
  newThreadIds: string[];
}) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length, processing: 0, pending_review: 0, sent: 0, failed: 0 };
    for (const t of items) if (t.status) c[t.status] = (c[t.status] || 0) + 1;
    return c;
  }, [items]);

  const filtered = items.filter((t) => {
    if (filter !== "all" && t.status !== filter) return false;
    if (search) {
      const s = search.toLowerCase();
      return (
        (t.incoming_email?.subject || "").toLowerCase().includes(s) ||
        (t.incoming_email?.sender_name || t.incoming_email?.sender || "").toLowerCase().includes(s) ||
        t.thread_id.toLowerCase().includes(s)
      );
    }
    return true;
  });

  const filterTabs = [
    { id: "all", label: "All" },
    { id: "processing", label: "Incoming" },
    { id: "pending_review", label: "Review" },
    { id: "sent", label: "Sent" },
  ];

  return (
    <aside style={{
      width: 340, flexShrink: 0, background: "var(--surface-2)",
      borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", height: "100%",
    }}>
      {/* Header */}
      <div style={{ padding: "14px 14px 10px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Workflow Queue</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)", background: "var(--surface-sunken)", padding: "1px 6px", borderRadius: 3 }}>
              {counts.all}
            </span>
          </div>
          <Btn variant="ghost" size="sm" icon="refresh" onClick={onSync}>Sync</Btn>
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 8px",
        }}>
          <Icon name="search" size={13} color="var(--text-muted)" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sender, subject, ID…"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "var(--text)" }}
          />
        </div>
      </div>
      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 2, padding: "8px 10px", borderBottom: "1px solid var(--border-subtle)", overflowX: "auto" }}>
        {filterTabs.map((f) => {
          const active = filter === f.id;
          return (
            <button key={f.id} onClick={() => setFilter(f.id)} style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              fontSize: 11.5, fontWeight: 500, padding: "3px 9px", borderRadius: 4, border: "1px solid",
              borderColor: active ? "var(--border-strong)" : "transparent",
              background: active ? "var(--surface)" : "transparent",
              color: active ? "var(--text)" : "var(--text-secondary)", cursor: "pointer",
            }}>
              {f.label}
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                {counts[f.id] || 0}
              </span>
            </button>
          );
        })}
      </div>
      {/* List */}
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px 16px" }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
            No threads match.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {filtered.map((item) => (
              <QueueItem
                key={item.thread_id}
                item={item}
                selected={item.thread_id === selectedId}
                onClick={() => onSelect(item.thread_id)}
                isNew={newThreadIds.includes(item.thread_id)}
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── ThreadHeader ─────────────────────────────────────────────────────────────

function ThreadHeader({ thread }: { thread: PipelineResult }) {
  const att = thread.incoming_email?.attachment_paths || [];
  return (
    <div style={{ padding: "16px 24px 14px", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: -0.2, marginBottom: 4 }}>
            {thread.incoming_email?.subject || "Shipment Review"}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: "var(--text-secondary)", flexWrap: "wrap" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <Icon name="mail" size={13} color="var(--text-tertiary)" />
              <strong style={{ fontWeight: 500, color: "var(--text)" }}>
                {thread.incoming_email?.sender_name || thread.incoming_email?.sender}
              </strong>
              {thread.incoming_email?.sender_name && (
                <span className="mono" style={{ color: "var(--text-tertiary)" }}>
                  &lt;{thread.incoming_email.sender}&gt;
                </span>
              )}
            </span>
            {thread.received_at && (
              <>
                <span style={{ color: "var(--text-muted)" }}>·</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <Icon name="clock" size={12} color="var(--text-tertiary)" />
                  {formatRelTime(thread.received_at)}
                </span>
              </>
            )}
            <span style={{ color: "var(--text-muted)" }}>·</span>
            <span className="mono" style={{ color: "var(--text-tertiary)", fontSize: 11.5 }}>{thread.thread_id}</span>
          </div>
        </div>
        <StatusBadge status={thread.status} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
        <span style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginRight: 4, display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Icon name="paperclip" size={12} /> {att.length} attachments
        </span>
        {att.map((a) => (
          <span key={a} className="mono" style={{
            display: "inline-flex", alignItems: "center", gap: 5, padding: "2px 8px", borderRadius: 4,
            background: "var(--surface-sunken)", border: "1px solid var(--border)", fontSize: 11, color: "var(--text-secondary)",
          }}>
            <Icon name="doc" size={11} color="var(--text-tertiary)" />
            {a.split("/").pop() || a}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── IncomingState ────────────────────────────────────────────────────────────

function IncomingState({ thread }: { thread: PipelineResult }) {
  const pct = thread.progress?.pct || 0;
  return (
    <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20, overflowY: "auto" }}>
      {/* Progress card */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "20px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 28, height: 28, borderRadius: 6,
              background: "var(--info-bg)", border: "1px solid var(--info-border)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Icon name="sparkles" size={15} color="var(--info)" />
            </div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>Agent is extracting and validating attached documents.</div>
              <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                Stage: <span className="mono">{thread.progress?.stage || "queued"}</span>
                {" · "}Estimated 12–25s remaining
              </div>
            </div>
          </div>
          <span className="mono" style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>{pct}%</span>
        </div>
        <Progress pct={pct} />
        <div style={{ marginTop: 18, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {[
            { id: "fetch",    label: "Fetch attachments" },
            { id: "extract",  label: "Extract fields" },
            { id: "validate", label: "Cross-validate" },
            { id: "draft",    label: "Draft reply" },
          ].map((s, i) => {
            const st = pct >= (i + 1) * 25 ? "done" : pct >= i * 25 ? "active" : "todo";
            return (
              <div key={s.id} style={{
                padding: "10px 12px", borderRadius: 6, border: "1px solid var(--border)",
                background: st === "active" ? "var(--info-bg)" : "var(--surface-2)",
                opacity: st === "todo" ? 0.55 : 1, display: "flex", alignItems: "center", gap: 8,
              }}>
                <span style={{
                  width: 16, height: 16, borderRadius: 999, border: "1.5px solid",
                  borderColor: st === "done" ? "var(--ok)" : st === "active" ? "var(--info)" : "var(--border-strong)",
                  background: st === "done" ? "var(--ok)" : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                }}>
                  {st === "done" && <Icon name="check" size={10} color="#fff" strokeWidth={2.5} />}
                  {st === "active" && <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--info)", animation: "pulse 1.4s ease-in-out infinite" }} />}
                </span>
                <span style={{ fontSize: 12, fontWeight: 500, color: st === "todo" ? "var(--text-tertiary)" : "var(--text)" }}>
                  {s.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Inbound message preview */}
      {thread.incoming_email?.preview && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "16px 20px" }}>
          <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, marginBottom: 8 }}>
            Inbound message
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text-secondary)" }}>
            {thread.incoming_email.preview}
          </div>
        </div>
      )}

      <div style={{ fontSize: 11.5, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="lock" size={12} />
        Agent will pause at draft. No reply is sent automatically.
      </div>
    </div>
  );
}

// ─── VerificationTable ────────────────────────────────────────────────────────

function VerificationTable({ rows, selectedRow, onRowClick }: {
  rows: FieldValidation[];
  selectedRow: FieldValidation | null;
  onRowClick: (r: FieldValidation) => void;
}) {
  const order: Record<string, number> = { mismatch: 0, uncertain: 1, match: 2 };
  const sorted = [...rows].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      {/* Header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(200px,1.6fr) 130px minmax(140px,1.1fr) minmax(130px,1.2fr) minmax(130px,1.2fr) 130px",
        fontSize: 11, fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase",
        color: "var(--text-tertiary)", padding: "9px 16px",
        borderBottom: "1px solid var(--border)", background: "var(--surface-2)",
      }}>
        <div>Document · Field</div><div>Check</div><div>Found</div>
        <div>Expected</div><div>Confidence</div><div style={{ textAlign: "right" }}>Status</div>
      </div>
      {/* Rows */}
      {sorted.map((r, i) => {
        const flagged = r.status !== "match";
        const sel = selectedRow === r;
        const rowBg = sel ? "var(--selected)"
          : flagged ? r.status === "mismatch"
            ? "color-mix(in oklab, var(--err-bg) 38%, white)"
            : "color-mix(in oklab, var(--warn-bg) 35%, white)"
          : "transparent";
        return (
          <button key={`${r.field_name}-${i}`}
            onClick={() => flagged && onRowClick(r)}
            disabled={!flagged}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(200px,1.6fr) 130px minmax(140px,1.1fr) minmax(130px,1.2fr) minmax(130px,1.2fr) 130px",
              width: "100%", textAlign: "left", background: rowBg, border: "none",
              borderTop: i === 0 ? "none" : "1px solid var(--border-subtle)",
              borderLeft: sel ? "2px solid var(--accent)" : "2px solid transparent",
              padding: "12px 14px", fontSize: 12.5, cursor: flagged ? "pointer" : "default",
              alignItems: "center", gap: 8, color: "inherit",
            }}
            onMouseEnter={(e) => { if (flagged && !sel) e.currentTarget.style.background = "var(--hover)"; }}
            onMouseLeave={(e) => {
              if (sel) return;
              e.currentTarget.style.background = flagged
                ? r.status === "mismatch"
                  ? "color-mix(in oklab, var(--err-bg) 38%, white)"
                  : "color-mix(in oklab, var(--warn-bg) 35%, white)"
                : "transparent";
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 500, color: "var(--text)", marginBottom: 1 }}>{r.field_name}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.document_name ? (r.document_name.split("/").pop() || r.document_name) : "—"}
              </div>
            </div>
            <div>
              <span style={{
                display: "inline-block", fontSize: 11, color: "var(--text-secondary)",
                background: "var(--surface-sunken)", border: "1px solid var(--border)",
                padding: "1px 7px", borderRadius: 3, fontWeight: 500,
              }}>
                {r.validation_type === "customer_rules" ? "Customer rule" : "Cross-doc"}
              </span>
            </div>
            <div className="mono" style={{
              fontSize: 12, color: r.status === "mismatch" ? "var(--err)" : "var(--text)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              fontWeight: r.status === "mismatch" ? 500 : 400,
            }}>
              {r.found_value || <span style={{ color: "var(--text-muted)" }}>—</span>}
            </div>
            <div className="mono" style={{ fontSize: 12, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {r.expected_value || <span style={{ color: "var(--text-muted)" }}>—</span>}
            </div>
            <div>{r.confidence != null && <Confidence value={r.confidence} />}</div>
            <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 6 }}>
              <StatusBadge status={r.status} size="sm" />
              {flagged && <Icon name="chevron-right" size={13} color="var(--text-tertiary)" />}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── DiscrepancyDrawer ────────────────────────────────────────────────────────

function DiscrepancyDrawer({
  row,
  onClose,
  onReviewAction,
}: {
  row: FieldValidation | null;
  onClose: () => void;
  onReviewAction: (row: FieldValidation, action: "accept_found_value" | "mark_resolved") => void;
}) {
  if (!row) return null;
  return (
    <div style={{
      width: 420, flexShrink: 0, borderLeft: "1px solid var(--border)",
      background: "var(--surface)", height: "100%", overflowY: "auto",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{
        padding: "14px 18px", borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
        position: "sticky", top: 0, background: "var(--surface)", zIndex: 1,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="alert" size={14} color={row.status === "mismatch" ? "var(--err)" : "var(--warn)"} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Discrepancy detail</span>
        </div>
        <button onClick={onClose} style={{
          background: "transparent", border: "none", cursor: "pointer",
          padding: 4, color: "var(--text-tertiary)", borderRadius: 4,
          display: "flex", alignItems: "center",
        }}>
          <Icon name="x" size={14} />
        </button>
      </div>
      <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Field info */}
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 4 }}>Field</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{row.field_name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StatusBadge status={row.status} size="sm" />
            <span style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
              {row.validation_type === "customer_rules" ? "Customer rule check" : "Cross-document check"}
            </span>
            {row.confidence != null && <Confidence value={row.confidence} />}
          </div>
        </div>

        {/* Found / Expected */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{
            padding: "10px 12px", borderRadius: 6,
            background: row.status === "mismatch" ? "var(--err-bg)" : "var(--warn-bg)",
            border: `1px solid ${row.status === "mismatch" ? "var(--err-border)" : "var(--warn-border)"}`,
          }}>
            <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 4 }}>Found</div>
            <div className="mono" style={{ fontSize: 12.5, color: row.status === "mismatch" ? "var(--err)" : "var(--warn)", fontWeight: 500, wordBreak: "break-word" }}>
              {row.found_value || "—"}
            </div>
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 6, background: "var(--surface-sunken)", border: "1px solid var(--border)" }}>
            <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 4 }}>Expected</div>
            <div className="mono" style={{ fontSize: 12.5, color: "var(--text)", fontWeight: 500, wordBreak: "break-word" }}>
              {row.expected_value || "—"}
            </div>
          </div>
        </div>

        {/* Source snippet */}
        <div>
          <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 6 }}>Source document</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
            <Icon name="doc" size={13} color="var(--text-tertiary)" />
            <span className="mono" style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
              {(() => { const d = row.source_doc || row.document_name || ""; return d ? (d.split("/").pop() || d) : "—"; })()}
            </span>
          </div>
          <div style={{
            padding: "12px 14px", background: "var(--surface-2)", border: "1px solid var(--border)",
            borderLeft: `3px solid ${row.status === "mismatch" ? "var(--err)" : "var(--warn)"}`,
            borderRadius: 4, fontSize: 12, color: "var(--text-secondary)",
            whiteSpace: "pre-wrap", lineHeight: 1.55,
            fontFamily: '"Geist Mono", ui-monospace, monospace',
          }}>
            {row.source_snippet || "Source snippet unavailable."}
          </div>
        </div>

        {/* Expected reference */}
        {row.source_doc_expected && (
          <div>
            <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 6 }}>Expected reference</div>
            <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{row.source_doc_expected}</div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, paddingTop: 14, borderTop: "1px solid var(--border-subtle)" }}>
          <Btn variant="secondary" size="sm" icon="check" onClick={() => onReviewAction(row, "accept_found_value")}>
            Accept found value
          </Btn>
          <Btn variant="ghost" size="sm" onClick={() => onReviewAction(row, "mark_resolved")}>
            Mark as resolved
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── DraftReply ───────────────────────────────────────────────────────────────

function isThreadSent(thread: PipelineResult): boolean {
  return (
    thread.status === "sent" ||
    thread.human_review_status === "sent" ||
    thread.mock_send_result?.status === "sent"
  );
}

function DraftReply({ thread, draft, setDraft, edited, sent, sending, onApprove, onReset }: {
  thread: PipelineResult; draft: string; setDraft: (v: string) => void;
  edited: boolean; sent: boolean; sending: boolean; onApprove: () => void; onReset: () => void;
}) {
  const isSent = isThreadSent(thread) || sent;
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--border-subtle)", background: "var(--surface-2)",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="mail" size={14} color="var(--text-secondary)" />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Draft reply</span>
          {isSent ? (
            <StatusBadge status="sent" size="sm" />
          ) : (
            <span style={{ fontSize: 11, color: "var(--text-tertiary)", padding: "1px 7px", borderRadius: 3, background: "var(--surface-sunken)", border: "1px solid var(--border)" }}>
              Generated by agent · awaiting approval
            </span>
          )}
          {sending && !isSent && <span style={{ fontSize: 11, color: "var(--accent-text)" }}>Sending...</span>}
          {edited && !isSent && !sending && <span style={{ fontSize: 11, color: "var(--accent-text)" }}>Edited</span>}
        </div>
        {edited && !isSent && !sending && <Btn variant="ghost" size="sm" onClick={onReset}>Revert to agent draft</Btn>}
      </div>
      {/* Address */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--border-subtle)",
        display: "grid", gridTemplateColumns: "60px 1fr", gap: "6px 12px", fontSize: 12.5,
      }}>
        <span style={{ color: "var(--text-tertiary)" }}>To</span>
        <span className="mono" style={{ color: "var(--text)" }}>{thread.incoming_email?.sender}</span>
        <span style={{ color: "var(--text-tertiary)" }}>Subject</span>
        <span style={{ color: "var(--text)" }}>Re: {thread.incoming_email?.subject}</span>
      </div>
      {/* Textarea */}
      <textarea
        readOnly={isSent || sending}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        style={{
          display: "block", width: "100%", minHeight: 280, border: "none", outline: "none",
          padding: "16px 20px", fontFamily: '"Geist", -apple-system, sans-serif',
          fontSize: 13, lineHeight: 1.65, boxSizing: "border-box",
          color: isSent ? "var(--text-secondary)" : "var(--text)",
          background: isSent ? "var(--surface-2)" : "var(--surface)",
          resize: "vertical",
        }}
      />
      {/* Footer */}
      <div style={{
        padding: "12px 16px", borderTop: "1px solid var(--border-subtle)", background: "var(--surface-2)",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: "var(--text-tertiary)" }}>
          <Icon name="lock" size={12} />
          {isSent ? (
            <>
              Sent {thread.mock_send_result?.sent_at ? `at ${new Date(thread.mock_send_result.sent_at).toLocaleString()}` : ""}
              {thread.mock_send_result?.delivery ? ` via ${thread.mock_send_result.delivery.toUpperCase()}` : ""}
              {" · "}delivery receipt stored
            </>
          ) : (
            <>Approval required — agent will not send automatically.</>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="primary" icon="send" onClick={onApprove} disabled={isSent || sending}>
            {isSent ? "Sent" : sending ? "Sending..." : "Approve & Send"}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── ExtractionSummary ────────────────────────────────────────────────────────

function ExtractionSummary({ data }: { data: Record<string, { value: string | null; confidence: number | null }> }) {
  const entries = FIELD_KEYS
    .map((k) => [k, data[k]] as [string, { value: string | null; confidence: number | null }])
    .filter(([, v]) => v && v.value);
  if (entries.length === 0) return null;

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}>
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Extracted fields</span>
          <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{entries.length} of {FIELD_KEYS.length}</span>
        </div>
        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>across {entries.length} fields</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)" }}>
        {entries.map(([k, v], i) => (
          <div key={k} style={{
            padding: "10px 14px", minWidth: 0,
            borderRight: i % 4 !== 3 ? "1px solid var(--border-subtle)" : "none",
            borderTop: i >= 4 ? "1px solid var(--border-subtle)" : "none",
          }}>
            <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.4, fontWeight: 600, marginBottom: 3 }}>
              {FIELD_LABELS[k] || k}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
              <span className="mono" style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
                {v.value}
              </span>
              <Confidence value={v.confidence} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SummaryStat ──────────────────────────────────────────────────────────────

function SummaryStat({ n, label, tone }: { n: number; label: string; tone: "ok" | "err" | "warn" }) {
  const colors = { ok: "var(--ok)", err: "var(--err)", warn: "var(--warn)" };
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span className="mono" style={{ fontSize: 18, fontWeight: 600, color: colors[tone], lineHeight: 1 }}>{n}</span>
      <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</span>
    </div>
  );
}

function buildDraftFromValidation(thread: PipelineResult, validations: FieldValidation[]): string {
  const subject = thread.incoming_email?.subject || "submitted shipment documents";
  const flagged = validations.filter((row) => row.status !== "match");

  if (flagged.length === 0) {
    return [
      `Subject: Approved - ${subject}`,
      "",
      "Dear Shipping Unit,",
      "",
      "We have reviewed the submitted shipment document set and the validation checks are clear. The documents are approved for onward processing.",
      "",
      "Thank you,",
      "GoComet Trade Compliance Team",
    ].join("\n");
  }

  return [
    "Subject: Amendment Request - Shipping Document Discrepancy",
    "",
    "Dear Shipping Unit,",
    "",
    "The document set was reviewed and the following discrepancies require correction:",
    ...flagged.map((row) => {
      const doc = row.document_name || "document";
      const found = row.found_value || "-";
      const expected = row.expected_value || "-";
      return `  - ${doc}: ${row.field_name} (${row.status}) - found "${found}"; expected "${expected}"`;
    }),
    "",
    "Please issue corrected documents at your earliest convenience.",
    "",
    "GoComet Trade Compliance Team",
  ].join("\n");
}

// ─── ReviewState ──────────────────────────────────────────────────────────────

function ReviewState({ thread, onApprove, onReviewAction, onRerun, sending = false }: {
  thread: PipelineResult;
  onApprove?: (threadId: string, draft: string) => void;
  onReviewAction: (row: FieldValidation, action: "accept_found_value" | "mark_resolved") => void;
  onRerun?: () => void;
  sending?: boolean;
}) {
  const [draft, setDraft] = useState(thread.edited_email_text || thread.decision_reasoning_or_draft || "");
  const [edited, setEdited] = useState(false);
  const [sent, setSent] = useState(isThreadSent(thread));
  const [selectedRow, setSelectedRow] = useState<FieldValidation | null>(null);
  const [filterFlagged, setFilterFlagged] = useState(false);

  const confidenceByDocAndField = new Map<string, number | null>();
  const extractionRows = Array.isArray(thread.extracted_data)
    ? thread.extracted_data
    : thread.extracted_data
      ? [thread.extracted_data]
      : [];
  for (const src of extractionRows as Array<Record<string, unknown>>) {
    const docName = String(src.document_name || "");
    for (const key of FIELD_KEYS) {
      const fv = src[key] as { confidence?: number | null } | undefined;
      if (fv && typeof fv === "object" && "confidence" in fv) {
        confidenceByDocAndField.set(`${docName}::${key}`, fv.confidence ?? null);
      }
    }
  }

  const validations = (thread.validation_results || []).map((row) => ({
    ...row,
    confidence: row.confidence ?? confidenceByDocAndField.get(`${row.document_name || ""}::${row.field_name}`) ?? null,
  }));
  const flaggedCount  = validations.filter((r) => r.status !== "match").length;
  const matchedCount  = validations.filter((r) => r.status === "match").length;
  const mismatchCount = validations.filter((r) => r.status === "mismatch").length;
  const uncertainCount = validations.filter((r) => r.status === "uncertain").length;
  const agentDraft = thread.edited_email_text || thread.decision_reasoning_or_draft || buildDraftFromValidation(thread, validations);

  useEffect(() => {
    setDraft(agentDraft);
    setEdited(false);
    setSent(isThreadSent(thread));
    setSelectedRow(null);
    setFilterFlagged(false);
  }, [thread.thread_id, agentDraft, thread.status, thread.human_review_status, thread.mock_send_result?.status]);

  const displayedValidations = filterFlagged
    ? validations.filter((r) => r.status !== "match")
    : validations;

  const handleSetDraft = (v: string) => {
    setDraft(v);
    setEdited(v !== agentDraft);
  };

  // Normalize extracted_data → Record<string, FieldValue>
  let extractedMap: Record<string, { value: string | null; confidence: number | null }> | null = null;
  if (thread.extracted_data && !Array.isArray(thread.extracted_data)) {
    const src = thread.extracted_data as unknown as Record<string, unknown>;
    const mapped: Record<string, { value: string | null; confidence: number | null }> = {};
    for (const key of FIELD_KEYS) {
      const fv = src[key] as { value?: string | null; confidence?: number | null } | undefined;
      if (fv && typeof fv === "object" && "value" in fv) {
        mapped[key] = { value: fv.value ?? null, confidence: fv.confidence ?? null };
      }
    }
    if (Object.keys(mapped).length > 0) extractedMap = mapped;
  } else if (Array.isArray(thread.extracted_data) && thread.extracted_data.length > 0) {
    const src = thread.extracted_data[0] as unknown as Record<string, unknown>;
    const mapped: Record<string, { value: string | null; confidence: number | null }> = {};
    for (const key of FIELD_KEYS) {
      const fv = src[key] as { value?: string | null; confidence?: number | null } | undefined;
      if (fv && typeof fv === "object" && "value" in fv) {
        mapped[key] = { value: fv.value ?? null, confidence: fv.confidence ?? null };
      }
    }
    if (Object.keys(mapped).length > 0) extractedMap = mapped;
  }

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
        {/* Decision summary */}
        <div style={{
          background: "var(--surface)", border: "1px solid var(--border)",
          borderLeft: `3px solid ${flaggedCount > 0 ? "var(--warn)" : "var(--ok)"}`,
          borderRadius: 8, padding: "14px 18px",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, marginBottom: 2 }}>
                Agent decision
              </div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {thread.final_decision === "draft_amendment"
                  ? "Draft amendment request — operator review"
                  : thread.final_decision === "auto_approve"
                    ? "Auto-approve candidate"
                    : "Flag for review"}
              </div>
            </div>
            <div style={{ width: 1, height: 32, background: "var(--border)" }} />
            <div style={{ display: "flex", gap: 16 }}>
              <SummaryStat n={matchedCount}  label="Match"     tone="ok"   />
              <SummaryStat n={mismatchCount} label="Mismatch"  tone="err"  />
              <SummaryStat n={uncertainCount} label="Uncertain" tone="warn" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="secondary" size="sm" icon="mail" onClick={() => setSelectedRow(null)}>
              Email
            </Btn>
            <Btn
              variant="secondary" size="sm" icon="filter"
              onClick={() => setFilterFlagged((f) => !f)}
              style={filterFlagged ? { background: "var(--accent-soft)", borderColor: "var(--selected-border)", color: "var(--accent-text)" } : undefined}
            >
              {filterFlagged ? "Flagged only" : "Filter"}
            </Btn>
            <Btn variant="ghost" size="sm" icon="refresh" onClick={onRerun} disabled={!onRerun || isThreadSent(thread)}>Re-run</Btn>
          </div>
        </div>

        {/* Extraction summary */}
        {extractedMap && <ExtractionSummary data={extractedMap} />}

        {/* Validation results */}
        {validations.length > 0 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, padding: "0 2px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Validation results</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)", background: "var(--surface-sunken)", padding: "1px 6px", borderRadius: 3 }}>
                  {displayedValidations.length}{filterFlagged && validations.length !== displayedValidations.length ? ` of ${validations.length}` : ""}
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
                Click a flagged row to inspect the source snippet.
              </div>
            </div>
            <VerificationTable rows={displayedValidations} selectedRow={selectedRow} onRowClick={setSelectedRow} />
          </div>
        )}
      </div>

      {selectedRow ? (
        <DiscrepancyDrawer
          row={selectedRow}
          onClose={() => setSelectedRow(null)}
          onReviewAction={(row, action) => {
            onReviewAction(row, action);
            setSelectedRow(null);
          }}
        />
      ) : (
        <aside style={{
          width: 480,
          flexShrink: 0,
          borderLeft: "1px solid var(--border)",
          background: "var(--bg)",
          height: "100%",
          overflowY: "auto",
          padding: 16,
          boxSizing: "border-box",
        }}>
          <DraftReply
            thread={thread}
            draft={draft}
            setDraft={handleSetDraft}
            edited={edited}
            sent={sent}
            sending={sending}
            onApprove={() => { onApprove?.(thread.thread_id, draft); }}
            onReset={() => { setDraft(agentDraft); setEdited(false); }}
          />
        </aside>
      )}
    </div>
  );
}

// ─── FailedState ──────────────────────────────────────────────────────────────

function FailedState({ thread }: { thread: PipelineResult }) {
  return (
    <div style={{ padding: 24 }}>
      <div style={{
        background: "var(--surface)", border: "1px solid var(--err-border)",
        borderLeft: "3px solid var(--err)", borderRadius: 8, padding: "16px 20px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Icon name="alert" size={15} color="var(--err)" />
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>Extraction failed</span>
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 14 }}>
          {thread.error_message || "The backend worker failed before completing this thread."}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="primary"   size="sm" icon="refresh">Retry extraction</Btn>
          <Btn variant="secondary" size="sm">Open in manual review</Btn>
        </div>
      </div>
    </div>
  );
}

// ─── MainPanel ────────────────────────────────────────────────────────────────

function MainPanel({ thread, onApprove, onReviewAction, onRerun, sendingThreadId, banner, onLoadUpdate, onDismissBanner, loading }: {
  thread: PipelineResult | null;
  onApprove: (threadId: string, draft: string) => void;
  onReviewAction: (row: FieldValidation, action: "accept_found_value" | "mark_resolved") => void;
  onRerun: () => void;
  sendingThreadId: string | null;
  banner: boolean;
  onLoadUpdate: () => void;
  onDismissBanner: () => void;
  loading: boolean;
}) {
  if (!thread && !loading) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13, background: "var(--bg)" }}>
        Select a thread from the queue.
      </div>
    );
  }
  if (loading && !thread) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <div className="spinner-sm" />
          <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>Loading thread…</span>
        </div>
      </div>
    );
  }
  if (!thread) return null;

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)" }}>
      <ThreadHeader thread={thread} />
      {banner && (
        <div style={{
          background: "color-mix(in oklab, var(--accent-soft) 70%, white)",
          borderBottom: "1px solid var(--selected-border)",
          padding: "8px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--accent-text)" }}>
            <Icon name="sparkles" size={13} color="var(--accent)" />
            New results available for this thread — extraction completed since you opened it.
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <Btn variant="ghost"    size="sm" onClick={onDismissBanner}>Dismiss</Btn>
            <Btn variant="primary"  size="sm" onClick={onLoadUpdate}>Load update</Btn>
          </div>
        </div>
      )}
      <div style={{ flex: 1, overflow: "hidden", minHeight: 0 }}>
        {thread.status === "processing" && <IncomingState thread={thread} />}
        {(thread.status === "pending_review" || thread.status === "sent" || thread.status === "complete") && (
          <ReviewState
            thread={thread}
            onApprove={onApprove}
            onReviewAction={onReviewAction}
            onRerun={onRerun}
            sending={sendingThreadId === thread.thread_id}
          />
        )}
        {thread.status === "failed" && <FailedState thread={thread} />}
      </div>
    </div>
  );
}

// ─── QueryDataTab ─────────────────────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  "How many shipments are awaiting operator review?",
  "Show all SU threads with HS code mismatches this week",
  "Which customer rule fails most often?",
  "Average time-to-resolution for amendment drafts",
];

function QueryDataTab() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ text: string; rows?: Record<string, unknown>[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk(text?: string) {
    const question = (text ?? q).trim();
    if (!question) return;
    setQ(question);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await runQuery(question);
      setResult({ text: data.answer, rows: data.rows });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", background: "var(--bg)" }}>
      <div style={{ maxWidth: 880, margin: "0 auto", padding: "32px 24px 64px" }}>
        <div style={{ marginBottom: 4, fontSize: 11.5, color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>
          Query data
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: -0.4, margin: "0 0 6px" }}>Ask the pipeline</h1>
        <p style={{ fontSize: 13.5, color: "var(--text-secondary)", margin: "0 0 22px", maxWidth: 560 }}>
          Natural-language access to extracted shipment fields, validation history, and SLA stats. Read-only.
        </p>

        {/* Search composer */}
        <div style={{
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
          padding: 4, display: "flex", alignItems: "center", gap: 4, boxShadow: "var(--shadow-sm)",
        }}>
          <Icon name="search" size={14} color="var(--text-muted)" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Show all SU threads with HS code mismatches this week"
            onKeyDown={(e) => e.key === "Enter" && q && handleAsk()}
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", padding: "8px", fontSize: 13.5, color: "var(--text)" }}
          />
          <Btn variant="primary" size="sm" disabled={!q || loading} onClick={() => handleAsk()}>
            {loading ? "Querying…" : "Ask"}
          </Btn>
        </div>

        {/* Suggested chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14 }}>
          {EXAMPLE_QUESTIONS.map((ex) => (
            <button key={ex} onClick={() => handleAsk(ex)} style={{
              padding: "5px 11px", borderRadius: 999,
              background: "var(--surface)", border: "1px solid var(--border-strong)",
              fontSize: 12, color: "var(--text-secondary)", cursor: "pointer",
            }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "var(--surface)")}
            >
              {ex}
            </button>
          ))}
        </div>

        {error && <div style={{ marginTop: 16, fontSize: 13, color: "var(--err)" }}>{error}</div>}

        {/* Answer card */}
        {(loading || result) && (
          <div style={{ marginTop: 28, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
            <div style={{ padding: "12px 18px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="sparkles" size={13} color="var(--accent)" />
              <span style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>{q}</span>
            </div>
            <div style={{ padding: "16px 18px" }}>
              {loading ? (
                <div style={{ color: "var(--text-tertiary)", fontSize: 13 }}>Querying pipeline data…</div>
              ) : result ? (
                <>
                  <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 12, lineHeight: 1.55, color: "var(--text)" }}>
                    {result.text}
                  </div>
                  {result.rows && result.rows.length > 0 && (() => {
                    const cols = Object.keys(result.rows![0]);
                    return (
                      <div style={{ border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
                        <div style={{
                          display: "grid", gridTemplateColumns: `repeat(${cols.length}, 1fr)`,
                          padding: "8px 12px", fontSize: 11, fontWeight: 600, letterSpacing: 0.4,
                          textTransform: "uppercase", color: "var(--text-tertiary)",
                          background: "var(--surface-2)", borderBottom: "1px solid var(--border-subtle)",
                        }}>
                          {cols.map((c) => <span key={c}>{c}</span>)}
                        </div>
                        {result.rows!.map((r, i) => (
                          <div key={i} style={{
                            display: "grid", gridTemplateColumns: `repeat(${cols.length}, 1fr)`,
                            padding: "9px 12px", fontSize: 12.5, alignItems: "center",
                            borderTop: i ? "1px solid var(--border-subtle)" : "none",
                          }}>
                            {cols.map((c) => (
                              <span key={c} className="mono" style={{ color: "var(--text-secondary)" }}>
                                {String(r[c] ?? "—")}
                              </span>
                            ))}
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── CGWorkflowTab ────────────────────────────────────────────────────────────

const CG_SELECTED_THREAD_KEY = "nova.cg.selectedThreadId";

function CGWorkflowTab() {
  const [queue, setQueue] = useState<PendingReviewItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState(false);
  const [sendingThreadId, setSendingThreadId] = useState<string | null>(null);
  const selectedThreadRef = useRef<string | null>(null);
  const resultStatusRef = useRef<PipelineResult["status"] | null>(null);
  const draftDirtyRef = useRef(false);
  const sendingThreadRef = useRef<string | null>(null);

  function applyResult(data: PipelineResult, opts?: { preserveDirtyDraft?: boolean }) {
    const normalized = isThreadSent(data) ? { ...data, status: "sent" as const } : data;
    setResult(normalized);
    resultStatusRef.current = normalized.status;
    if (!opts?.preserveDirtyDraft || !draftDirtyRef.current) {
      draftDirtyRef.current = false;
    }
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
    setBanner(false);
    try {
      const data = await getStatus(threadId);
      setSelectedId(threadId);
      selectedThreadRef.current = threadId;
      window.localStorage.setItem(CG_SELECTED_THREAD_KEY, threadId);
      applyResult(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove(threadId: string, draft: string) {
    if (!threadId || !draft.trim()) return;
    if (sendingThreadRef.current === threadId) return;
    sendingThreadRef.current = threadId;
    setSendingThreadId(threadId);
    setError(null);
    try {
      const data = await resumePipeline(threadId, draft);
      applyResult(data);
      await loadQueue();
    } catch (e) {
      setError(String(e));
    } finally {
      sendingThreadRef.current = null;
      setSendingThreadId(null);
    }
  }

  async function handleReviewAction(row: FieldValidation, action: "accept_found_value" | "mark_resolved") {
    if (!selectedThreadRef.current) return;
    setError(null);
    try {
      const data = await applyReviewAction(selectedThreadRef.current, row, action);
      applyResult(data);
      await loadQueue();
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    async function init() {
      await loadQueue();
      const saved = window.localStorage.getItem(CG_SELECTED_THREAD_KEY);
      if (saved) await openThread(saved);
    }
    init();
  }, []);

  useEffect(() => {
    const stream = createReviewQueueStream();
    stream.addEventListener("queue", (event) => {
      try {
        const rows = JSON.parse((event as MessageEvent).data) as PendingReviewItem[];
        setQueue(rows);
        const selId = selectedThreadRef.current;
        if (!selId) return;
        const selItem = rows.find((item) => item.thread_id === selId);
        if (selItem?.status && selItem.status !== resultStatusRef.current) setBanner(true);
      } catch (e) {
        setError(String(e));
      }
    });
    stream.onerror = () => setError("Live queue connection interrupted. Use Sync if the queue looks stale.");
    return () => stream.close();
  }, []);

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {error && (
        <div style={{
          position: "fixed", bottom: 16, right: 16, zIndex: 50,
          background: "var(--err-bg)", border: "1px solid var(--err-border)",
          borderRadius: 8, padding: "10px 16px", fontSize: 12.5, color: "var(--err)",
          maxWidth: 360, boxShadow: "var(--shadow-md)",
        }}>
          {error}
        </div>
      )}
      <QueueSidebar
        items={queue}
        selectedId={selectedId}
        onSelect={openThread}
        onSync={loadQueue}
        newThreadIds={[]}
      />
      <MainPanel
        thread={result}
        onApprove={handleApprove}
        onReviewAction={handleReviewAction}
        onRerun={() => { if (selectedId) openThread(selectedId); }}
        sendingThreadId={sendingThreadId}
        banner={banner}
        onLoadUpdate={() => { if (selectedId) openThread(selectedId); }}
        onDismissBanner={() => setBanner(false)}
        loading={loading}
      />
    </div>
  );
}

// ─── App root ─────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState("workflow");
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <TopNav tab={tab} setTab={setTab} />
      {tab === "workflow" ? <CGWorkflowTab /> : <QueryDataTab />}
    </div>
  );
}
