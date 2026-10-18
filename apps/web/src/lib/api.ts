export type ResearchMode = "quick" | "deep" | "academic" | "forensic";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface ResearchRun {
  id: string;
  question: string;
  mode: ResearchMode;
  status: RunStatus;
  created_at: string;
  demo: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function createResearchRun(input: {
  question: string;
  mode: ResearchMode;
  max_sources?: number;
}): Promise<ResearchRun> {
  const response = await fetch(`${API_BASE}/api/v1/research/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Could not create research run (${response.status}).`);
  }
  return response.json() as Promise<ResearchRun>;
}
