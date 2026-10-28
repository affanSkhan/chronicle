export type ResearchMode = "quick" | "deep" | "academic" | "forensic";
export type RunStatus = "queued" | "running" | "completed" | "completed_with_limitations" | "failed" | "cancel_requested" | "cancelled";

export interface ResearchRun {
  id: string;
  question: string;
  mode: ResearchMode;
  status: RunStatus;
  max_sources: number;
  project_id: string | null;
  created_at: string;
  demo: boolean;
  error_message?: string | null;
  cancel_requested_at?: string | null;
  cancelled_at?: string | null;
  retry_of_run_id?: string | null;
}

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const SESSION_TOKEN_KEY = "chronicle.access-token";

export interface AuthUser {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer" | string;
  expires_in: number;
  user: AuthUser;
}

export function hasSavedAccessToken(): boolean {
  return typeof window !== "undefined" && Boolean(window.sessionStorage.getItem(SESSION_TOKEN_KEY));
}

export function saveAccessToken(token: string): void {
  if (typeof window !== "undefined") window.sessionStorage.setItem(SESSION_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
}

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = typeof window !== "undefined" ? window.sessionStorage.getItem(SESSION_TOKEN_KEY) : null;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

export async function registerAccount(email: string, password: string): Promise<AuthResponse> {
  const response = await apiFetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AuthResponse>;
}

export async function loginAccount(email: string, password: string): Promise<AuthResponse> {
  const response = await apiFetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AuthResponse>;
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await apiFetch(`${API_BASE}/api/v1/auth/me`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AuthUser>;
}


async function readError(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (typeof payload?.detail === "string") return payload.detail;
  return `Chronicle API request failed (${response.status}).`;
}

export async function createResearchRun(input: {
  question: string;
  mode: ResearchMode;
  max_sources?: number;
  project_id?: string | null;
  source_paper_ids?: string[];
  execute?: boolean;
}): Promise<ResearchRun> {
  const response = await apiFetch(`${API_BASE}/api/v1/research/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun>;
}

export async function cancelResearchRun(runId: string): Promise<ResearchRun> {
  const response = await apiFetch(`${API_BASE}/api/v1/research/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    cache: "no-store"
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun>;
}

export async function retryResearchRun(runId: string): Promise<ResearchRun> {
  const response = await apiFetch(`${API_BASE}/api/v1/research/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
    cache: "no-store"
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun>;
}

export async function listResearchRuns(): Promise<ResearchRun[]> {
  const response = await apiFetch(`${API_BASE}/api/v1/research/runs`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun[]>;
}

export interface AcademicSearchResult {
  provider: string;
  external_id: string | null;
  doi: string | null;
  title: string;
  authors: string[];
  abstract: string | null;
  publication_year: number | null;
  publisher: string | null;
  landing_url: string | null;
}

export interface ResearchProjectRecord {
  id: string;
  title: string;
  research_question: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export async function listResearchProjects(includeArchived = false): Promise<ResearchProjectRecord[]> {
  const params = new URLSearchParams({ include_archived: String(includeArchived) });
  const response = await apiFetch(`${API_BASE}/api/v1/projects?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchProjectRecord[]>;
}

export async function createResearchProject(input: {
  title: string;
  research_question: string;
}): Promise<ResearchProjectRecord> {
  const response = await apiFetch(`${API_BASE}/api/v1/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchProjectRecord>;
}

export async function updateResearchProject(
  projectId: string,
  input: { title?: string; research_question?: string; archived?: boolean }
): Promise<ResearchProjectRecord> {
  const response = await apiFetch(`${API_BASE}/api/v1/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchProjectRecord>;
}


export async function searchAcademicSources(query: string, limit = 10, provider = "all") {
  const params = new URLSearchParams({ q: query, limit: String(limit), provider });
  const response = await apiFetch(`${API_BASE}/api/v1/sources/search?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<{
    query: string;
    results: AcademicSearchResult[];
    provider_errors: Record<string, string>;
    note: string;
  }>;
}

export async function importPaper(paper: Omit<AcademicSearchResult, "provider"> & { provider: string }) {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(paper)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}


export interface PDFUploadResult {
  paper_id: string;
  paper_version_id?: string;
  title: string;
  page_count?: number;
  text_characters?: number;
  passages_created?: number;
  sha256?: string;
  duplicate_upload: boolean;
  note?: string;
  message?: string;
}

export async function uploadPdf(file: File): Promise<PDFUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch(`${API_BASE}/api/v1/documents/upload`, {
    method: "POST",
    body: form
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<PDFUploadResult>;
}


export interface ReportVersionSummary {
  id: string;
  run_id: string;
  version_number: number;
  parent_version_id: string | null;
  title: string;
  content_markdown: string;
  evidence_snapshot?: Record<string, unknown> | null;
  change_summary: string | null;
  review_required: boolean;
  created_at: string;
}

export async function listReportVersions(runId: string): Promise<ReportVersionSummary[]> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/runs/${runId}/reports`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ReportVersionSummary[]>;
}


export interface EvidenceGraphNode {
  id: string;
  type: string;
  label: string;
  assessment?: string;
  review_required?: boolean;
  page_number?: number | null;
  paper_version_id?: string;
  publication_status?: string;
  paper_id?: string;
  doi?: string | null;
  source_passage_id?: string | null;
  extraction_basis?: string;
  provenance_basis?: string;
  report_version_number?: number;
  created_at?: string | null;
  population?: string | null;
  method?: string | null;
  intervention?: string | null;
  outcomes?: string[];
  limitations?: string[];
  rationale?: string | null;
  evidence_passage_ids?: string[];
  prior_art_search_queries?: string[];
  alternative_explanations?: string[];
  falsification_plan?: string | null;
  review_status?: string;
}

export interface EvidenceGraphEdge {
  id?: string;
  source: string;
  target: string;
  type: string;
  provenance_basis?: string;
  reviewer_status?: string;
  confidence?: number | null;
  rationale?: string | null;
}

export interface EvidenceGraphResponse {
  run_id: string;
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
  note: string;
}

export async function getEvidenceGraph(runId: string): Promise<EvidenceGraphResponse> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/runs/${runId}/graph`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<EvidenceGraphResponse>;
}


export interface LibraryPaper {
  id: string;
  doi: string | null;
  title: string;
  authors: string[];
  abstract: string | null;
  publication_year: number | null;
  publisher: string | null;
  source_provider: string;
  external_id: string | null;
  landing_url: string | null;
  monitoring_enabled: boolean;
  monitor_interval_minutes: number;
  last_status_check_at: string | null;
  next_status_check_at: string | null;
}

export interface SourceEventRecord {
  id: string;
  paper_id: string;
  paper_title: string;
  event_type: string;
  event_date: string | null;
  observed_at: string;
  source_url: string | null;
  description: string;
  verification_status: string;
  metadata_snapshot: Record<string, unknown>;
}

export async function listLibraryPapers(limit = 100): Promise<LibraryPaper[]> {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<LibraryPaper[]>;
}

export async function listSourceEvents(limit = 50): Promise<SourceEventRecord[]> {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/events?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const payload = await response.json() as { events: SourceEventRecord[] };
  return payload.events;
}

export async function createSourceEvent(input: {
  paperId: string;
  event_type: "correction" | "retraction" | "expression_of_concern" | "new_version" | "metadata_change" | "conflicting_study";
  description: string;
  source_url?: string;
  verification_status: "unverified" | "metadata_confirmed" | "human_verified";
  event_date?: string;
}): Promise<{
  event: { id: string; paper_id: string; event_type: string; verification_status: string };
  impact: {
    impacted_paper_ids: string[];
    affected_claim_ids: string[];
    claims_flagged_for_review: number;
    affected_run_ids: string[];
    report_versions_flagged_for_review: number;
  };
  note: string;
}> {
  const { paperId, ...payload } = input;
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers/${paperId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}




export type DependencyCandidateRelationType = "same_dataset" | "duplicate_or_overlap";

export interface DependencyCandidate {
  id: string;
  paper_a_id: string;
  paper_a_title: string;
  paper_a_doi: string | null;
  paper_b_id: string;
  paper_b_title: string;
  paper_b_doi: string | null;
  relation_type: DependencyCandidateRelationType;
  provenance_basis: "metadata_inferred" | string;
  confidence: number;
  signals: string[];
  rationale: string;
  direction: "symmetric" | string;
}

export async function listDependencyCandidates(limit = 30): Promise<{
  count: number;
  candidates: DependencyCandidate[];
  note: string;
}> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/dependency-candidates?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function addPaperDependency(input: {
  dependent_paper_id: string;
  depends_on_paper_id: string;
  relation_type: DependencyCandidateRelationType;
  provenance_basis: "human_reviewed" | "metadata_inferred";
  rationale: string;
  confidence: number;
}): Promise<{ id: string; duplicate?: boolean }> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/paper-dependencies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<{ id: string; duplicate?: boolean }>;
}

export interface CitationVerificationResult {
  claim_id: string;
  verdict: "supported" | "partially_supported" | "contradicted" | "insufficient_evidence" | "unverifiable" | string;
  rationale: string;
  evidence_passage_ids: string[];
  context_note?: string | null;
  uncertainty_notes: string[];
  review_required: boolean;
  reviewer_status: string;
  provenance_basis: string;
  verifier_model: string;
  notice: string;
}

export async function verifyClaimCitationSupport(claimId: string): Promise<CitationVerificationResult> {
  const response = await apiFetch(
    `${API_BASE}/api/v1/evidence/claims/${encodeURIComponent(claimId)}/verify`,
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<CitationVerificationResult>;
}

export async function reviewEvidenceRelation(
  relationId: string,
  reviewerStatus: "accepted" | "rejected" | "needs_review",
  reviewerNotes?: string
): Promise<{ id: string; reviewer_status: string; provenance_basis: string; relation_type: string }> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/relations/${relationId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer_status: reviewerStatus, reviewer_notes: reviewerNotes })
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}


export interface SourceStatusSignal {
  provider: string;
  event_type: "correction" | "retraction" | "expression_of_concern" | "new_version" | "metadata_change" | "conflicting_study";
  update_type: string;
  description: string;
  source_url: string | null;
  verification_status: string;
  metadata: Record<string, unknown>;
}

export interface PaperStatusCheck {
  paper_id: string;
  doi: string | null;
  providers?: Record<string, string>;
  provider_states?: Record<string, string>;
  signals: SourceStatusSignal[];
  note: string;
  id?: string;
  checked_at?: string;
  trigger_type?: string;
  outcome?: string;
  change_detected?: boolean;
  previous_result_hash?: string | null;
  result_hash?: string;
  monitoring_enabled?: boolean;
  next_status_check_at?: string | null;
}

export async function checkPaperStatus(paperId: string): Promise<PaperStatusCheck> {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers/${paperId}/status-check`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<PaperStatusCheck>;
}


export async function downloadEvidencePassport(runId: string, format: "markdown" | "json" | "pdf" = "markdown"): Promise<void> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/runs/${runId}/passport?format=${format}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `chronicle-evidence-passport-${runId.slice(0, 8)}.${format === "json" ? "json" : format === "pdf" ? "pdf" : "md"}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}


export interface AuditEventRecord {
  id: string;
  actor_user_id: string | null;
  target_entity_type: string;
  target_entity_id: string;
  action: string;
  previous_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  resolution_status: string;
  created_at: string;
}

export async function listRunAuditEvents(runId: string, limit = 100): Promise<AuditEventRecord[]> {
  const response = await apiFetch(`${API_BASE}/api/v1/evidence/runs/${runId}/audit?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const payload = await response.json() as { events: AuditEventRecord[] };
  return payload.events;
}



export async function recordPaperStatusCheck(paperId: string): Promise<PaperStatusCheck> {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers/${paperId}/status-check`, { method: "POST" });
  if (!response.ok) throw new Error(await readError(response));
  const result = await response.json() as PaperStatusCheck;
  return { ...result, providers: result.provider_states ?? result.providers ?? {} };
}

export async function configurePaperMonitoring(
  paperId: string,
  enabled: boolean,
  intervalMinutes = 1440
): Promise<LibraryPaper> {
  const response = await apiFetch(`${API_BASE}/api/v1/sources/papers/${paperId}/monitoring`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, interval_minutes: intervalMinutes })
  });
  if (!response.ok) throw new Error(await readError(response));
  const config = await response.json() as {
    paper_id: string; monitoring_enabled: boolean; monitor_interval_minutes: number;
    last_status_check_at: string | null; next_status_check_at: string | null;
  };
  const existing = (await listLibraryPapers(100)).find((paper) => paper.id === paperId);
  if (!existing) throw new Error("Saved paper was not found after monitoring settings were updated.");
  return { ...existing, ...config };
}

export interface SourceStatusCheckRecord extends PaperStatusCheck {
  id: string;
  paper_id: string;
  paper_title: string;
  checked_at: string;
  trigger_type: "manual" | "scheduled" | string;
  outcome: "ok" | "partial" | "unavailable" | "failed" | "no_doi" | string;
  provider_states: Record<string, string>;
  change_detected: boolean;
  result_hash: string;
  error_message: string | null;
}

export async function listSourceStatusChecks(
  limit = 50,
  changesOnly = false
): Promise<SourceStatusCheckRecord[]> {
  const params = new URLSearchParams({ limit: String(limit), changes_only: String(changesOnly) });
  const response = await apiFetch(`${API_BASE}/api/v1/sources/status-checks?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const payload = await response.json() as { checks: SourceStatusCheckRecord[] };
  return payload.checks;
}
