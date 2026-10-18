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
}

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function readError(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (typeof payload?.detail === "string") return payload.detail;
  return \`Chronicle API request failed (\${response.status}).\`;
}

export async function createResearchRun(input: {
  question: string;
  mode: ResearchMode;
  max_sources?: number;
  project_id?: string | null;
}): Promise<ResearchRun> {
  const response = await fetch(\`\${API_BASE}/api/v1/research/runs\`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<ResearchRun>;
}

export async function listResearchRuns(): Promise<ResearchRun[]> {
  const response = await fetch(\`\${API_BASE}/api/v1/research/runs\`, { cache: "no-store" });
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
  const response = await fetch(\`\${API_BASE}/api/v1/sources/search?\${params.toString()}\`, { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<{
    query: string;
    results: AcademicSearchResult[];
    provider_errors: Record<string, string>;
    note: string;
  }>;
}

export async function importPaper(paper: Omit<AcademicSearchResult, "provider"> & { provider: string }) {
  const response = await fetch(\`\${API_BASE}/api/v1/sources/papers\`, {
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
  const response = await fetch(\`\${API_BASE}/api/v1/documents/upload\`, {
    method: "POST",
    body: form
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<PDFUploadResult>;
}
