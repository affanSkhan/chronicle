export type ResearchMode = "quick" | "deep" | "academic" | "forensic";
export type RunStatus = "queued" | "running" | "completed" | "failed";

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
}

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

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
  execute?: boolean;
}): Promise<ResearchRun> {
  const response = await fetch(`${API_BASE}/api/v1/research/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun>;
}

export async function listResearchRuns(): Promise<ResearchRun[]> {
  const response = await fetch(`${API_BASE}/api/v1/research/runs`, { cache: "no-store" });
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

export async function searchAcademicSources(query: string, limit = 10, provider = "all") {
  const params = new URLSearchParams({ q: query, limit: String(limit), provider });
  const response = await fetch(`${API_BASE}/api/v1/sources/search?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<{
    query: string;
    results: AcademicSearchResult[];
    provider_errors: Record<string, string>;
    note: string;
  }>;
}

export async function importPaper(paper: Omit<AcademicSearchResult, "provider"> & { provider: string }) {
  const response = await fetch(`${API_BASE}/api/v1/sources/papers`, {
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
  const response = await fetch(`${API_BASE}/api/v1/documents/upload`, {
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
  change_summary: string | null;
  review_required: boolean;
  created_at: string;
}

export async function listReportVersions(runId: string): Promise<ReportVersionSummary[]> {
  const response = await fetch(`${API_BASE}/api/v1/evidence/runs/${runId}/reports`, { cache: "no-store" });
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
  const response = await fetch(`${API_BASE}/api/v1/evidence/runs/${runId}/graph`, { cache: "no-store" });
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
  const response = await fetch(`${API_BASE}/api/v1/sources/papers?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<LibraryPaper[]>;
}

export async function listSourceEvents(limit = 50): Promise<SourceEventRecord[]> {
  const response = await fetch(`${API_BASE}/api/v1/sources/events?limit=${limit}`, { cache: "no-store" });
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
  const response = await fetch(`${API_BASE}/api/v1/sources/papers/${paperId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}
