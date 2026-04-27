import type { PipelineResult } from "./types";

const BASE = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

function headers(extra?: Record<string, string>) {
  return { "x-api-key": API_KEY, ...extra };
}

export async function submitDocument(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE}/pipeline/process`, {
    method: "POST",
    headers: headers(),
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }

  return res.json();
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
