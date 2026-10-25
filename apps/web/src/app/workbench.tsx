"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, AlertCircle, ArrowRight, BookOpen, Check, ChevronDown, Clock3,
  FlaskConical, History, LayoutDashboard, LoaderCircle, LogOut, Network, Plus,
  RefreshCw, Search, ShieldCheck, Sparkles, Upload, X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  clearAccessToken, configurePaperMonitoring, createResearchRun, createSourceEvent,
  downloadEvidencePassport, fetchCurrentUser, getEvidenceGraph, hasSavedAccessToken,
  importPaper, listLibraryPapers, listReportVersions, listResearchRuns, listSourceEvents,
  listSourceStatusChecks, loginAccount, recordPaperStatusCheck, registerAccount,
  addPaperDependency, listDependencyCandidates,
  createResearchProject, listResearchProjects, updateResearchProject,
  reviewEvidenceRelation, saveAccessToken, searchAcademicSources, uploadPdf,
  verifyClaimCitationSupport,
  type AcademicSearchResult, type AuthUser, type CitationVerificationResult, type DependencyCandidate, type EvidenceGraphResponse, type LibraryPaper,
  type PaperStatusCheck, type ReportVersionSummary, type ResearchMode, type ResearchProjectRecord, type ResearchRun,
  type SourceEventRecord, type SourceStatusCheckRecord
} from "@/lib/api";

type View = "Overview" | "Research workspace" | "Evidence graph" | "Source timeline" | "Hypothesis lab";
type GraphNode = EvidenceGraphResponse["nodes"][number];
type GraphEdge = EvidenceGraphResponse["edges"][number];
type EventKind = "correction" | "retraction" | "expression_of_concern" | "new_version" | "metadata_change" | "conflicting_study";
type Verification = "unverified" | "metadata_confirmed" | "human_verified";

const NAV: { label: View; icon: LucideIcon }[] = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Research workspace", icon: BookOpen },
  { label: "Evidence graph", icon: Network },
  { label: "Source timeline", icon: History },
  { label: "Hypothesis lab", icon: FlaskConical }
];

const MODES: { value: ResearchMode; label: string }[] = [
  { value: "quick", label: "Quick discovery" },
  { value: "deep", label: "Deep research" },
  { value: "academic", label: "Academic review" },
  { value: "forensic", label: "Forensic analysis" }
];

const EVENT_TYPES: { value: EventKind; label: string }[] = [
  { value: "correction", label: "Correction" },
  { value: "retraction", label: "Retraction" },
  { value: "expression_of_concern", label: "Expression of concern" },
  { value: "new_version", label: "New version" },
  { value: "metadata_change", label: "Metadata change" },
  { value: "conflicting_study", label: "Conflicting study" }
];

function statusTone(status: string): string {
  if (status === "completed_with_limitations") return "bg-amber-50 text-amber-800 ring-amber-600/15";
  if (status === "completed" || status === "supported" || status === "human_verified" || status === "accepted") return "bg-emerald-50 text-emerald-700 ring-emerald-600/15";
  if (status === "failed" || status === "rejected" || status === "contradicted") return "bg-rose-50 text-rose-700 ring-rose-600/15";
  if (status === "running" || status === "queued" || status === "unverified" || status === "needs_review" || status === "qualified") return "bg-amber-50 text-amber-800 ring-amber-600/15";
  return "bg-slate-100 text-slate-600 ring-slate-500/10";
}

function StatusPill({ children, status }: { children: React.ReactNode; status: string }) {
  return <span className={"inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset " + statusTone(status)}>{children}</span>;
}

function formatDate(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function shorten(value: string, max = 120): string {
  const cleaned = value.trim();
  return cleaned.length > max ? cleaned.slice(0, max - 1).trimEnd() + "…" : cleaned;
}

function wrapSvgLabel(value: string, lineLength = 24): string[] {
  const words = value.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if ((line + " " + word).trim().length > lineLength && line) {
      lines.push(line);
      line = word;
    } else {
      line = (line + " " + word).trim();
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 2);
}

function graphLayer(type: string): number {
  if (type === "paper") return 0;
  if (type === "paper_version") return 1;
  if (type === "passage" || type === "study") return 2;
  if (type === "claim") return 3;
  return 2;
}

function edgeColor(type: string): string {
  if (type === "supports") return "#0f9f82";
  if (type === "contradicts") return "#e45c66";
  if (type === "qualifies" || type === "not_comparable" || type === "insufficient_evidence") return "#d99a2b";
  if (type === "depends_on" || type === "derived_from" || type === "same_dataset" || type === "duplicate_or_overlap") return "#7c73e6";
  return "#a1adbf";
}

function useGraphLayout(nodes: GraphNode[], edges: GraphEdge[]) {
  return useMemo(() => {
    const grouped: GraphNode[][] = [[], [], [], []];
    nodes.forEach((node) => grouped[graphLayer(node.type)].push(node));
    grouped.forEach((layer) => layer.sort((a, b) => a.label.localeCompare(b.label)));
    const columnX = [24, 262, 500, 738];
    const nodeWidth = 198;
    const nodeHeight = 84;
    const rowGap = 32;
    const rowCount = Math.max(1, ...grouped.map((layer) => layer.length));
    const height = Math.max(420, 70 + rowCount * (nodeHeight + rowGap));
    const placed: { node: GraphNode; x: number; y: number }[] = [];
    grouped.forEach((layer, layerIndex) => {
      layer.forEach((node, index) => {
        placed.push({
          node,
          x: columnX[layerIndex],
          y: 56 + index * (nodeHeight + rowGap)
        });
      });
    });
    const positions = new Map(placed.map((item) => [item.node.id, item]));
    const lines = edges.filter((edge) => positions.has(edge.source) && positions.has(edge.target)).map((edge) => {
      const source = positions.get(edge.source)!;
      const target = positions.get(edge.target)!;
      let sx = source.x + nodeWidth;
      let sy = source.y + nodeHeight / 2;
      let tx = target.x;
      let ty = target.y + nodeHeight / 2;
      let path: string;
      if (target.x > source.x) {
        const mid = (sx + tx) / 2;
        path = "M " + sx + " " + sy + " C " + mid + " " + sy + ", " + mid + " " + ty + ", " + tx + " " + ty;
      } else if (target.x < source.x) {
        sx = source.x;
        tx = target.x + nodeWidth;
        const mid = (sx + tx) / 2;
        path = "M " + sx + " " + sy + " C " + mid + " " + sy + ", " + mid + " " + ty + ", " + tx + " " + ty;
      } else if (target.y >= source.y) {
        sx = source.x + nodeWidth / 2;
        tx = target.x + nodeWidth / 2;
        sy = source.y + nodeHeight;
        ty = target.y;
        const mid = (sy + ty) / 2;
        path = "M " + sx + " " + sy + " C " + (sx + 38) + " " + mid + ", " + (tx + 38) + " " + mid + ", " + tx + " " + ty;
      } else {
        sx = source.x + nodeWidth / 2;
        tx = target.x + nodeWidth / 2;
        sy = source.y;
        ty = target.y + nodeHeight;
        const mid = (sy + ty) / 2;
        path = "M " + sx + " " + sy + " C " + (sx + 38) + " " + mid + ", " + (tx + 38) + " " + mid + ", " + tx + " " + ty;
      }
      return { edge, path, labelX: (sx + tx) / 2, labelY: (sy + ty) / 2 - 6 };
    });
    return { placed, positions, lines, height, nodeWidth, nodeHeight };
  }, [nodes, edges]);
}

function EmptyState({ icon: Icon, title, description, action }: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return <div className="flex min-h-56 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
    <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600"><Icon size={20}/></span>
    <h2 className="text-base font-semibold text-slate-900">{title}</h2>
    <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
    {action ? <div className="mt-5">{action}</div> : null}
  </div>;
}

export default function ChronicleWorkbench() {
  const [view, setView] = useState<View>("Overview");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authSubmitting, setAuthSubmitting] = useState(false);

  const [notice, setNotice] = useState("");
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [sourceEvents, setSourceEvents] = useState<SourceEventRecord[]>([]);
  const [statusChecks, setStatusChecks] = useState<SourceStatusCheckRecord[]>([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ResearchProjectRecord[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [showArchivedProjects, setShowArchivedProjects] = useState(false);
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [newProjectQuestion, setNewProjectQuestion] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectTitle, setEditingProjectTitle] = useState("");
  const [editingProjectQuestion, setEditingProjectQuestion] = useState("");
  const [savingProject, setSavingProject] = useState(false);

  const [question, setQuestion] = useState("");
  const [researchMode, setResearchMode] = useState<ResearchMode>("deep");
  const [maxSources, setMaxSources] = useState(10);
  const [creatingRun, setCreatingRun] = useState(false);
  const [reportVersions, setReportVersions] = useState<ReportVersionSummary[]>([]);
  const [reportLoading, setReportLoading] = useState(false);
  const [exporting, setExporting] = useState<"markdown" | "json" | null>(null);

  const [graphData, setGraphData] = useState<EvidenceGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [graphRefreshKey, setGraphRefreshKey] = useState(0);
  const [graphQuery, setGraphQuery] = useState("");
  const [graphType, setGraphType] = useState("all");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null);

  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceResults, setSourceResults] = useState<AcademicSearchResult[]>([]);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [savedPaperKeys, setSavedPaperKeys] = useState<string[]>([]);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");

  const [eventFormOpen, setEventFormOpen] = useState(false);
  const [eventPaperId, setEventPaperId] = useState("");
  const [eventType, setEventType] = useState<EventKind>("retraction");
  const [eventDescription, setEventDescription] = useState("");
  const [eventSourceUrl, setEventSourceUrl] = useState("");
  const [eventVerification, setEventVerification] = useState<Verification>("unverified");
  const [recordingEvent, setRecordingEvent] = useState(false);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [statusCheck, setStatusCheck] = useState<PaperStatusCheck | null>(null);
  const [monitorIntervalMinutes, setMonitorIntervalMinutes] = useState(1440);
  const [updatingMonitoring, setUpdatingMonitoring] = useState(false);
  const [showAdvancedSourceSearch, setShowAdvancedSourceSearch] = useState(false);
  const [showPdfUpload, setShowPdfUpload] = useState(false);
  const [reviewingRelationId, setReviewingRelationId] = useState<string | null>(null);
  const [verifyingClaimId, setVerifyingClaimId] = useState<string | null>(null);
  const [verificationByClaim, setVerificationByClaim] = useState<Record<string, CitationVerificationResult>>({});
  const [dependencyCandidates, setDependencyCandidates] = useState<DependencyCandidate[]>([]);
  const [dependencyCandidatesLoading, setDependencyCandidatesLoading] = useState(false);
  const [dependencyCandidatesLoaded, setDependencyCandidatesLoaded] = useState(false);
  const [dependencyCandidateError, setDependencyCandidateError] = useState("");
  const [savingDependencyCandidateId, setSavingDependencyCandidateId] = useState<string | null>(null);

  const activeRun = useMemo(() => runs.find((run) => run.id === activeRunId) ?? null, [runs, activeRunId]);
  const activeReport = reportVersions[0] ?? null;
  const selectedPaper = papers.find((paper) => paper.id === eventPaperId) ?? null;
  const synthesis = activeReport?.evidence_snapshot?.model_synthesis;
  const modelSynthesis = synthesis && typeof synthesis === "object" ? synthesis as {
    executive_summary?: string;
    findings?: { statement: string; evidence_passage_ids?: string[]; relation_type?: string; context_note?: string | null }[];
    disagreements?: { description: string; evidence_passage_ids?: string[]; comparability_note?: string | null }[];
    limitations?: string[];
    candidate_research_questions?: string[];
    research_opportunities?: { question: string; rationale: string; evidence_passage_ids?: string[]; prior_art_search_queries?: string[]; alternative_explanations?: string[]; falsification_plan: string; review_status?: string }[];
    uncertainty_statement?: string;
    human_review_required?: boolean;
  } : null;

  useEffect(() => {
    let cancelled = false;
    async function restoreSession() {
      if (!hasSavedAccessToken()) {
        setAuthLoading(false);
        return;
      }
      try {
        const user = await fetchCurrentUser();
        if (!cancelled) setAuthUser(user);
      } catch {
        clearAccessToken();
        if (!cancelled) setAuthUser(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    }
    void restoreSession();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authUser) {
      setRuns([]);
      setPapers([]);
      setSourceEvents([]);
      setStatusChecks([]);
      setActiveRunId(null);
      setReportVersions([]);
      setGraphData(null);
      return;
    }
    let cancelled = false;
    async function loadWorkspace() {
      setWorkspaceLoading(true);
      setWorkspaceError("");
      try {
        const results = await Promise.all([
          listResearchRuns(),
          listLibraryPapers(100),
          listSourceEvents(50),
          listSourceStatusChecks(50, false),
          listResearchProjects(true)
        ]);
        if (cancelled) return;
        const nextRuns = results[0] as ResearchRun[];
        const nextPapers = results[1] as LibraryPaper[];
        const nextProjects = results[4] as ResearchProjectRecord[];
        setRuns(nextRuns);
        setPapers(nextPapers);
        setProjects(nextProjects);
        setSourceEvents(results[2] as SourceEventRecord[]);
        setStatusChecks(results[3] as SourceStatusCheckRecord[]);
        setActiveRunId((current) => current && nextRuns.some((run) => run.id === current) ? current : (nextRuns[0]?.id ?? null));
        setEventPaperId((current) => current && nextPapers.some((paper) => paper.id === current) ? current : (nextPapers[0]?.id ?? ""));
        setActiveProjectId((current) => current && nextProjects.some((project) => project.id === current && !project.archived_at) ? current : (nextProjects.find((project) => !project.archived_at)?.id ?? null));
      } catch (error) {
        if (!cancelled) setWorkspaceError(error instanceof Error ? error.message : "Could not load your workspace.");
      } finally {
        if (!cancelled) setWorkspaceLoading(false);
      }
    }
    void loadWorkspace();
    return () => { cancelled = true; };
  }, [authUser]);

  useEffect(() => {
    if (!authUser || !activeRunId || (activeRun?.status !== "queued" && activeRun?.status !== "running")) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const nextRuns = await listResearchRuns();
        if (!cancelled) setRuns(nextRuns);
      } catch {
        // The current status stays visible; the user can refresh manually.
      }
    }, 3500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [authUser, activeRunId, activeRun?.status]);

  useEffect(() => {
    if (!authUser || !activeRunId || (activeRun?.status !== "completed" && activeRun?.status !== "completed_with_limitations")) {
      setReportVersions([]);
      return;
    }
    let cancelled = false;
    setReportLoading(true);
    listReportVersions(activeRunId).then((reports) => {
      if (!cancelled) setReportVersions(reports);
    }).catch(() => {
      if (!cancelled) setReportVersions([]);
    }).finally(() => {
      if (!cancelled) setReportLoading(false);
    });
    return () => { cancelled = true; };
  }, [authUser, activeRunId, activeRun?.status]);

  useEffect(() => {
    if (!authUser || view !== "Evidence graph" || !activeRunId) return;
    let cancelled = false;
    setGraphLoading(true);
    setGraphError("");
    getEvidenceGraph(activeRunId).then((graph) => {
      if (cancelled) return;
      setGraphData(graph);
      setSelectedGraphNodeId((current) => current && graph.nodes.some((node) => node.id === current) ? current : (graph.nodes[0]?.id ?? null));
    }).catch((error) => {
      if (!cancelled) setGraphError(error instanceof Error ? error.message : "Could not load evidence for this run.");
    }).finally(() => {
      if (!cancelled) setGraphLoading(false);
    });
    return () => { cancelled = true; };
  }, [authUser, view, activeRunId, graphRefreshKey]);

  useEffect(() => {
    const selected = papers.find((paper) => paper.id === eventPaperId);
    if (selected) setMonitorIntervalMinutes(selected.monitor_interval_minutes);
  }, [eventPaperId, papers]);

  async function submitAuthentication(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthSubmitting(true);
    setAuthError("");
    try {
      const result = authMode === "register"
        ? await registerAccount(authEmail.trim(), authPassword)
        : await loginAccount(authEmail.trim(), authPassword);
      saveAccessToken(result.access_token);
      setAuthUser(result.user);
      setAuthPassword("");
      setNotice(authMode === "register" ? "Account created." : "Signed in.");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed. Check your connection and credentials.");
    } finally {
      setAuthSubmitting(false);
      setAuthLoading(false);
    }
  }

  function signOut() {
    clearAccessToken();
    setAuthUser(null);
    setView("Overview");
    setRuns([]);
    setProjects([]);
    setActiveProjectId(null);
    setPapers([]);
    setSourceEvents([]);
    setReportVersions([]);
    setGraphData(null);
    setStatusCheck(null);
    setNotice("Signed out.");
  }

  async function refreshWorkspace() {
    setWorkspaceLoading(true);
    setWorkspaceError("");
    try {
      const results = await Promise.all([
        listResearchRuns(), listLibraryPapers(100), listSourceEvents(50), listSourceStatusChecks(50, false), listResearchProjects(true)
      ]);
      const nextRuns = results[0] as ResearchRun[];
      const nextProjects = results[4] as ResearchProjectRecord[];
      setRuns(nextRuns);
      setProjects(nextProjects);
      setActiveProjectId((current) => current && nextProjects.some((project) => project.id === current && !project.archived_at) ? current : (nextProjects.find((project) => !project.archived_at)?.id ?? null));
      setPapers(results[1] as LibraryPaper[]);
      setSourceEvents(results[2] as SourceEventRecord[]);
      setStatusChecks(results[3] as SourceStatusCheckRecord[]);
      setActiveRunId((current) => current && nextRuns.some((run) => run.id === current) ? current : (nextRuns[0]?.id ?? null));
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Could not refresh your workspace.");
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function submitNewProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newProjectTitle.trim().length < 2 || newProjectQuestion.trim().length < 8) {
      setNotice("Workspace title needs 2 characters and its research question needs 8.");
      return;
    }
    setCreatingProject(true);
    setWorkspaceError("");
    try {
      const project = await createResearchProject({
        title: newProjectTitle.trim(),
        research_question: newProjectQuestion.trim(),
      });
      setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
      setActiveProjectId(project.id);
      setNewProjectTitle("");
      setNewProjectQuestion("");
      setNotice("Research workspace created.");
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Could not create the workspace.");
    } finally {
      setCreatingProject(false);
    }
  }

  function beginEditProject(project: ResearchProjectRecord) {
    setEditingProjectId(project.id);
    setEditingProjectTitle(project.title);
    setEditingProjectQuestion(project.research_question);
  }

  async function saveEditedProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingProjectId) return;
    setSavingProject(true);
    setWorkspaceError("");
    try {
      const updated = await updateResearchProject(editingProjectId, {
        title: editingProjectTitle.trim(),
        research_question: editingProjectQuestion.trim(),
      });
      setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditingProjectId(null);
      setNotice("Workspace details updated.");
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Could not update the workspace.");
    } finally {
      setSavingProject(false);
    }
  }

  async function setProjectArchived(project: ResearchProjectRecord, archived: boolean) {
    setSavingProject(true);
    setWorkspaceError("");
    try {
      const updated = await updateResearchProject(project.id, { archived });
      setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
      if (archived && activeProjectId === project.id) setActiveProjectId(null);
      if (!archived) setActiveProjectId(project.id);
      if (editingProjectId === project.id) setEditingProjectId(null);
      setNotice(archived ? "Workspace archived. Its historical runs remain available." : "Workspace restored.");
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Could not change workspace archive state.");
    } finally {
      setSavingProject(false);
    }
  }

  async function submitResearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (question.trim().length < 8) {
      setNotice("Enter a research question of at least 8 characters.");
      return;
    }
    setCreatingRun(true);
    setNotice("");
    try {
      const created = await createResearchRun({
        question: question.trim(),
        mode: researchMode,
        max_sources: maxSources,
        project_id: activeProjectId,
        execute: true
      });
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setActiveRunId(created.id);
      setQuestion("");
      setView("Research workspace");
      setNotice("Research run started.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not start the research run.");
    } finally {
      setCreatingRun(false);
    }
  }

  async function refreshGraph() {
    if (!activeRunId) return;
    setGraphRefreshKey((value) => value + 1);
  }

  async function reviewRelation(relationId: string, reviewerStatus: "accepted" | "rejected" | "needs_review") {
    setReviewingRelationId(relationId);
    setGraphError("");
    try {
      await reviewEvidenceRelation(
        relationId,
        reviewerStatus,
        reviewerStatus === "accepted" ? "Reviewed by researcher in Chronicle." : "Researcher requested further review."
      );
      const graph = activeRunId ? await getEvidenceGraph(activeRunId) : null;
      if (graph) setGraphData(graph);
      setNotice(reviewerStatus === "accepted" ? "Relationship marked as reviewed." : "Relationship flagged for review.");
    } catch (error) {
      setGraphError(error instanceof Error ? error.message : "Could not save this review.");
    } finally {
      setReviewingRelationId(null);
    }
  }

  async function verifyClaim(claimNodeId: string) {
    const claimId = claimNodeId.startsWith("claim:") ? claimNodeId.slice("claim:".length) : claimNodeId;
    setVerifyingClaimId(claimNodeId);
    setGraphError("");
    try {
      const result = await verifyClaimCitationSupport(claimId);
      setVerificationByClaim((previous) => ({ ...previous, [claimNodeId]: result }));
      const graph = activeRunId ? await getEvidenceGraph(activeRunId) : null;
      if (graph) setGraphData(graph);
      setNotice(`Model assessment: ${result.verdict.replaceAll("_", " ")}. Human review is still required.`);
    } catch (error) {
      setGraphError(error instanceof Error ? error.message : "Citation verification failed.");
    } finally {
      setVerifyingClaimId(null);
    }
  }

  async function loadDependencyCandidates() {
    setDependencyCandidatesLoading(true);
    setDependencyCandidateError("");
    try {
      const result = await listDependencyCandidates(30);
      setDependencyCandidates(result.candidates);
      setDependencyCandidatesLoaded(true);
    } catch (error) {
      setDependencyCandidateError(error instanceof Error ? error.message : "Could not discover dependency candidates.");
    } finally {
      setDependencyCandidatesLoading(false);
    }
  }

  async function confirmDependencyCandidate(candidate: DependencyCandidate) {
    setSavingDependencyCandidateId(candidate.id);
    setDependencyCandidateError("");
    try {
      await addPaperDependency({
        dependent_paper_id: candidate.paper_a_id,
        depends_on_paper_id: candidate.paper_b_id,
        relation_type: candidate.relation_type,
        provenance_basis: "human_reviewed",
        rationale: "Researcher confirmed a candidate surfaced by Chronicle. Signal: " + candidate.signals.join("; ") + ". " + candidate.rationale,
        confidence: candidate.confidence,
      });
      setDependencyCandidates((previous) => previous.filter((item) => item.id !== candidate.id));
      setNotice("Source relationship confirmed. Updates to either linked record can now flag the other for human review.");
      if (activeRunId) {
        const graph = await getEvidenceGraph(activeRunId);
        setGraphData(graph);
      }
    } catch (error) {
      setDependencyCandidateError(error instanceof Error ? error.message : "Could not save the dependency link.");
    } finally {
      setSavingDependencyCandidateId(null);
    }
  }

  async function searchPapers() {
    if (sourceQuery.trim().length < 3) {
      setSourceError("Enter at least 3 characters.");
      return;
    }
    setSourceLoading(true);
    setSourceError("");
    try {
      const result = await searchAcademicSources(sourceQuery.trim(), 10, "all");
      setSourceResults(result.results);
      const failed = Object.keys(result.provider_errors ?? {});
      if (failed.length) setSourceError("Partial results: " + failed.join(", ") + " unavailable.");
      else if (!result.results.length) setSourceError("No papers found. Try another query.");
    } catch (error) {
      setSourceResults([]);
      setSourceError(error instanceof Error ? error.message : "Academic search failed.");
    } finally {
      setSourceLoading(false);
    }
  }

  function paperKey(paper: AcademicSearchResult) {
    return (paper.doi ? "doi:" + paper.doi.toLowerCase() : (paper.external_id || paper.title)).toLowerCase();
  }

  async function savePaper(paper: AcademicSearchResult) {
    const key = paperKey(paper);
    setSourceError("");
    setSavedPaperKeys((current) => current.includes(key) ? current : [...current, key]);
    try {
      await importPaper(paper);
      const nextPapers = await listLibraryPapers(100);
      setPapers(nextPapers);
      setEventPaperId((current) => current || (nextPapers[0]?.id ?? ""));
      setNotice("Paper saved to your library.");
    } catch (error) {
      setSavedPaperKeys((current) => current.filter((item) => item !== key));
      setSourceError(error instanceof Error ? error.message : "Could not save this paper.");
    }
  }

  async function handlePdfUpload(file?: File) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadMessage("Choose a PDF file.");
      return;
    }
    setUploadingPdf(true);
    setUploadMessage("");
    try {
      const uploaded = await uploadPdf(file);
      setUploadMessage(uploaded.duplicate_upload ? "This PDF is already in your library." : "PDF added. " + (uploaded.passages_created ?? 0) + " passages extracted.");
      setPapers(await listLibraryPapers(100));
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "PDF upload failed.");
    } finally {
      setUploadingPdf(false);
    }
  }

  async function checkPaperStatus() {
    if (!eventPaperId) {
      setNotice("Save a paper before checking its status.");
      return;
    }
    setCheckingStatus(true);
    setTimelineError("");
    try {
      const result = await recordPaperStatusCheck(eventPaperId);
      setStatusCheck(result);
      setStatusChecks(await listSourceStatusChecks(50, false));
      setPapers(await listLibraryPapers(100));
      setNotice("Source status checked.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Source status check failed.");
    } finally {
      setCheckingStatus(false);
    }
  }

  const [timelineError, setTimelineError] = useState("");

  async function submitSourceEvent(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!eventPaperId || eventDescription.trim().length < 8) {
      setTimelineError("Choose a paper and enter a short description.");
      return;
    }
    setRecordingEvent(true);
    setTimelineError("");
    try {
      const result = await createSourceEvent({
        paperId: eventPaperId,
        event_type: eventType,
        description: eventDescription.trim(),
        source_url: eventSourceUrl.trim() || undefined,
        verification_status: eventVerification
      });
      setSourceEvents(await listSourceEvents(50));
      setPapers(await listLibraryPapers(100));
      setEventDescription("");
      setEventFormOpen(false);
      setNotice("Source event recorded. " + result.impact.claims_flagged_for_review + " claim(s) flagged for review.");
    } catch (error) {
      setTimelineError(error instanceof Error ? error.message : "Could not record this source event.");
    } finally {
      setRecordingEvent(false);
    }
  }

  async function toggleMonitoring(enabled: boolean) {
    if (!eventPaperId) return;
    setUpdatingMonitoring(true);
    try {
      const updated = await configurePaperMonitoring(eventPaperId, enabled, monitorIntervalMinutes);
      setPapers((current) => current.map((paper) => paper.id === updated.id ? updated : paper));
      setNotice(enabled ? "Source monitoring enabled." : "Source monitoring disabled.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update source monitoring.");
    } finally {
      setUpdatingMonitoring(false);
    }
  }

  async function exportPassport(format: "markdown" | "json") {
    if (!activeRunId) return;
    setExporting(format);
    try {
      await downloadEvidencePassport(activeRunId, format);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not export the evidence passport.");
    } finally {
      setExporting(null);
    }
  }

  const graphSource = graphData?.run_id === activeRunId ? graphData : null;
  const visibleNodes = useMemo(() => {
    const list = graphSource?.nodes ?? [];
    const q = graphQuery.trim().toLowerCase();
    return list.filter((node) =>
      (graphType === "all" || node.type === graphType) &&
      (!q || (node.label + " " + node.type + " " + node.id).toLowerCase().includes(q))
    ).slice(0, 64);
  }, [graphSource, graphQuery, graphType]);
  const graphLayout = useGraphLayout(visibleNodes, graphSource?.edges ?? []);
  const selectedGraphNode = graphSource?.nodes.find((node) => node.id === selectedGraphNodeId) ?? null;
  const visibleGraphNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleGraphEdges = (graphSource?.edges ?? []).filter((edge) => visibleGraphNodeIds.has(edge.source) && visibleGraphNodeIds.has(edge.target));
  const currentPaperStatus = selectedPaper?.monitoring_enabled ? "Monitoring on" : "Monitoring off";

  if (authLoading) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500"><LoaderCircle className="mr-2 animate-spin" size={18}/> Loading Chronicle…</div>;
  }

  if (!authUser) {
    return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl shadow-slate-200/60 md:grid-cols-2">
        <section className="hidden flex-col justify-between bg-slate-950 p-10 text-white md:flex">
          <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10"><History size={22}/></span><div><div className="text-lg font-semibold">chronicle.</div><div className="text-xs text-slate-400">Evidence intelligence</div></div></div>
          <div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">Research with provenance</p><h1 className="mt-4 max-w-sm text-3xl font-semibold leading-tight">Keep every conclusion connected to its evidence.</h1><p className="mt-4 max-w-sm text-sm leading-6 text-slate-300">Search literature, track source changes, and inspect relationships between claims and passages.</p></div>
          <p className="text-xs text-slate-500">Evidence is a starting point for review, not a substitute for it.</p>
        </section>
        <section className="p-7 sm:p-10">
          <div className="mb-8 flex items-center gap-3 md:hidden"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-950 text-white"><History size={20}/></span><div><div className="font-semibold">chronicle.</div><div className="text-xs text-slate-500">Evidence intelligence</div></div></div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600">{authMode === "login" ? "Welcome back" : "Get started"}</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{authMode === "login" ? "Sign in to Chronicle" : "Create your account"}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">{authMode === "login" ? "Continue your research workspace." : "Save your research runs, sources, and evidence."}</p>
          <form className="mt-8 space-y-4" onSubmit={submitAuthentication}>
            <label className="block text-sm font-medium text-slate-700">Email address<input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-indigo-500" type="email" autoComplete="email" required value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="you@example.com"/></label>
            <label className="block text-sm font-medium text-slate-700">Password<input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-indigo-500" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={authMode === "register" ? 12 : 1} required value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder={authMode === "register" ? "At least 12 characters" : "Enter your password"}/></label>
            {authError ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{authError}</div> : null}
            <button disabled={authSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">{authSubmitting ? <LoaderCircle size={16} className="animate-spin"/> : null}{authSubmitting ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"}<ArrowRight size={16}/></button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-500">{authMode === "login" ? "New to Chronicle?" : "Already have an account?"} <button className="font-semibold text-indigo-600 hover:text-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setAuthError(""); }}>{authMode === "login" ? "Create an account" : "Sign in"}</button></p>
        </section>
      </div>
    </main>;
  }

  const viewSubtitle: Record<View, string> = {
    "Overview": "Your research, sources, and review activity.",
    "Research workspace": "Start a question or return to a saved run.",
    "Evidence graph": "Explore persisted papers, passages, studies, and claims.",
    "Source timeline": "Track updates that may change how evidence should be reviewed.",
    "Hypothesis lab": "Turn evidence gaps into candidate research questions."
  };

  return <div className="min-h-screen bg-slate-50 text-slate-900">
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200 bg-white px-4 py-5 lg:flex">
      <button onClick={() => setView("Overview")} className="flex items-center gap-3 rounded-xl px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-950 text-white"><History size={20}/></span>
        <span><span className="block font-semibold tracking-tight">chronicle.</span><span className="block text-xs text-slate-500">Evidence intelligence</span></span>
      </button>
      <div className="mt-9 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Workspace</div>
      <nav className="mt-3 space-y-1" aria-label="Main navigation">
        {NAV.map((item) => {
          const Icon = item.icon;
          return <button key={item.label} onClick={() => setView(item.label)} aria-current={view === item.label ? "page" : undefined} className={"flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 " + (view === item.label ? "bg-indigo-50 font-semibold text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950")}><Icon size={17}/><span>{item.label}</span>{item.label === "Source timeline" && sourceEvents.length > 0 ? <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-[10px]">{sourceEvents.length}</span> : null}</button>;
        })}
      </nav>
      <div className="mt-auto border-t border-slate-100 pt-4">
        <div className="flex items-center gap-3 px-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700">{authUser.email.slice(0, 1).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-800">{authUser.email}</span><span className="block text-[11px] text-slate-500">Personal workspace</span></span></div>
        <button onClick={signOut} className="mt-3 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-50 hover:text-slate-900"><LogOut size={16}/>Sign out</button>
      </div>
    </aside>

    <div className="lg:pl-64">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="flex min-h-[72px] items-center justify-between gap-4 px-4 sm:px-6 xl:px-8">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold tracking-tight">{view}</h1>
            <p className="hidden text-xs text-slate-500 sm:block">{viewSubtitle[view]}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden max-w-48 truncate rounded-full bg-slate-100 px-3 py-2 text-xs font-medium text-slate-600 xl:block">{authUser.email}</span>
            <button onClick={() => { setView("Research workspace"); setQuestion(""); }} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3.5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"><Plus size={16}/><span className="hidden sm:inline">New research</span><span className="sm:hidden">New</span></button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-3 py-2 lg:hidden" aria-label="Mobile navigation">
          {NAV.map((item) => {
            const Icon = item.icon;
            return <button key={item.label} onClick={() => setView(item.label)} aria-current={view === item.label ? "page" : undefined} className={"inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium " + (view === item.label ? "bg-indigo-50 text-indigo-700" : "text-slate-500 hover:bg-slate-50")}><Icon size={14}/>{item.label}</button>;
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-6 sm:px-6 xl:px-8">
        {notice ? <div role="status" aria-live="polite" className="flex items-start justify-between gap-3 rounded-xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-sm text-indigo-900"><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice("")} className="shrink-0 rounded p-0.5 text-indigo-700 hover:bg-indigo-100"><X size={16}/></button></div> : null}
        {workspaceError ? <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"><AlertCircle size={17} className="mt-0.5 shrink-0"/><span>{workspaceError}</span></div> : null}

        {view === "Overview" ? <div className="space-y-6">
          <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600">Workspace</p><h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Your research, at a glance.</h2></div>
            <button onClick={refreshWorkspace} disabled={workspaceLoading} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60"><RefreshCw size={15} className={workspaceLoading ? "animate-spin" : ""}/>Refresh</button>
          </section>
          <section className="grid gap-4 sm:grid-cols-3">
            {[
              { label: "Research runs", value: runs.length, hint: "Questions submitted", icon: Activity },
              { label: "Saved papers", value: papers.length, hint: "In your library", icon: BookOpen },
              { label: "Source events", value: sourceEvents.length, hint: "Updates recorded", icon: Clock3 }
            ].map((item) => {
              const Icon = item.icon;
              return <article key={item.label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><div className="flex items-center justify-between"><span className="text-sm font-medium text-slate-500">{item.label}</span><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Icon size={18}/></span></div><div className="mt-4 text-3xl font-semibold tracking-tight text-slate-950">{item.value}</div><p className="mt-1 text-xs text-slate-500">{item.hint}</p></article>;
            })}
          </section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
              <div><h3 className="text-sm font-semibold text-slate-900">Research workspaces</h3><p className="mt-1 text-xs leading-5 text-slate-500">Group questions and research runs by topic. Archived workspaces keep their history but cannot start new runs.</p></div>
              <button type="button" onClick={() => setShowArchivedProjects((value) => !value)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">{showArchivedProjects ? "Hide archived" : "Show archived"}</button>
            </div>
            <form onSubmit={submitNewProject} className="mt-4 grid gap-3 border-b border-slate-100 pb-4 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto]">
              <label className="block text-xs font-medium text-slate-700">Workspace title<input value={newProjectTitle} onChange={(event) => setNewProjectTitle(event.target.value)} minLength={2} maxLength={240} required placeholder="e.g. Major project literature" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/></label>
              <label className="block text-xs font-medium text-slate-700">Primary research question<input value={newProjectQuestion} onChange={(event) => setNewProjectQuestion(event.target.value)} minLength={8} maxLength={4000} required placeholder="What is the main question for this workspace?" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/></label>
              <button disabled={creatingProject} className="self-end rounded-lg bg-indigo-600 px-3.5 py-2.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{creatingProject ? "Creating…" : "Create workspace"}</button>
            </form>
            <div className="mt-3 space-y-2">
              {projects.filter((project) => showArchivedProjects || !project.archived_at).length === 0 ? <p className="rounded-lg bg-slate-50 p-4 text-xs text-slate-500">{showArchivedProjects ? "No workspaces found yet." : "No active workspaces yet. Create one above or run research without a workspace."}</p> : null}
              {projects.filter((project) => showArchivedProjects || !project.archived_at).map((project) => <article key={project.id} className="rounded-xl border border-slate-100 p-3">
                {editingProjectId === project.id ? <form onSubmit={saveEditedProject} className="grid gap-3 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto]">
                  <label className="block text-xs font-medium text-slate-700">Title<input value={editingProjectTitle} onChange={(event) => setEditingProjectTitle(event.target.value)} minLength={2} maxLength={240} required className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"/></label>
                  <label className="block text-xs font-medium text-slate-700">Research question<input value={editingProjectQuestion} onChange={(event) => setEditingProjectQuestion(event.target.value)} minLength={8} maxLength={4000} required className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"/></label>
                  <div className="flex items-end gap-2"><button disabled={savingProject} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{savingProject ? "Saving…" : "Save"}</button><button type="button" onClick={() => setEditingProjectId(null)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600">Cancel</button></div>
                </form> : <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                  <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold text-slate-900">{project.title}</h4>{project.archived_at ? <StatusPill status="archived">archived</StatusPill> : activeProjectId === project.id ? <StatusPill status="completed">selected</StatusPill> : null}</div><p className="mt-1 text-xs leading-5 text-slate-500">{project.research_question}</p></div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <button type="button" onClick={() => { setActiveProjectId(project.archived_at ? null : project.id); setView("Research workspace"); }} disabled={Boolean(project.archived_at)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40">Open</button>
                    {!project.archived_at ? <><button type="button" onClick={() => beginEditProject(project)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">Rename / edit</button><button type="button" disabled={savingProject} onClick={() => void setProjectArchived(project, true)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">Archive</button></> : <button type="button" disabled={savingProject} onClick={() => void setProjectArchived(project, false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50">Restore</button>}
                  </div>
                </div>}
              </article>)}
            </div>
          </section>
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/30">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h3 className="font-semibold text-slate-900">Recent research</h3><p className="mt-0.5 text-xs text-slate-500">Open a run to continue.</p></div><button onClick={() => setView("Research workspace")} className="inline-flex items-center gap-1.5 text-sm font-semibold text-indigo-600 hover:text-indigo-700">New run<ArrowRight size={15}/></button></div>
            {runsLoadingOrEmpty(workspaceLoading, runs) ? <div className="divide-y divide-slate-100">{[1, 2, 3].map((row) => <div key={row} className="animate-pulse px-5 py-4"><div className="h-3 w-2/3 rounded bg-slate-100"/><div className="mt-3 h-3 w-1/3 rounded bg-slate-100"/></div>)}</div> : null}
            {!workspaceLoading && runs.length === 0 ? <div className="p-4"><EmptyState icon={BookOpen} title="Start your first research run" description="Enter a question and Chronicle will collect source metadata for review." action={<button onClick={() => setView("Research workspace")} className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">Start research</button>}/></div> : null}
            {!workspaceLoading && runs.length > 0 ? <div className="divide-y divide-slate-100">{runs.slice(0, 6).map((run) => <button key={run.id} onClick={() => { setActiveRunId(run.id); setView("Research workspace"); }} className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-indigo-600"><span className="min-w-0"><span className="block truncate text-sm font-medium text-slate-900">{run.question}</span><span className="mt-1 block text-xs text-slate-500">{run.mode} · {formatDate(run.created_at)}{run.demo ? " · Request only" : ""}</span></span><span className="flex shrink-0 items-center gap-3"><StatusPill status={run.status}>{run.status}</StatusPill><ArrowRight size={15} className="text-slate-400"/></span></button>)}</div> : null}
          </section>
        </div> : null}

        {view === "Research workspace" ? <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-6">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30 sm:p-6">
              <div className="mb-5 flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-600">Research question</p><h2 className="mt-1.5 text-xl font-semibold tracking-tight">What do you want to investigate?</h2></div><span className="hidden rounded-xl bg-indigo-50 p-3 text-indigo-600 sm:flex"><Sparkles size={20}/></span></div>
              <form onSubmit={submitResearch} className="space-y-4">
                <label className="block text-sm font-medium text-slate-700">Workspace<select value={activeProjectId ?? ""} onChange={(event) => setActiveProjectId(event.target.value || null)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="">No workspace (standalone run)</option>{projects.filter((project) => !project.archived_at).map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
                <label className="block text-sm font-medium text-slate-700">Question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} required minLength={8} maxLength={2000} rows={4} placeholder="e.g. How does retrieval practice affect long-term learning outcomes?" className="mt-2 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 outline-none transition placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-indigo-500"/></label>
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px]">
                  <label className="block text-sm font-medium text-slate-700">Research mode<select value={researchMode} onChange={(event) => setResearchMode(event.target.value as ResearchMode)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">{MODES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                  <label className="block text-sm font-medium text-slate-700">Source limit<select value={maxSources} onChange={(event) => setMaxSources(Number(event.target.value))} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value={5}>5 sources</option><option value={10}>10 sources</option><option value={20}>20 sources</option><option value={30}>30 sources</option></select></label>
                </div>
                <p className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900">Provider disclosure: Chronicle sends the research query to scholarly metadata providers. When model-backed extraction or verification is run, selected source passages may be sent to the model provider configured by the server. Do not upload or process confidential or restricted material unless authorized.</p>
                <div className="flex flex-col-reverse justify-between gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center"><p className="text-xs leading-5 text-slate-500">Results remain reviewable; missing evidence is not proof of absence.</p><button disabled={creatingRun} className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">{creatingRun ? <LoaderCircle size={16} className="animate-spin"/> : <Sparkles size={16}/>} {creatingRun ? "Starting…" : "Start research"}</button></div>
              </form>
            </section>

            {activeRun ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30 sm:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Selected run</p><h3 className="mt-1.5 max-w-3xl text-lg font-semibold tracking-tight text-slate-950">{activeRun.question}</h3></div><StatusPill status={activeRun.status}>{activeRun.status}</StatusPill></div>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500"><span>{activeRun.mode} · up to {activeRun.max_sources} sources</span><span>{formatDate(activeRun.created_at)}</span><span className="font-mono">ID {activeRun.id.slice(0, 8)}</span></div>
              {activeRun.error_message ? <div role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{activeRun.error_message}</div> : null}
              {activeRun.status === "queued" || activeRun.status === "running" ? <div role="status" aria-live="polite" className="mt-5 rounded-xl bg-indigo-50 px-4 py-3"><div className="flex items-center gap-2 text-sm font-medium text-indigo-800"><LoaderCircle size={16} className="animate-spin"/> Research is in progress</div><p className="mt-1 text-xs text-indigo-700">This panel updates automatically.</p></div> : null}
              {activeRun.status === "completed" || activeRun.status === "completed_with_limitations" ? <div className="mt-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4"><div><p className="text-sm font-semibold text-slate-900">Research report</p><p className="mt-0.5 text-xs text-slate-500">{reportLoading ? "Loading latest report…" : activeReport ? "Latest saved version" : "No report version found for this run."}</p></div><div className="flex gap-2"><button disabled={!activeReport || exporting !== null} onClick={() => void exportPassport("markdown")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">{exporting === "markdown" ? "Exporting…" : "Export .md"}</button><button disabled={!activeReport || exporting !== null} onClick={() => void exportPassport("json")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">{exporting === "json" ? "Exporting…" : "Export .json"}</button></div></div>
                {activeReport ? <div className="max-h-[460px] overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 p-4 sm:p-5"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                  h1: ({ children }) => <h1 className="mb-3 mt-5 text-xl font-semibold text-slate-900 first:mt-0">{children}</h1>,
                  h2: ({ children }) => <h2 className="mb-2 mt-5 text-lg font-semibold text-slate-900">{children}</h2>,
                  h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold text-slate-900">{children}</h3>,
                  p: ({ children }) => <p className="mb-3 text-sm leading-6 text-slate-700">{children}</p>,
                  ul: ({ children }) => <ul className="mb-4 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">{children}</ul>,
                  ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1 pl-5 text-sm leading-6 text-slate-700">{children}</ol>,
                  a: ({ children, href }) => <a className="text-indigo-600 underline underline-offset-2" href={href} target="_blank" rel="noreferrer">{children}</a>,
                  blockquote: ({ children }) => <blockquote className="my-4 border-l-2 border-indigo-300 pl-4 text-sm text-slate-600">{children}</blockquote>
                }}>{activeReport.content_markdown}</ReactMarkdown></div> : <p className="text-sm text-slate-500">The run completed, but no report is available yet.</p>}
              </div> : null}
              <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-4"><button onClick={() => setView("Evidence graph")} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-3.5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"><Network size={15}/>Open evidence graph</button><button onClick={() => setView("Hypothesis lab")} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"><FlaskConical size={15}/>Hypothesis lab</button></div>
            </section> : <EmptyState icon={BookOpen} title="No selected research run" description="Start a question above or select a run from the list."/>}

            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/30">
              <button onClick={() => setShowAdvancedSourceSearch((current) => !current)} aria-expanded={showAdvancedSourceSearch} className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-slate-50"><span className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Search size={17}/></span><span><span className="block text-sm font-semibold text-slate-900">Discover papers</span><span className="mt-0.5 block text-xs text-slate-500">Search Crossref and OpenAlex, then save useful sources.</span></span></span><ChevronDown size={17} className={"shrink-0 text-slate-400 transition " + (showAdvancedSourceSearch ? "rotate-180" : "")}/></button>
              {showAdvancedSourceSearch ? <div className="border-t border-slate-100 p-5">
                <form onSubmit={(event) => { event.preventDefault(); void searchPapers(); }} className="flex flex-col gap-2 sm:flex-row"><input value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="Search by topic, title, or DOI" className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/><button disabled={sourceLoading} className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">{sourceLoading ? <LoaderCircle size={15} className="animate-spin"/> : <Search size={15}/>}Search</button></form>
                {sourceError ? <p role="status" className="mt-3 text-xs text-amber-700">{sourceError}</p> : null}
                {sourceResults.length ? <div className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-100">{sourceResults.map((paper) => { const key = paperKey(paper); const saved = savedPaperKeys.includes(key) || papers.some((item) => (paper.doi && item.doi?.toLowerCase() === paper.doi.toLowerCase()) || (paper.external_id && item.external_id === paper.external_id)); return <article key={key} className="flex flex-col justify-between gap-3 p-4 sm:flex-row"><div className="min-w-0"><h4 className="text-sm font-medium text-slate-900">{paper.title}</h4><p className="mt-1 text-xs text-slate-500">{(paper.authors ?? []).slice(0, 3).join(", ")}{paper.publication_year ? " · " + paper.publication_year : ""}{paper.publisher ? " · " + paper.publisher : ""}</p>{paper.doi ? <p className="mt-1 break-all text-[11px] text-slate-400">DOI: {paper.doi}</p> : null}</div><button onClick={() => void savePaper(paper)} disabled={saved} className="h-fit shrink-0 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-default disabled:bg-emerald-50 disabled:text-emerald-700">{saved ? "Saved" : "Save paper"}</button></article>; })}</div> : null}
              </div> : null}
            </section>
            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/30">
              <button onClick={() => setShowPdfUpload((current) => !current)} aria-expanded={showPdfUpload} className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-slate-50"><span className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 text-slate-700"><Upload size={17}/></span><span><span className="block text-sm font-semibold text-slate-900">Add a PDF</span><span className="mt-0.5 block text-xs text-slate-500">Extract text passages for evidence inspection.</span></span></span><ChevronDown size={17} className={"shrink-0 text-slate-400 transition " + (showPdfUpload ? "rotate-180" : "")}/></button>
              {showPdfUpload ? <div className="border-t border-slate-100 p-5"><label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center hover:border-indigo-300 hover:bg-indigo-50/40"><Upload size={20} className="text-slate-500"/><span className="mt-2 text-sm font-medium text-slate-800">{uploadingPdf ? "Uploading PDF…" : "Choose a PDF (server limit applies)"}</span><span className="mt-1 text-xs text-slate-500">The server validates size and page limits. Original files are stored on the configured server filesystem.</span><input className="sr-only" type="file" accept=".pdf,application/pdf" disabled={uploadingPdf} onChange={(event) => void handlePdfUpload(event.target.files?.[0])}/></label>{uploadMessage ? <p role="status" className="mt-3 text-sm text-slate-600">{uploadMessage}</p> : null}</div> : null}
            </section>
          </div>
          <aside className="space-y-5">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-slate-900">Recent runs</h3><span className="text-xs text-slate-400">{runs.length}</span></div><div className="mt-3 space-y-1">{runs.slice(0, 6).map((run) => <button key={run.id} onClick={() => setActiveRunId(run.id)} className={"w-full rounded-xl px-3 py-3 text-left transition " + (run.id === activeRunId ? "bg-indigo-50" : "hover:bg-slate-50")}><span className="block line-clamp-2 text-sm font-medium text-slate-800">{run.question}</span><span className="mt-2 flex items-center justify-between gap-2"><span className="text-[11px] text-slate-500">{formatDate(run.created_at)}</span><StatusPill status={run.status}>{run.status}</StatusPill></span></button>)}</div></section>
            <section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-white"><ShieldCheck size={20} className="text-indigo-300"/><h3 className="mt-3 text-sm font-semibold">Evidence-first by design</h3><p className="mt-2 text-xs leading-5 text-slate-300">Trace claims back to stored sources. Treat generated interpretations as candidates for review.</p></section>
          </aside>
        </div> : null}

        {view === "Evidence graph" ? <section className="space-y-4">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Evidence relationship map</h2><p className="mt-1 text-sm text-slate-500">Select a node to inspect its saved record.</p></div><div className="flex items-center gap-2"><label className="sr-only" htmlFor="graph-run">Research run</label><select id="graph-run" value={activeRunId ?? ""} onChange={(event) => { setActiveRunId(event.target.value || null); setSelectedGraphNodeId(null); }} className="min-w-0 max-w-64 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="">Choose a research run</option>{runs.map((run) => <option key={run.id} value={run.id}>{shorten(run.question, 58)}</option>)}</select><button aria-label="Refresh graph" onClick={() => void refreshGraph()} disabled={!activeRunId || graphLoading} className="rounded-xl border border-slate-200 bg-white p-2.5 text-slate-600 hover:bg-slate-50 disabled:opacity-50"><RefreshCw size={16} className={graphLoading ? "animate-spin" : ""}/></button></div></div>
          {!activeRunId ? <EmptyState icon={Network} title="Choose a research run" description="The graph uses saved source and claim records from a specific run." action={<button onClick={() => setView("Research workspace")} className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">Start research</button>}/> : null}
          {activeRunId && graphLoading && !graphSource ? <div role="status" aria-live="polite" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex items-center gap-2 text-sm font-medium text-slate-700"><LoaderCircle size={16} className="animate-spin text-indigo-600"/> Loading saved evidence…</div><div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">{[1, 2, 3, 4].map((item) => <div key={item} className="h-20 animate-pulse rounded-xl bg-slate-100"/> )}</div><div className="mt-4 h-80 animate-pulse rounded-xl bg-slate-50"/></div> : null}
          {activeRunId && graphError && !graphSource ? <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><p className="text-sm font-semibold text-rose-800">Could not load this graph</p><p className="mt-1 text-sm text-rose-700">{graphError}</p><button onClick={() => void refreshGraph()} className="mt-3 rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-700">Try again</button></div> : null}
          {activeRunId && graphSource && graphSource.nodes.length === 0 ? <EmptyState icon={Network} title="No saved evidence yet" description="This run has no persisted papers, passages, studies, or claims to draw. Completed discovery runs may populate source nodes first; claim links appear as they are saved." action={<button onClick={() => setView("Research workspace")} className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">View research run</button>}/> : null}
          {activeRunId && graphSource && graphSource.nodes.length > 0 ? <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_300px]">
            <section className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/30">
              <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center"><div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3 top-3 text-slate-400"/><input value={graphQuery} onChange={(event) => setGraphQuery(event.target.value)} placeholder="Find a paper, claim, or passage" className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/></div><label className="flex items-center gap-2 text-xs font-medium text-slate-500">Show<select value={graphType} onChange={(event) => setGraphType(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="all">All node types</option><option value="paper">Papers</option><option value="paper_version">Versions</option><option value="passage">Passages</option><option value="study">Studies</option><option value="claim">Claims</option></select></label></div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 px-4 py-3 text-xs text-slate-500"><span><strong className="text-slate-900">{graphSource.nodes.length}</strong> nodes</span><span><strong className="text-slate-900">{graphSource.edges.length}</strong> relationships</span><span><strong className="text-slate-900">{graphSource.nodes.filter((node) => node.type === "claim").length}</strong> claims</span>{graphLoading ? <span role="status" className="inline-flex items-center gap-1 text-indigo-600"><LoaderCircle size={13} className="animate-spin"/>Refreshing</span> : null}</div>
              {visibleNodes.length === 0 ? <div className="p-8 text-center"><Search size={20} className="mx-auto text-slate-400"/><p className="mt-2 text-sm font-medium text-slate-800">No matching nodes</p><p className="mt-1 text-xs text-slate-500">Change the search or node filter.</p></div> : <div className="graph-canvas max-h-[680px] overflow-auto">
                <svg viewBox={"0 0 960 " + graphLayout.height} className="block min-w-[960px] w-full" role="img" aria-label="Interactive map of persisted evidence relationships">
                  <defs><marker id="chronicle-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#9aa7bd"/></marker></defs>
                  {["Papers", "Versions", "Passages & studies", "Claims"].map((label, index) => <text key={label} x={[123, 361, 599, 837][index]} y="25" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.3" fill="#8591a6">{label.toUpperCase()}</text>)}
                  {graphLayout.lines.filter((line) => visibleGraphEdges.includes(line.edge)).map((line, index) => <g key={line.edge.id ?? (line.edge.source + "-" + line.edge.target + "-" + index)}><path d={line.path} fill="none" stroke={edgeColor(line.edge.type)} strokeWidth="1.8" strokeOpacity="0.78" markerEnd="url(#chronicle-arrow)"/>{graphLayout.lines.length < 18 ? <text x={line.labelX} y={line.labelY} textAnchor="middle" fontSize="10" fill="#64748b" paintOrder="stroke" stroke="#ffffff" strokeWidth="4" strokeLinejoin="round">{shorten(line.edge.type.replaceAll("_", " "), 24)}</text> : null}</g>)}
                  {graphLayout.placed.map(({ node, x, y }) => {
                    const selected = node.id === selectedGraphNodeId;
                    const lines = wrapSvgLabel(node.label);
                    const meta = node.type === "claim" ? (node.assessment ?? "unassessed").replaceAll("_", " ") : node.type === "passage" && node.page_number ? "Page " + node.page_number : node.publication_status?.replaceAll("_", " ") ?? "";
                    return <g key={node.id} role="button" tabIndex={0} aria-label={node.type + ": " + node.label} aria-pressed={selected} onClick={() => setSelectedGraphNodeId(node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedGraphNodeId(node.id); } }} className="cursor-pointer outline-none">
                      <rect x={x} y={y} width={graphLayout.nodeWidth} height={graphLayout.nodeHeight} rx="12" fill={selected ? "#eef2ff" : "#ffffff"} stroke={selected ? "#6366f1" : "#dbe2ee"} strokeWidth={selected ? "2.4" : "1.2"}/>
                      <text x={x + 12} y={y + 17} fontSize="9.5" fontWeight="700" letterSpacing=".5" fill={selected ? "#4f46e5" : "#64748b"}>{node.type.replaceAll("_", " ").toUpperCase()}</text>
                      <text x={x + 12} y={y + 38} fontSize="12" fontWeight="600" fill="#172033"><tspan x={x + 12} dy="0">{lines[0] ?? ""}</tspan>{lines[1] ? <tspan x={x + 12} dy="16">{lines[1]}</tspan> : null}</text>
                      {meta ? <text x={x + 12} y={y + 72} fontSize="9.5" fill="#64748b">{shorten(meta, 26)}</text> : null}
                    </g>;
                  })}
                </svg>
              </div>}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 px-4 py-3 text-[11px] text-slate-500"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500"/>Supports</span><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-rose-500"/>Contradicts</span><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-500"/>Qualifies / uncertain</span><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-500"/>Dependencies</span><span className="ml-auto hidden sm:inline">Only stored relationships are shown.</span></div>
              {graphSource.note ? <p className="px-4 pb-4 text-[11px] leading-5 text-slate-400">{graphSource.note}</p> : null}
            </section>
            <aside className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30">
              {selectedGraphNode ? <><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">Node details</span><StatusPill status={selectedGraphNode.type}>{selectedGraphNode.type.replaceAll("_", " ")}</StatusPill></div><h3 className="mt-3 break-words text-base font-semibold leading-6 text-slate-950">{selectedGraphNode.label}</h3>
                {selectedGraphNode.assessment ? <div className="mt-3"><StatusPill status={selectedGraphNode.assessment}>{selectedGraphNode.assessment.replaceAll("_", " ")}</StatusPill></div> : null}
                {selectedGraphNode.review_required ? <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">This claim needs human review.</p> : null}
                {selectedGraphNode.doi ? <p className="mt-4 break-all text-xs leading-5 text-slate-500">DOI: {selectedGraphNode.doi}</p> : null}
                {selectedGraphNode.page_number ? <p className="mt-3 text-xs text-slate-500">Page {selectedGraphNode.page_number}</p> : null}
                {selectedGraphNode.population ? <div className="mt-4"><p className="text-xs font-semibold text-slate-700">Population</p><p className="mt-1 text-sm leading-5 text-slate-600">{selectedGraphNode.population}</p></div> : null}
                {selectedGraphNode.method ? <div className="mt-4"><p className="text-xs font-semibold text-slate-700">Method</p><p className="mt-1 text-sm leading-5 text-slate-600">{selectedGraphNode.method}</p></div> : null}
                {selectedGraphNode.limitations?.length ? <div className="mt-4"><p className="text-xs font-semibold text-slate-700">Limitations</p><ul className="mt-1 list-disc space-y-1 pl-4 text-sm leading-5 text-slate-600">{selectedGraphNode.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
                <details className="mt-5 border-t border-slate-100 pt-3"><summary className="cursor-pointer text-xs font-medium text-slate-500">Record ID</summary><code className="mt-2 block break-all text-[10px] leading-4 text-slate-500">{selectedGraphNode.id}</code></details>
                {selectedGraphNode.type === "claim" ? <div className="mt-5 space-y-3">
                  <div className="grid grid-cols-1 gap-2">
                    <p className="text-xs leading-5 text-slate-500">Run a model-assisted comparison between this claim and its linked passages. The result is a review prompt, not proof of scientific truth.</p>
                    <button onClick={() => void verifyClaim(selectedGraphNode.id)} disabled={verifyingClaimId === selectedGraphNode.id} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
                      {verifyingClaimId === selectedGraphNode.id ? <><LoaderCircle size={14} className="animate-spin"/>Verifying citation support…</> : <><ShieldCheck size={14}/>Verify citation support</>}
                    </button>
                  </div>
                  {verificationByClaim[selectedGraphNode.id] ? <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-slate-900">Model-assisted assessment</p><StatusPill status={verificationByClaim[selectedGraphNode.id].verdict}>{verificationByClaim[selectedGraphNode.id].verdict.replaceAll("_", " ")}</StatusPill></div>
                    <p className="mt-2 text-sm leading-5 text-slate-700">{verificationByClaim[selectedGraphNode.id].rationale}</p>
                    {verificationByClaim[selectedGraphNode.id].context_note ? <p className="mt-2 text-xs leading-5 text-slate-600">Context: {verificationByClaim[selectedGraphNode.id].context_note}</p> : null}
                    {verificationByClaim[selectedGraphNode.id].evidence_passage_ids.length ? <p className="mt-2 break-words text-[11px] leading-5 text-slate-500">Evidence passage IDs: {verificationByClaim[selectedGraphNode.id].evidence_passage_ids.join(", ")}</p> : null}
                    {verificationByClaim[selectedGraphNode.id].uncertainty_notes.length ? <div className="mt-2"><p className="text-[11px] font-semibold text-slate-600">Uncertainty notes</p><ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">{verificationByClaim[selectedGraphNode.id].uncertainty_notes.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
                    <p className="mt-3 text-[11px] leading-5 text-amber-800">{verificationByClaim[selectedGraphNode.id].notice}</p>
                  </div> : null}
                  {visibleGraphEdges.filter((edge) => edge.id && (edge.source === selectedGraphNode.id || edge.target === selectedGraphNode.id) && edge.reviewer_status === "unreviewed").map((edge) => <div key={edge.id} className="rounded-xl border border-slate-100 p-3"><p className="text-xs font-medium text-slate-800">{edge.type.replaceAll("_", " ")}</p><p className="mt-1 text-[11px] text-slate-500">{shorten(graphSource.nodes.find((node) => node.id === (edge.source === selectedGraphNode.id ? edge.target : edge.source))?.label ?? "", 90)}</p><div className="mt-3 flex gap-2"><button disabled={reviewingRelationId === edge.id} onClick={() => void reviewRelation(edge.id as string, "accepted")} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">{reviewingRelationId === edge.id ? "Saving…" : "Accept"}</button><button disabled={reviewingRelationId === edge.id} onClick={() => void reviewRelation(edge.id as string, "needs_review")} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50">Needs review</button></div></div>)}
                </div> : null}
              </> : <div><Network size={20} className="text-slate-400"/><h3 className="mt-3 font-semibold text-slate-900">Select a node</h3><p className="mt-1 text-sm leading-5 text-slate-500">Its saved metadata and review state will appear here.</p></div>}
            </aside>
          </div> : null}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Potential source-dependence links</h3>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">Surface shared dataset or registry identifiers and near-duplicate abstracts. Suggestions are not saved until a researcher confirms them.</p>
              </div>
              <button onClick={() => void loadDependencyCandidates()} disabled={dependencyCandidatesLoading} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                {dependencyCandidatesLoading ? <LoaderCircle size={14} className="animate-spin"/> : <Search size={14}/>}
                {dependencyCandidatesLoading ? "Scanning sources…" : dependencyCandidatesLoaded ? "Refresh suggestions" : "Find dependency candidates"}
              </button>
            </div>
            {dependencyCandidateError ? <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{dependencyCandidateError}</p> : null}
            {dependencyCandidatesLoaded && dependencyCandidates.length === 0 && !dependencyCandidatesLoading ? <p className="mt-4 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">No candidates matched the current high-specificity heuristics. This does not prove the papers are independent.</p> : null}
            {dependencyCandidates.length > 0 ? <div className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-100">
              {dependencyCandidates.map((candidate) => <article key={candidate.id} className="flex flex-col justify-between gap-4 p-4 lg:flex-row lg:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill status="needs_review">{candidate.relation_type.replaceAll("_", " ")}</StatusPill>
                    <span className="text-[11px] text-slate-500">Heuristic signal · {Math.round(candidate.confidence * 100)}% score (not a calibrated probability)</span>
                  </div>
                  <p className="mt-2 break-words text-sm font-semibold leading-5 text-slate-900">{candidate.paper_a_title}</p>
                  <p className="my-1 text-[11px] font-medium text-slate-400">↔ possible shared evidence ↔</p>
                  <p className="break-words text-sm font-semibold leading-5 text-slate-900">{candidate.paper_b_title}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{candidate.rationale}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">{candidate.signals.map((signal) => <span key={signal} className="rounded-md bg-slate-100 px-2 py-1 text-[10px] text-slate-600">{signal.replaceAll("_", " ")}</span>)}</div>
                </div>
                <button onClick={() => void confirmDependencyCandidate(candidate)} disabled={savingDependencyCandidateId === candidate.id} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                  {savingDependencyCandidateId === candidate.id ? <LoaderCircle size={13} className="animate-spin"/> : <Check size={13}/>}
                  {savingDependencyCandidateId === candidate.id ? "Saving…" : "Confirm link"}
                </button>
              </article>)}
            </div> : null}
            <p className="mt-3 text-[11px] leading-5 text-slate-400">Confirmed shared-dataset and overlap links may flag both papers after a source event; the system does not automatically invalidate related claims.</p>
          </section>
        </section> : null}

        {view === "Source timeline" ? <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Source timeline</h2><p className="mt-1 text-sm text-slate-500">Updates are recorded for review; conclusions are never invalidated automatically.</p></div><button onClick={() => setEventFormOpen((current) => !current)} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3.5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"><Plus size={16}/>{eventFormOpen ? "Close form" : "Record event"}</button></div>
            {eventFormOpen ? <form onSubmit={submitSourceEvent} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30">
              <div className="grid gap-4 sm:grid-cols-2"><label className="block text-sm font-medium text-slate-700">Saved paper<select value={eventPaperId} onChange={(event) => setEventPaperId(event.target.value)} required className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="">Choose a paper</option>{papers.map((paper) => <option key={paper.id} value={paper.id}>{shorten(paper.title, 70)}</option>)}</select></label><label className="block text-sm font-medium text-slate-700">Event type<select value={eventType} onChange={(event) => setEventType(event.target.value as EventKind)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">{EVENT_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label></div>
              <label className="mt-4 block text-sm font-medium text-slate-700">Description<textarea value={eventDescription} onChange={(event) => setEventDescription(event.target.value)} minLength={8} required rows={3} placeholder="What changed, and where is the notice?" className="mt-2 w-full rounded-xl border border-slate-200 px-3.5 py-3 text-sm leading-6 outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/></label>
              <div className="mt-4 grid gap-4 sm:grid-cols-2"><label className="block text-sm font-medium text-slate-700">Source URL <span className="font-normal text-slate-400">(optional)</span><input type="url" value={eventSourceUrl} onChange={(event) => setEventSourceUrl(event.target.value)} placeholder="https://publisher.org/notice" className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"/></label><label className="block text-sm font-medium text-slate-700">Verification<select value={eventVerification} onChange={(event) => setEventVerification(event.target.value as Verification)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="unverified">Unverified</option><option value="metadata_confirmed">Metadata confirmed</option><option value="human_verified">Human verified</option></select></label></div>
              {timelineError ? <p role="alert" className="mt-3 text-sm text-rose-700">{timelineError}</p> : null}
              <div className="mt-5 flex justify-end"><button disabled={recordingEvent} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">{recordingEvent ? <LoaderCircle size={15} className="animate-spin"/> : <Check size={15}/>}Record source event</button></div>
            </form> : null}
            {sourceEvents.length === 0 ? <EmptyState icon={History} title="No source events yet" description="When a paper is corrected, retracted, or updated, record the notice here." action={<button onClick={() => { setView("Research workspace"); setShowAdvancedSourceSearch(true); }} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">Find papers first</button>}/> : <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/30"><div className="divide-y divide-slate-100">{sourceEvents.map((event) => <article key={event.id} className="flex gap-3 p-4 sm:p-5"><span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Clock3 size={17}/></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-slate-900">{event.event_type.replaceAll("_", " ")}</span><StatusPill status={event.verification_status}>{event.verification_status.replaceAll("_", " ")}</StatusPill></div><p className="mt-1 text-xs text-slate-500">{event.paper_title} · {formatDate(event.event_date ?? event.observed_at)}</p><p className="mt-2 text-sm leading-6 text-slate-700">{event.description}</p>{event.source_url ? <a className="mt-2 inline-block break-all text-xs font-medium text-indigo-600 hover:underline" href={event.source_url} target="_blank" rel="noreferrer">Open source notice ↗</a> : null}</div></article>)}</div></section>}
          </section>
          <aside className="space-y-4">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><h3 className="text-sm font-semibold text-slate-900">Check source status</h3><p className="mt-1 text-xs leading-5 text-slate-500">Compare public metadata before recording an event.</p><label className="mt-4 block text-xs font-medium text-slate-600">Paper<select value={eventPaperId} onChange={(event) => { setEventPaperId(event.target.value); setStatusCheck(null); }} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value="">Choose a paper</option>{papers.map((paper) => <option key={paper.id} value={paper.id}>{shorten(paper.title, 58)}</option>)}</select></label><button disabled={!eventPaperId || checkingStatus} onClick={() => void checkPaperStatus()} className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">{checkingStatus ? <LoaderCircle size={15} className="animate-spin"/> : <RefreshCw size={15}/>}Check external status</button>
              {statusCheck ? <div className="mt-4 rounded-xl bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-800">Latest check</p><p className="mt-1 text-xs text-slate-500">{statusCheck.signals.length} candidate signal(s) · {statusCheck.note}</p>{statusCheck.signals.slice(0, 3).map((signal, index) => <button key={index} onClick={() => { setEventType(signal.event_type); setEventDescription(signal.description); setEventSourceUrl(signal.source_url ?? ""); setEventVerification("unverified"); setEventFormOpen(true); }} className="mt-2 block w-full rounded-lg border border-slate-200 bg-white p-2.5 text-left text-xs leading-5 text-slate-700 hover:border-indigo-200">{shorten(signal.description, 110)}<span className="mt-1 block font-semibold text-indigo-600">Prepare event for review →</span></button>)}</div> : null}
            </section>
            {selectedPaper ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-900">Scheduled checks</h3><StatusPill status={selectedPaper.monitoring_enabled ? "completed" : "slate"}>{currentPaperStatus}</StatusPill></div><label className="mt-4 block text-xs font-medium text-slate-600">Check interval<select value={monitorIntervalMinutes} onChange={(event) => setMonitorIntervalMinutes(Number(event.target.value))} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"><option value={1440}>Daily</option><option value={720}>Every 12 hours</option><option value={360}>Every 6 hours</option><option value={60}>Hourly</option></select></label><button disabled={updatingMonitoring} onClick={() => void toggleMonitoring(!selectedPaper.monitoring_enabled)} className="mt-3 w-full rounded-xl bg-slate-950 px-3 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">{updatingMonitoring ? "Saving…" : selectedPaper.monitoring_enabled ? "Disable monitoring" : "Enable monitoring"}</button><p className="mt-2 text-[11px] leading-5 text-slate-400">Scheduled checks need the server-side monitoring workflow to run.</p></section> : <section className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="text-sm font-semibold text-slate-900">Build your source library</h3><p className="mt-1 text-xs leading-5 text-slate-500">Save a paper in Research workspace to enable status checks and timeline events.</p><button onClick={() => setView("Research workspace")} className="mt-3 text-sm font-semibold text-indigo-600">Discover papers →</button></section>}
            {statusChecks.length ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><h3 className="text-sm font-semibold text-slate-900">Recent checks</h3><div className="mt-3 space-y-3">{statusChecks.slice(0, 4).map((check) => <div key={check.id} className="border-l-2 border-slate-200 pl-3"><p className="text-xs font-medium text-slate-800">{shorten(check.paper_title, 70)}</p><p className="mt-1 text-[11px] text-slate-500">{formatDate(check.checked_at)} · {check.outcome.replaceAll("_", " ")}</p></div>)}</div></section> : null}
          </aside>
        </div> : null}

        {view === "Hypothesis lab" ? <section className="space-y-5">
          <div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Candidate research questions</h2><p className="mt-1 text-sm text-slate-500">Ideas to investigate further, not claims of novelty.</p></div>
          {!activeRunId ? <EmptyState icon={FlaskConical} title="Choose a research direction" description="Start or select a research run before reviewing candidate questions." action={<button onClick={() => setView("Research workspace")} className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">Start research</button>}/> : null}
          {activeRunId && !modelSynthesis ? <EmptyState icon={FlaskConical} title="No hypothesis synthesis yet" description={activeReport ? "This report has no model-generated question set." : "Complete a research run to load its report and candidate questions."} action={<button onClick={() => setView("Research workspace")} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">Open research workspace</button>}/> : null}
          {modelSynthesis ? <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-5">
              {modelSynthesis.executive_summary ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><h3 className="text-sm font-semibold text-slate-900">Evidence summary</h3><p className="mt-2 text-sm leading-6 text-slate-600">{modelSynthesis.executive_summary}</p></section> : null}
              {modelSynthesis.candidate_research_questions?.length ? <div className="grid gap-3 md:grid-cols-2">{modelSynthesis.candidate_research_questions.map((item, index) => <article key={item} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><div className="flex items-center justify-between"><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-700">Candidate {index + 1}</span><FlaskConical size={17} className="text-indigo-500"/></div><h3 className="mt-3 text-sm font-semibold leading-6 text-slate-900">{item}</h3></article>)}</div> : <EmptyState icon={FlaskConical} title="No candidate questions in this report" description="The current report did not produce a candidate question list."/>}
              {modelSynthesis.research_opportunities?.length ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30">
                <div><h3 className="text-sm font-semibold text-slate-900">Evidence-linked research opportunities</h3><p className="mt-1 text-xs leading-5 text-slate-500">Candidates are not novelty claims. Inspect the cited passages, search prior work, and test alternative explanations before proposing a contribution.</p></div>
                <div className="mt-3 space-y-3">{modelSynthesis.research_opportunities.map((opportunity, index) => <article key={opportunity.question + index} className="rounded-xl border border-slate-100 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2"><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-700">Opportunity {index + 1}</span><span className="text-[10px] font-medium text-amber-700">Prior-art review required</span></div>
                  <h4 className="mt-3 text-sm font-semibold leading-6 text-slate-900">{opportunity.question}</h4>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{opportunity.rationale}</p>
                  {opportunity.evidence_passage_ids?.length ? <div className="mt-3"><p className="text-[11px] font-semibold text-slate-700">Evidence passage IDs</p><p className="mt-1 break-all text-[11px] leading-5 text-slate-500">{opportunity.evidence_passage_ids.join(", ")}</p></div> : null}
                  {opportunity.prior_art_search_queries?.length ? <div className="mt-3"><p className="text-[11px] font-semibold text-slate-700">Suggested prior-art searches</p><ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">{opportunity.prior_art_search_queries.map((query) => <li key={query}>{query}</li>)}</ul></div> : null}
                  {opportunity.alternative_explanations?.length ? <div className="mt-3"><p className="text-[11px] font-semibold text-slate-700">Alternative explanations</p><ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">{opportunity.alternative_explanations.map((alternative) => <li key={alternative}>{alternative}</li>)}</ul></div> : null}
                  <div className="mt-3 rounded-lg bg-slate-50 p-3"><p className="text-[11px] font-semibold text-slate-700">Falsification plan</p><p className="mt-1 text-xs leading-5 text-slate-600">{opportunity.falsification_plan}</p></div>
                  <button onClick={() => { setQuestion(opportunity.prior_art_search_queries?.[0] ?? opportunity.question); setResearchMode("forensic"); setView("Research workspace"); }} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"><Search size={13}/>Investigate prior art</button>
                </article>)}</div>
              </section> : null}
              {modelSynthesis.disagreements?.length ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><h3 className="text-sm font-semibold text-slate-900">Evidence disagreements</h3><div className="mt-3 divide-y divide-slate-100">{modelSynthesis.disagreements.map((item, index) => <div key={index} className="py-3 first:pt-0 last:pb-0"><p className="text-sm leading-6 text-slate-700">{item.description}</p>{item.comparability_note ? <p className="mt-1 text-xs leading-5 text-slate-500">{item.comparability_note}</p> : null}</div>)}</div></section> : null}
            </div>
            <aside className="space-y-4"><section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-white"><Sparkles size={20} className="text-indigo-300"/><h3 className="mt-3 text-sm font-semibold">Review before asserting novelty</h3><p className="mt-2 text-xs leading-5 text-slate-300">Compare prior work, identify alternatives, and define what would falsify each candidate.</p></section>{modelSynthesis.limitations?.length ? <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/30"><h3 className="text-sm font-semibold text-slate-900">Limitations</h3><ul className="mt-3 list-disc space-y-2 pl-4 text-sm leading-5 text-slate-600">{modelSynthesis.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section> : null}{modelSynthesis.uncertainty_statement ? <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4"><p className="text-xs font-semibold text-amber-900">Uncertainty</p><p className="mt-1 text-sm leading-5 text-amber-800">{modelSynthesis.uncertainty_statement}</p></section> : null}</aside>
          </div> : null}
        </section> : null}

        {workspaceLoading ? <p role="status" className="sr-only">Refreshing workspace data.</p> : null}
      </main>
      <footer className="px-4 pb-7 pt-2 text-center text-[11px] text-slate-400 sm:px-6">Chronicle · Research records remain subject to human review.</footer>
    </div>
  </div>;
}

function runsLoadingOrEmpty(loading: boolean, runs: ResearchRun[]) {
  return loading && runs.length === 0;
}
