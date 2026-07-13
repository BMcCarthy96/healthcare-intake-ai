export type CaseStatus =
  | "received"
  | "queued"
  | "processing"
  | "ready_for_export"
  | "missing_information"
  | "review_required"
  | "failed"
  | "completed";

export type CaseSummary = {
  id: string;
  external_reference: string;
  status: CaseStatus;
  source: string;
  document_count: number;
  created_at?: string;
  updated_at?: string;
};

export type Evidence = { page_number: number; quote: string; confidence: number };
export type ExtractedField = { name: string; value: string | null; evidence: Evidence | null };
export type IntakeRecord = {
  case_reference: string | null;
  member_identifier: string | null;
  requesting_organization: string | null;
  requesting_contact: string | null;
  service_code: string | null;
  requested_start_date: string | null;
  document_types_present: string[];
  notes: string | null;
  fields: ExtractedField[];
};
export type CaseDetail = CaseSummary & {
  documents: { id: string; original_filename: string; page_count: number | null; size_bytes: number; created_at?: string }[];
  latest_record: IntakeRecord | null;
  validation_issues: { id: string; code: string; severity: string; field_name: string | null; message: string; evidence: Record<string, unknown> | null; created_at?: string }[];
  model_runs: { id: string; provider: string; model: string; route_tier: string; duration_ms: number | null; status: string; created_at?: string }[];
  events: { id: string; event_type: string; actor: string; correlation_id: string; details: Record<string, unknown> | null; created_at?: string }[];
  reviewer_approved: boolean;
};
export type EvalRun = { id: string; dataset: string; total_cases: number; matched_cases: number; routing_accuracy: number; field_accuracy: number; results: { case_id: string; expected_status: string; actual_status: string; matched: boolean; issue?: string | null; fields_matched: number; fields_compared: number }[] };

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { ...(options?.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: { message: "Request failed" } }));
    throw new Error(payload.detail?.message || "Request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  listCases: () => request<CaseSummary[]>("/v1/cases"),
  seedDemo: () => request<CaseSummary>("/v1/demo/seed", { method: "POST" }),
  getCase: (id: string) => request<CaseDetail>(`/v1/cases/${id}`),
  createCase: (external_reference: string) => request<CaseSummary>("/v1/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ external_reference, source: "reviewer-console" }) }),
  upload: (id: string, file: File) => { const form = new FormData(); form.append("file", file); return request(`/v1/cases/${id}/documents`, { method: "POST", body: form }); },
  process: (id: string) => request(`/v1/cases/${id}/process`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }),
  review: (id: string, action: "approve" | "correct" | "request_information", corrections: Record<string, string | null> = {}, reason?: string) => request<CaseSummary>(`/v1/cases/${id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, reviewer: "demo-reviewer", corrections, reason }) }),
  exportCase: (id: string) => request(`/v1/cases/${id}/export`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }),
  runEval: (dataset: "development" | "held_out") => request<EvalRun>(`/v1/evals?dataset=${dataset}`, { method: "POST" }),
};
