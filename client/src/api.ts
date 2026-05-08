import type { FieldValidation, PendingReviewItem, PipelineResult } from "./types";

const BASE = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

function headers(extra?: Record<string, string>) {
  return { "x-api-key": API_KEY, ...extra };
}

export async function getStatus(jobId: string): Promise<PipelineResult> {
  const res = await fetch(`${BASE}/pipeline/status/${jobId}`, {
    headers: headers(),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Status check failed");
  }

  return res.json();
}

export async function getPendingReview(): Promise<PendingReviewItem[]> {
  const res = await fetch(`${BASE}/pipeline/review-queue`, {
    headers: headers(),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Review queue lookup failed");
  }

  return res.json();
}

export function createReviewQueueStream(): EventSource {
  const url = new URL(`${BASE}/pipeline/review-queue/stream`, window.location.origin);
  url.searchParams.set("api_key", API_KEY);
  return new EventSource(url.toString());
}

export async function resumePipeline(
  threadId: string,
  editedEmailText: string,
): Promise<PipelineResult> {
  const res = await fetch(`${BASE}/pipeline/resume/${threadId}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ edited_email_text: editedEmailText }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Resume failed");
  }

  return res.json();
}

export async function applyReviewAction(
  threadId: string,
  row: FieldValidation,
  action: "accept_found_value" | "mark_resolved",
): Promise<PipelineResult> {
  const res = await fetch(`${BASE}/pipeline/review-action/${threadId}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      field_name: row.field_name,
      document_name: row.document_name ?? null,
      validation_type: row.validation_type ?? null,
      action,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Review action failed");
  }

  return res.json();
}

export interface QueryResponse {
  question: string;
  sql: string;
  answer: string;
  rows: Record<string, unknown>[];
  row_count: number;
}

export async function runQuery(question: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Query failed");
  }

  return res.json();
}
