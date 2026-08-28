export type CaseStatus =
  | "received"
  | "queued"
  | "processing"
  | "ready_for_export"
  | "missing_information"
  | "review_required"
  | "failed"
  | "exporting"
  | "completed";

export type CaseSummary = {
  id: string;
  external_reference: string;
  status: CaseStatus;
  source: string;
  scenario?: string | null;
  document_count: number;
  issue_count: number;
  workspace_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type EvidenceBox = { x: number; y: number; width: number; height: number };
export type Evidence = {
  document_id?: string | null;
  page_number: number;
  quote: string;
  confidence: number;
  provenance?: "model" | "reviewer";
  start_char?: number | null;
  end_char?: number | null;
  boxes: EvidenceBox[];
  source_mode: "native" | "ocr" | "unknown";
  source_confidence?: number | null;
};
export type ExtractedField = { name: string; value: string | null; evidence: Evidence | null };
export type IntakeRecord = {
  schema_version: string;
  case_reference: string | null;
  member_identifier: string | null;
  requesting_organization: string | null;
  requesting_contact: string | null;
  service_code: string | null;
  requested_start_date: string | null;
  document_types_present: string[];
  notes: string | null;
  fields: ExtractedField[];
  patient_name?: string | null;
  date_of_birth?: string | null;
  payer_name?: string | null;
  group_number?: string | null;
  provider_name?: string | null;
  provider_npi?: string | null;
  procedure_codes?: string[];
  diagnosis_codes?: string[];
  requested_service_date?: string | null;
};

export type ExportAttempt = {
  id: string;
  operation_id?: string | null;
  case_id: string;
  extraction_id: string | null;
  idempotency_key: string;
  attempt_number: number;
  status: string;
  response_status: number | null;
  response_body: Record<string, unknown> | null;
  request_signature?: string | null;
  downstream_record_id?: string | null;
  retryable?: boolean;
  error_message: string | null;
  created_at?: string;
  completed_at?: string;
};

export type CaseDetail = CaseSummary & {
  documents: { id: string; original_filename: string; page_count: number | null; size_bytes: number; source_mode: string; created_at?: string }[];
  latest_record: IntakeRecord | null;
  validation_issues: { id: string; code: string; severity: string; field_name: string | null; message: string; evidence: Record<string, unknown> | null; extraction_id?: string | null; resolved_at?: string | null; created_at?: string }[];
  model_runs: { id: string; provider: string; model: string; route_tier: string; duration_ms: number | null; status: string; purpose?: string; created_at?: string }[];
  events: { id: string; event_type: string; actor: string; correlation_id: string; details: Record<string, unknown> | null; created_at?: string }[];
  reviewer_approved: boolean;
  latest_extraction_id?: string | null;
  latest_extraction_version?: number | null;
  export_attempts: ExportAttempt[];
};

export type EvalRun = {
  id: string;
  dataset: string;
  total_cases: number;
  matched_cases: number;
  routing_accuracy: number;
  field_accuracy: number;
  routing_macro_f1: number;
  field_macro_f1: number;
  false_ready_count: number;
  evidence_validity: number;
  category_metrics: Record<string, { cases: number; routing_accuracy: number; field_accuracy: number; false_ready_count: number }>;
  results: { case_id: string; category?: string; expected_status: string; actual_status: string; matched: boolean; issue?: string | null; fields_matched: number; fields_compared: number; evidence_valid?: boolean }[];
};

export type DemoScenario = { id: string; title: string; description: string; status: string; case_id?: string | null; recommended: boolean };
export type TourStep = { id: string; title: string; body: string; target: string; route: string };
export type DemoSession = { session_id: string; token: string; expires_at: string; scenario_version: string; scenarios: DemoScenario[]; tour: TourStep[] };
export type DemoManifest = Omit<DemoSession, "token">;
export type PageData = { document_id: string; page_number: number; text: string; source_mode: string; source_confidence: number | null; width: number | null; height: number | null; image_url: string };
export type ModelComparison = { id: string; case_id: string; provider: string; model: string; status: string; result?: Record<string, unknown> | null; error_message?: string | null; created_at?: string };
export type Meta = { app_version: string; api_commit_sha: string; frontend_commit_sha?: string; build_time?: string | null; schema_version: string; mode: string; demo_scenario_version: string; custom_uploads_enabled: boolean; live_model_compare_enabled: boolean; evaluation_runs_enabled: boolean };
export type Job = { id: string; case_id: string; job_type: string; status: string; stage: string; attempt: number; progress: number; idempotency_key: string; correlation_id: string; failure_classification?: string | null; error_message?: string | null; created_at?: string; completed_at?: string };
export type Proof = { generated_at?: string | null; commit_sha: string; frontend_commit_sha?: string; build_time?: string | null; app_version: string; schema_version: string; demo_scenario_version: string; provider: string; latest_evaluation?: EvalRun | null; quality_gates: Record<string, boolean>; limitations: string[] };

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}

export function getDemoToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem("intakeflow-demo-token");
}

export function setDemoSession(session: DemoSession): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem("intakeflow-demo-token", session.token);
  window.sessionStorage.setItem("intakeflow-demo-session", session.session_id);
  window.sessionStorage.setItem("intakeflow-demo-expires", session.expires_at);
  window.sessionStorage.setItem("intakeflow-tour-step", "0");
  window.sessionStorage.removeItem("intakeflow-tour-paused");
}

export function clearDemoSession(): void {
  if (typeof window === "undefined") return;
  Object.keys(window.sessionStorage)
    .filter((key) => key.startsWith("intakeflow-"))
    .forEach((key) => window.sessionStorage.removeItem(key));
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

function stableKey(kind: string, caseId: string): string {
  if (typeof window === "undefined") return `${kind}-${caseId}-${crypto.randomUUID()}`;
  const key = `intakeflow-${kind}-${caseId}`;
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const created = `${kind}-${caseId}-${crypto.randomUUID()}`;
  window.sessionStorage.setItem(key, created);
  return created;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  const token = getDemoToken();
  if (token) headers.set("X-Demo-Session", token);
  const response = await fetch(apiUrl(path), { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: { message: `Request failed (${response.status})` } }));
    const detail = typeof payload.detail === "string" ? payload.detail : payload.detail?.message;
    throw new ApiError(detail || `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function fetchPageImage(documentId: string, page: number): Promise<string> {
  const headers = new Headers();
  const token = getDemoToken();
  if (token) headers.set("X-Demo-Session", token);
  const response = await fetch(apiUrl(`/v1/documents/${documentId}/pages/${page}/image`), { headers, cache: "no-store" });
  if (!response.ok) throw new Error("Rendered page image is unavailable.");
  return URL.createObjectURL(await response.blob());
}

export const api = {
  listCases: (filters?: { status?: string; risk?: string; query?: string }) => {
    const params = new URLSearchParams();
    if (filters?.status && filters.status !== "all") params.set("status", filters.status);
    if (filters?.risk && filters.risk !== "all") params.set("risk", filters.risk);
    if (filters?.query) params.set("query", filters.query);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<CaseSummary[]>(`/v1/cases${suffix}`);
  },
  seedDemo: () => request<CaseSummary>("/v1/demo/seed", { method: "POST" }),
  startDemo: () => request<DemoSession>("/v1/demo/sessions", { method: "POST" }),
  resetDemo: () => {
    const sessionId = typeof window === "undefined" ? "" : window.sessionStorage.getItem("intakeflow-demo-session");
    return request<DemoManifest>(`/v1/demo/sessions/${sessionId}/reset`, { method: "POST" });
  },
  manifest: () => request<DemoManifest>("/v1/demo/manifest"),
  getCase: (id: string) => request<CaseDetail>(`/v1/cases/${id}`),
  createCase: (external_reference: string) => request<CaseSummary>("/v1/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ external_reference, source: "reviewer-console" }) }),
  upload: (id: string, file: File) => { const form = new FormData(); form.append("file", file); return request(`/v1/cases/${id}/documents`, { method: "POST", body: form }); },
  process: (id: string) => request(`/v1/cases/${id}/process`, { method: "POST", headers: { "Idempotency-Key": stableKey("process", id) } }),
  review: (id: string, action: "approve" | "correct" | "request_information", corrections: Record<string, string | null> = {}, reason?: string, extractionId?: string | null) => request<CaseSummary>(`/v1/cases/${id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, reviewer: "demo-reviewer", corrections, reason, extraction_id: extractionId }) }),
  exportCase: (id: string) => request<{ status: string; attempt_id?: string; attempt_number?: number; message: string }>(`/v1/cases/${id}/export`, { method: "POST", headers: { "Idempotency-Key": stableKey("export", id) } }),
  exports: (id: string) => request<ExportAttempt[]>(`/v1/cases/${id}/exports`),
  getPage: (documentId: string, page: number) => request<PageData>(`/v1/documents/${documentId}/pages/${page}`),
  compareModels: (id: string) => request<ModelComparison>(`/v1/cases/${id}/model-comparisons`, { method: "POST" }),
  getJob: (id: string) => request<Job>(`/v1/jobs/${id}`),
  runEval: (dataset: "development" | "held_out" | "challenge") => request<EvalRun>(`/v1/evals?dataset=${dataset}`, { method: "POST" }),
  listEvals: () => request<EvalRun[]>("/v1/evals"),
  meta: () => request<Meta>("/v1/meta"),
  proof: () => request<Proof>("/v1/proof"),
};
