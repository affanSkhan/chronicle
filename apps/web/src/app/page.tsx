"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { checkPaperStatus, clearAccessToken, createResearchRun, createSourceEvent, downloadEvidencePassport, fetchCurrentUser, getEvidenceGraph, hasSavedAccessToken, importPaper, listLibraryPapers, listReportVersions, listResearchRuns, listRunAuditEvents, listSourceEvents, loginAccount, registerAccount, reviewEvidenceRelation, saveAccessToken, searchAcademicSources, uploadPdf, type AcademicSearchResult, type AuditEventRecord, type AuthUser, type EvidenceGraphResponse, type LibraryPaper, type PaperStatusCheck, type ReportVersionSummary, type ResearchMode as ApiResearchMode, type ResearchRun, type SourceEventRecord } from "@/lib/api";
import {
  Activity, ArrowRight, BookOpen, CircleHelp, Clock3, FileSearch, FlaskConical, GitBranch, GitCompare,
  History, LayoutDashboard, Microscope, Network, Plus, Search,
  ShieldCheck, Sparkles, Upload, Workflow, AlertTriangle, CircleDashed, LogOut
} from "lucide-react";

type View = "Overview" | "Research workspace" | "Evidence graph" | "Source timeline" | "Hypothesis lab";

const nav: { label: View; icon: typeof LayoutDashboard }[] = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Research workspace", icon: BookOpen },
  { label: "Evidence graph", icon: Network },
  { label: "Source timeline", icon: History },
  { label: "Hypothesis lab", icon: FlaskConical }
];

const demoClaims = [
  { id: "C-001", title: "The intervention improves measured learning outcomes", state: "Supported", evidence: 3, tone: "teal", summary: "Two independent study groups provide direct support; one paper is related to an existing dataset." },
  { id: "C-002", title: "The effect persists in unsupervised settings", state: "Needs review", evidence: 2, tone: "amber", summary: "Studies use different settings and outcomes. The evidence is not directly comparable yet." },
  { id: "C-003", title: "The approach generalizes across age groups", state: "Insufficient evidence", evidence: 1, tone: "slate", summary: "Only one eligible study was found for the target population in this sample." }
];

const timeline = [
  { date: "Today · 10:42", title: "Research run created", description: "A new question was submitted to the research planner.", kind: "run" },
  { date: "Today · 10:43", title: "3 candidate claims extracted", description: "Demo records created for the Evidence Ledger.", kind: "claim" },
  { date: "Today · 10:44", title: "Dependency review pending", description: "Source independence has not been verified by a real connector.", kind: "review" }
];

function StatusPill({ children, tone = "slate" }: { children: React.ReactNode; tone?: string }) {
  const styles: Record<string, string> = {
    teal: "bg-teal-50 text-teal-700 ring-teal-600/15",
    amber: "bg-amber-50 text-amber-800 ring-amber-600/15",
    blue: "bg-blue-50 text-blue-700 ring-blue-600/15",
    slate: "bg-slate-100 text-slate-600 ring-slate-500/10",
    red: "bg-red-50 text-red-700 ring-red-600/10"
  };
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${styles[tone] ?? styles.slate}`}>{children}</span>;
}

function Metric({ label, value, hint, icon: Icon }: { label: string; value: string; hint: string; icon: typeof Activity }) {
  return <div className="surface p-4">
    <div className="flex items-center justify-between"><span className="text-xs font-medium text-muted">{label}</span><span className="rounded-xl bg-paper p-2 text-accent"><Icon size={17}/></span></div>
    <div className="mt-4 text-2xl font-semibold tracking-tight">{value}</div>
    <div className="mt-1 text-xs text-muted">{hint}</div>
  </div>;
}

export default function HomePage() {
  const [view, setView] = useState<View>("Overview");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("Deep research");
  const [showNewRun, setShowNewRun] = useState(false);
  const [activeClaim, setActiveClaim] = useState("C-001");
  const [searchTerm, setSearchTerm] = useState("");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [currentReport, setCurrentReport] = useState<ReportVersionSummary | null>(null);
  const [reportVersions, setReportVersions] = useState<ReportVersionSummary[]>([]);
  const [compareReportId, setCompareReportId] = useState("");
  const [showVersionCompare, setShowVersionCompare] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEventRecord[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [graphData, setGraphData] = useState<EvidenceGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [libraryPapers, setLibraryPapers] = useState<LibraryPaper[]>([]);
  const [sourceEvents, setSourceEvents] = useState<SourceEventRecord[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState("");
  const [eventPaperId, setEventPaperId] = useState("");
  const [eventType, setEventType] = useState<"correction" | "retraction" | "expression_of_concern" | "new_version" | "metadata_change" | "conflicting_study">("retraction");
  const [eventDescription, setEventDescription] = useState("");
  const [eventSourceUrl, setEventSourceUrl] = useState("");
  const [eventVerification, setEventVerification] = useState<"unverified" | "metadata_confirmed" | "human_verified">("unverified");
  const [recordingEvent, setRecordingEvent] = useState(false);
  const [eventResult, setEventResult] = useState("");
  const [statusCheck, setStatusCheck] = useState<PaperStatusCheck | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [passportFormatLoading, setPassportFormatLoading] = useState<"markdown" | "json" | null>(null);
  const [passportError, setPassportError] = useState("");
  const [reviewingRelationId, setReviewingRelationId] = useState<string | null>(null);
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceResults, setSourceResults] = useState<AcademicSearchResult[]>([]);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [savingPaperKey, setSavingPaperKey] = useState("");
  const [savedPaperKeys, setSavedPaperKeys] = useState<string[]>([]);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const claims = useMemo(() => demoClaims.filter(c => (c.title + c.state).toLowerCase().includes(searchTerm.toLowerCase())), [searchTerm]);

  useEffect(() => {
    let cancelled = false;
    const restoreSession = async () => {
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
    };
    void restoreSession();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authUser) {
      setRuns([]);
      return;
    }
    let cancelled = false;
    const loadRuns = async () => {
      setRunsLoading(true);
      try {
        const latest = await listResearchRuns();
        if (!cancelled) setRuns(latest);
      } catch (error) {
        if (!cancelled) setNotice(error instanceof Error ? error.message : "Could not load saved research runs.");
      } finally {
        if (!cancelled) setRunsLoading(false);
      }
    };
    void loadRuns();
    return () => { cancelled = true; };
  }, [authUser]);

  useEffect(() => {
    if (view !== "Source timeline" || !authUser) return;
    let cancelled = false;
    const loadTimeline = async () => {
      setTimelineLoading(true);
      setTimelineError("");
      try {
        const [papers, events] = await Promise.all([listLibraryPapers(100), listSourceEvents(50)]);
        if (!cancelled) {
          setLibraryPapers(papers);
          setSourceEvents(events);
          setEventPaperId((current) => current || papers[0]?.id || "");
        }
      } catch (error) {
        if (!cancelled) setTimelineError(error instanceof Error ? error.message : "Could not load source lifecycle events.");
      } finally {
        if (!cancelled) setTimelineLoading(false);
      }
    };
    void loadTimeline();
    return () => { cancelled = true; };
  }, [view, authUser]);

  async function reviewGraphRelation(
    relationId: string,
    reviewerStatus: "accepted" | "rejected" | "needs_review"
  ) {
    setReviewingRelationId(relationId);
    setGraphError("");
    try {
      await reviewEvidenceRelation(
        relationId,
        reviewerStatus,
        reviewerStatus === "accepted" ? "Reviewed by researcher in Chronicle workspace." : "Researcher requested further review or rejected this relationship."
      );
      if (activeRunId) {
        const updatedGraph = await getEvidenceGraph(activeRunId);
        setGraphData(updatedGraph);
      }
      setNotice(reviewerStatus === "accepted" ? "Evidence relationship accepted and marked as human-reviewed." : "Evidence relationship marked for further review/rejected.");
    } catch (error) {
      setGraphError(error instanceof Error ? error.message : "Could not save the evidence review.");
    } finally {
      setReviewingRelationId(null);
    }
  }

  async function runPaperStatusCheck() {
    if (!eventPaperId) {
      setTimelineError("Select a saved paper before checking external metadata.");
      return;
    }
    setCheckingStatus(true);
    setTimelineError("");
    setStatusCheck(null);
    try {
      setStatusCheck(await checkPaperStatus(eventPaperId));
    } catch (error) {
      setTimelineError(error instanceof Error ? error.message : "Could not check external source metadata.");
    } finally {
      setCheckingStatus(false);
    }
  }

  function handleStatusSignal(signal: NonNullable<PaperStatusCheck["signals"]>[number]) {
    setEventPaperId(statusCheck?.paper_id ?? eventPaperId);
    setEventType(signal.event_type);
    setEventDescription(signal.description);
    setEventSourceUrl(signal.source_url ?? "");
    // A provider signal is a candidate. Leave it unverified until the researcher inspects the notice.
    setEventVerification("unverified");
    setEventResult("Candidate source signal loaded into the form. Verify the underlying notice before marking the event as confirmed.");
  }

  async function submitSourceEvent(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!eventPaperId) {
      setTimelineError("Import or upload a paper before recording a source event.");
      return;
    }
    if (eventDescription.trim().length < 8) {
      setTimelineError("Provide a source-event description of at least 8 characters.");
      return;
    }
    setRecordingEvent(true);
    setTimelineError("");
    setEventResult("");
    try {
      const result = await createSourceEvent({
        paperId: eventPaperId,
        event_type: eventType,
        description: eventDescription.trim(),
        source_url: eventSourceUrl.trim() || undefined,
        verification_status: eventVerification,
      });
      const impact = result.impact;
      setEventResult(`Event recorded. ${impact.claims_flagged_for_review} claim(s) and ${impact.report_versions_flagged_for_review} report version(s) flagged for review across ${impact.impacted_paper_ids.length} paper(s). ${result.event.verification_status === "unverified" ? "The event is unverified; the source status was not changed." : "The event was marked as verified according to the selected status."}`);
      setEventDescription("");
      const [papers, events] = await Promise.all([listLibraryPapers(100), listSourceEvents(50)]);
      setLibraryPapers(papers);
      setSourceEvents(events);
    } catch (error) {
      setTimelineError(error instanceof Error ? error.message : "Could not record the source event.");
    } finally {
      setRecordingEvent(false);
    }
  }

  useEffect(() => {
    if (!activeRunId || !authUser) {
      setAuditEvents([]);
      return;
    }
    let cancelled = false;
    const loadAudit = async () => {
      setAuditLoading(true);
      setAuditError("");
      try {
        const events = await listRunAuditEvents(activeRunId, 100);
        if (!cancelled) setAuditEvents(events);
      } catch (error) {
        if (!cancelled) setAuditError(error instanceof Error ? error.message : "Could not load audit history.");
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    };
    void loadAudit();
    return () => { cancelled = true; };
  }, [activeRunId, authUser]);

  useEffect(() => {
    if (view !== "Evidence graph" || !activeRunId || !authUser) {
      setGraphData(null);
      setGraphError("");
      return;
    }
    let cancelled = false;
    const loadGraph = async () => {
      setGraphLoading(true);
      setGraphError("");
      try {
        const graph = await getEvidenceGraph(activeRunId);
        if (!cancelled) setGraphData(graph);
      } catch (error) {
        if (!cancelled) setGraphError(error instanceof Error ? error.message : "Could not load the persisted evidence graph.");
      } finally {
        if (!cancelled) setGraphLoading(false);
      }
    };
    void loadGraph();
    return () => { cancelled = true; };
  }, [view, activeRunId, authUser]);

  useEffect(() => {
    if (!activeRunId || !authUser) return;
    let cancelled = false;
    const pollRun = async () => {
      try {
        const latestRuns = await listResearchRuns();
        if (cancelled) return;
        setRuns(latestRuns);
        const active = latestRuns.find((run) => run.id === activeRunId);
        if (active?.status === "completed") {
          setReportLoading(true);
          try {
            const reports = await listReportVersions(activeRunId);
            if (!cancelled) {
              setReportVersions(reports);
              setCurrentReport(reports[0] ?? null);
              setCompareReportId(reports.find((report) => report.id !== reports[0]?.id)?.id ?? "");
            }
          } catch (error) {
            if (!cancelled) setNotice(error instanceof Error ? error.message : "The report was completed but could not be loaded.");
          } finally {
            if (!cancelled) setReportLoading(false);
          }
          if (timer) clearInterval(timer);
          setNotice("Academic discovery completed. Review the report and inspect its source metadata; any extracted claims remain unreviewed.");
        } else if (active?.status === "failed") {
          if (timer) clearInterval(timer);
          setNotice(active.error_message ?? "The research run failed. Review the API status and server logs.");
        }
      } catch {
        if (!cancelled) setNotice("Could not refresh this research run. Check the API connection.");
      }
    };
    const timer = setInterval(() => { void pollRun(); }, 4000);
    void pollRun();
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [activeRunId, authUser]);


  async function refreshRuns() {
    setRunsLoading(true);
    try {
      const latest = await listResearchRuns();
      setRuns(latest);
    } catch {
      // Keep demo UI usable if the API is offline; show the connection error in the workspace.
    } finally {
      setRunsLoading(false);
    }
  }

  async function runAcademicSearch() {
    if (sourceQuery.trim().length < 3) {
      setSourceError("Enter at least three characters for an academic search.");
      return;
    }
    setSourceLoading(true);
    setSourceError("");
    try {
      const result = await searchAcademicSources(sourceQuery.trim(), 10, "all");
      setSourceResults(result.results);
      const failedProviders = Object.keys(result.provider_errors ?? {});
      if (failedProviders.length) {
        setSourceError(`Partial results: ${failedProviders.join(", ")} could not be reached.`);
      }
      if (!result.results.length && !failedProviders.length) {
        setSourceError("No metadata results were returned for this query.");
      }
    } catch (error) {
      setSourceResults([]);
      setSourceError(error instanceof Error ? error.message : "Academic search failed. Check the API connection.");
    } finally {
      setSourceLoading(false);
    }
  }

  function paperKey(paper: AcademicSearchResult) {
    return (paper.doi ? `doi:${paper.doi.toLowerCase()}` : paper.external_id || paper.title).toLowerCase();
  }

  async function savePaper(paper: AcademicSearchResult) {
    const key = paperKey(paper);
    setSavingPaperKey(key);
    setSourceError("");
    try {
      await importPaper(paper);
      setSavedPaperKeys((current) => current.includes(key) ? current : [...current, key]);
      setNotice(`Saved "${paper.title}" to the paper library.`);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : "Paper could not be imported.");
    } finally {
      setSavingPaperKey("");
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
      const result = await uploadPdf(file);
      setUploadMessage(result.duplicate_upload
        ? `This PDF is already in the library: ${result.title}.`
        : `Added ${result.title}: ${result.page_count} pages and ${result.passages_created} evidence passages extracted. Claims have not been verified.`);
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "PDF upload failed.");
    } finally {
      setUploadingPdf(false);
    }
  }


  const activeSynthesis = useMemo(() => {
    const raw = currentReport?.evidence_snapshot?.model_synthesis;
    if (!raw || typeof raw !== "object") return null;
    return raw as {
      executive_summary?: string;
      findings?: { statement: string; evidence_passage_ids?: string[]; relation_type?: string; context_note?: string | null }[];
      disagreements?: { description: string; evidence_passage_ids?: string[]; comparability_note?: string | null }[];
      limitations?: string[];
      candidate_research_questions?: string[];
      uncertainty_statement?: string;
      human_review_required?: boolean;
    };
  }, [currentReport]);

  const latestReport = reportVersions[0] ?? currentReport;
  const comparedReport = reportVersions.find((report) => report.id === compareReportId) ?? null;
  const versionDiff = useMemo(() => {
    if (!showVersionCompare || !latestReport || !comparedReport || latestReport.id === comparedReport.id) return [];
    const oldLines = comparedReport.content_markdown.split("\n");
    const newLines = latestReport.content_markdown.split("\n");
    const oldSet = new Set(oldLines);
    const newSet = new Set(newLines);
    const rows: { kind: "removed" | "added" | "unchanged"; text: string }[] = [];
    for (const line of oldLines) {
      if (!newSet.has(line)) rows.push({ kind: "removed", text: line });
    }
    for (const line of newLines) {
      if (!oldSet.has(line)) rows.push({ kind: "added", text: line });
    }
    if (!rows.length) rows.push({ kind: "unchanged", text: "No line-level text changes detected." });
    return rows;
  }, [showVersionCompare, latestReport, comparedReport]);

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
      setAuthMode("login");
      setNotice(authMode === "register" ? "Account created. Your research records are private to this account." : "Signed in successfully.");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Could not authenticate. Check your connection and credentials.");
    } finally {
      setAuthSubmitting(false);
      setAuthLoading(false);
    }
  }

  function signOut() {
    clearAccessToken();
    setAuthUser(null);
    setActiveRunId(null);
    setCurrentReport(null);
    setReportVersions([]);
    setCompareReportId("");
    setShowVersionCompare(false);
    setGraphData(null);
    setGraphError("");
    setAuditEvents([]);
    setAuditError("");
    setRuns([]);
    setSourceEvents([]);
    setLibraryPapers([]);
    setSourceResults([]);
    setSourceQuery("");
    setSourceError("");
    setSavedPaperKeys([]);
    setUploadMessage("");
    setEventPaperId("");
    setEventDescription("");
    setEventSourceUrl("");
    setEventVerification("unverified");
    setEventResult("");
    setStatusCheck(null);
    setTimelineError("");
    setPassportError("");
    setQuery("");
    setNotice("");
    setView("Overview");
  }

  async function exportPassport(format: "markdown" | "json") {
    if (!activeRunId) return;
    setPassportFormatLoading(format);
    setPassportError("");
    try {
      await downloadEvidencePassport(activeRunId, format);
    } catch (error) {
      setPassportError(error instanceof Error ? error.message : "Evidence Passport export failed.");
    } finally {
      setPassportFormatLoading(null);
    }
  }

  async function openResearchRun(runId: string) {
    setActiveRunId(runId);
    setCurrentReport(null);
    setView("Research workspace");
    setReportLoading(true);
    try {
      const reports = await listReportVersions(runId);
      setReportVersions(reports);
      setCurrentReport(reports[0] ?? null);
      setCompareReportId(reports.find((report) => report.id !== reports[0]?.id)?.id ?? "");
      setShowVersionCompare(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load this research run.");
    } finally {
      setReportLoading(false);
    }
  }

  async function startResearch() {
    if (!query.trim()) {
      setNotice("Enter a research question to create a run.");
      return;
    }
    setSubmitting(true);
    setNotice("");
    try {
      const modes: Record<string, ApiResearchMode> = {
        "Quick scan": "quick",
        "Deep research": "deep",
        "Academic review": "academic",
        "Forensic analysis": "forensic"
      };
      const created = await createResearchRun({
        question: query.trim(),
        mode: modes[mode] ?? "deep",
        max_sources: 10,
        execute: true
      });
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setActiveRunId(created.id);
      setCurrentReport(null);
      setReportVersions([]);
      setCompareReportId("");
      setShowVersionCompare(false);
      setView("Research workspace");
      setNotice(`Run ${created.id.slice(0, 8)} submitted. Searching Crossref/OpenAlex and building an academic discovery snapshot…`);
      setShowNewRun(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not reach the Chronicle API. Check that the API is running.");
    } finally {
      setSubmitting(false);
    }
  }

  if (authLoading) {
    return <main className="flex min-h-screen items-center justify-center bg-paper p-6"><div className="rounded-2xl border border-line bg-white px-8 py-7 text-center shadow-sm"><div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-white"><History size={22}/></div><p className="mt-4 text-sm font-semibold">Opening your Chronicle workspace…</p><p className="mt-1 text-xs text-muted">Restoring your private session</p></div></main>;
  }

  if (!authUser) {
    return <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-100 via-paper to-paper p-4 md:p-8">
      <section className="grid w-full max-w-4xl overflow-hidden rounded-3xl border border-line bg-white shadow-xl md:grid-cols-[0.95fr_1.05fr]">
        <div className="flex flex-col justify-between bg-ink p-7 text-white md:p-9">
          <div><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/10"><History size={22}/></div><div><div className="text-lg font-semibold">chronicle<span className="text-indigo-300">.</span></div><div className="text-[11px] text-slate-300">Temporal evidence intelligence</div></div></div>
            <div className="mt-12"><div className="eyebrow text-indigo-200">Multi-agent research assistant</div><h1 className="mt-3 text-3xl font-semibold leading-tight">Make every conclusion traceable.</h1><p className="mt-4 text-sm leading-6 text-slate-300">Discover scholarly sources, connect claims to passages, inspect source lineage and keep track of evidence changes over time.</p></div>
          </div>
          <div className="mt-10 rounded-2xl border border-white/10 bg-white/5 p-4"><div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={16}/> Private research workspace</div><p className="mt-2 text-xs leading-5 text-slate-300">Your saved papers, runs, reports and uploaded documents are scoped to your account. This research prototype does not guarantee scientific truth and still requires human review.</p></div>
        </div>
        <div className="p-7 md:p-9">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">{authMode === "login" ? "Welcome back" : "Get started"}</div>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">{authMode === "login" ? "Sign in to Chronicle" : "Create your account"}</h2>
          <p className="mt-2 text-sm leading-6 text-muted">{authMode === "login" ? "Continue to your private research projects and evidence ledger." : "Create an account to save and revisit your research."}</p>
          <form onSubmit={submitAuthentication} className="mt-7 space-y-4">
            <label className="block text-xs font-semibold">Email address<input type="email" required autoComplete="email" value={authEmail} onChange={(event)=>setAuthEmail(event.target.value)} className="field mt-1.5" placeholder="you@university.edu"/></label>
            <label className="block text-xs font-semibold">Password<input type="password" required minLength={authMode === "register" ? 12 : 1} maxLength={128} autoComplete={authMode === "login" ? "current-password" : "new-password"} value={authPassword} onChange={(event)=>setAuthPassword(event.target.value)} className="field mt-1.5" placeholder={authMode === "register" ? "At least 12 characters" : "Enter your password"}/></label>
            {authError && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">{authError}</div>}
            <button type="submit" disabled={authSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50">{authSubmitting ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"} <ArrowRight size={15}/></button>
          </form>
          <div className="mt-5 text-center text-xs text-muted">{authMode === "login" ? "New to Chronicle?" : "Already have an account?"} <button onClick={()=>{setAuthMode((mode)=>mode==="login"?"register":"login");setAuthError("");}} className="font-semibold text-accent hover:underline">{authMode === "login" ? "Create an account" : "Sign in"}</button></div>
          <p className="mt-6 text-[10px] leading-5 text-muted">Use a unique password. Provider credentials are managed on the server. Reported findings and hypotheses remain research aids for human review.</p>
        </div>
      </section>
    </main>;
  }

  return <div className="min-h-screen bg-paper text-ink">
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-[248px] flex-col border-r border-line bg-white px-4 py-5 lg:flex">
      <div className="flex items-center gap-3 px-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-ink text-white"><History size={21}/></div>
        <div><div className="font-semibold tracking-tight">chronicle<span className="text-accent">.</span></div><div className="text-[11px] text-muted">Evidence intelligence</div></div>
      </div>
      <div className="mt-9 px-2 eyebrow">Workspace</div>
      <nav className="mt-3 space-y-1">{nav.map(item => <button key={item.label} onClick={() => setView(item.label)} className={`nav-item w-full text-left ${view === item.label ? "nav-item-active" : ""}`}><item.icon size={17}/><span>{item.label}</span>{item.label === "Source timeline" && <span className="ml-auto rounded-md bg-paper px-1.5 py-0.5 text-[10px]">NEW</span>}</button>)}</nav>
      <div className="mt-9 px-2 eyebrow">Saved research</div>
      <button onClick={() => {setView("Research workspace"); setQuery("How does AI-assisted learning affect student outcomes?");}} className="mt-3 flex items-start gap-3 rounded-xl p-3 text-left hover:bg-paper"><BookOpen size={17} className="mt-0.5 shrink-0 text-muted"/><span className="text-xs leading-5 text-slate-600">AI-assisted learning outcomes<span className="mt-1 block text-[10px] text-muted">Demo project · 3 claims</span></span></button>
      <div className="mt-auto rounded-2xl bg-ink p-4 text-white">
        <div className="flex items-center gap-2 text-sm font-medium"><Sparkles size={16}/> Built for explainable research</div>
        <p className="mt-2 text-xs leading-5 text-slate-300">Follow a claim from a report back to the source passage and track why its assessment may change.</p>
        <button onClick={() => setView("Evidence graph")} className="mt-3 flex items-center gap-2 text-xs font-semibold text-white hover:text-indigo-200">Explore evidence graph <ArrowRight size={14}/></button>
      </div>
    </aside>

    <main className="min-h-screen lg:pl-[248px]">
      <header className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-line bg-white/90 px-5 backdrop-blur md:px-8">
        <div><div className="text-sm font-semibold">{view}</div><div className="mt-0.5 text-[11px] text-muted">Temporal Evidence Intelligence <span className="mx-1">/</span> Prototype</div></div>
        <div className="flex items-center gap-2"><span className="hidden max-w-[180px] truncate rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-medium text-slate-700 sm:inline-flex" title={authUser.email}>{authUser.email}</span><button onClick={signOut} className="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-2.5 text-xs font-semibold hover:bg-paper" aria-label="Sign out"><LogOut size={14}/><span className="hidden sm:inline">Sign out</span></button><button onClick={() => setShowNewRun(true)} className="inline-flex items-center gap-2 rounded-xl bg-accent px-3.5 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700"><Plus size={15}/> New research</button></div>
      </header>

      <div className="mx-auto max-w-[1500px] px-5 py-7 md:px-8">
        {notice && <div role="status" className="mb-5 flex items-start justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900"><span>{notice}</span><button className="text-xs font-semibold" onClick={() => setNotice("")}>Dismiss</button></div>}

        {view === "Overview" && <>
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><div className="eyebrow">Research command center</div><h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">A clearer trail from evidence to conclusion.</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Explore a research workspace built to keep claims inspectable, source dependencies visible, and evidence changes accountable.</p></div><button onClick={() => setShowNewRun(true)} className="inline-flex w-fit items-center gap-2 rounded-xl border border-line bg-white px-4 py-2.5 text-sm font-semibold shadow-sm hover:bg-slate-50"><Plus size={16}/> Start a research run</button></div>
          <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Research runs" value={String(runs.length).padStart(2, "0")} hint={runsLoading ? "Refreshing API runs…" : "API-backed demo run requests"} icon={Workflow}/><Metric label="Claims in ledger" value="03" hint="Illustrative demo records" icon={ShieldCheck}/><Metric label="Evidence relations" value="06" hint="Not verified against live sources" icon={GitBranch}/><Metric label="Source updates" value="00" hint="External monitoring not connected" icon={Clock3}/></div>
          <div className="mt-7 grid gap-5 2xl:grid-cols-[1.25fr_0.75fr]">
            <section className="surface overflow-hidden"><div className="flex items-center justify-between border-b border-line px-5 py-4"><div><div className="font-semibold">Evidence ledger</div><div className="mt-1 text-xs text-muted">Example claims and their review states</div></div><button onClick={() => setView("Research workspace")} className="text-xs font-semibold text-accent">Open ledger <ArrowRight size={13} className="ml-1 inline"/></button></div><div className="divide-y divide-line">{demoClaims.map(c => <button key={c.id} onClick={() => {setActiveClaim(c.id); setView("Research workspace");}} className="flex w-full items-start gap-4 px-5 py-4 text-left transition hover:bg-slate-50"><div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-paper text-muted"><FileSearch size={17}/></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-[10px] font-semibold tracking-wide text-muted">{c.id}</span><StatusPill tone={c.tone}>{c.state}</StatusPill></div><div className="mt-1.5 text-sm font-semibold">{c.title}</div><div className="mt-1 text-xs leading-5 text-muted">{c.summary}</div></div><div className="shrink-0 text-right"><div className="text-sm font-semibold">{c.evidence}</div><div className="text-[10px] text-muted">evidence links</div></div></button>)}</div><div className="bg-paper px-5 py-3 text-[11px] text-muted">Illustrative sample only. The prototype has not yet retrieved or verified these findings.</div></section>
            <section className="surface p-5"><div className="flex items-center justify-between"><div><div className="font-semibold">Research activity</div><div className="mt-1 text-xs text-muted">Events in the demo workspace</div></div><Activity size={18} className="text-muted"/></div><div className="mt-6 space-y-5">{timeline.map((item,i)=><div key={item.title} className="flex gap-3"><div className="flex flex-col items-center"><div className={`flex h-8 w-8 items-center justify-center rounded-xl ${item.kind === "review" ? "bg-amber-50 text-amber-700" : "bg-accent-soft text-accent"}`}>{item.kind === "run" ? <Workflow size={15}/> : item.kind === "claim" ? <ShieldCheck size={15}/> : <CircleDashed size={15}/>}</div>{i < timeline.length-1 && <div className="mt-2 h-8 w-px bg-line"/>}</div><div><div className="text-[10px] font-medium text-muted">{item.date}</div><div className="mt-1 text-sm font-semibold">{item.title}</div><div className="mt-1 text-xs leading-5 text-muted">{item.description}</div></div></div>)}</div><button onClick={() => setView("Source timeline")} className="mt-6 flex items-center gap-2 text-xs font-semibold text-accent">Open source timeline <ArrowRight size={14}/></button></section>
          </div>
<section className="surface mt-5 overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div><div className="font-semibold">Research runs</div><div className="mt-1 text-xs text-muted">Stored by the API process (demo storage resets on restart)</div></div>
              <button onClick={refreshRuns} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold hover:bg-paper" disabled={runsLoading}>{runsLoading ? "Refreshing…" : "Refresh"}</button>
            </div>
            {runs.length === 0 ? <div className="px-5 py-6 text-sm text-muted">No API-backed runs loaded yet. Open this workspace and create a research run to verify the backend connection.</div> :
            <div className="divide-y divide-line">{runs.map((run) => <div key={run.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <div className="min-w-0"><div className="text-sm font-medium">{run.question}</div><div className="mt-1 text-[11px] text-muted">{run.id.slice(0, 8)} · {new Date(run.created_at).toLocaleString()}</div></div>
              <div className="flex items-center gap-2"><StatusPill tone="blue">{run.mode}</StatusPill><StatusPill tone={run.status==="completed"?"teal":run.status==="failed"?"red":"amber"}>{run.status}</StatusPill><button onClick={()=>{void openResearchRun(run.id);}} className="rounded-lg border border-line px-3 py-1.5 text-[11px] font-semibold hover:bg-paper">{run.status==="completed"?"Open report":"Open run"}</button></div>
            </div>)}</div>}
          </section>
          <div className="mt-5 grid gap-4 xl:grid-cols-3"><div className="surface p-5"><div className="flex items-center gap-2 text-sm font-semibold"><Network size={17} className="text-accent"/> Evidence graph</div><p className="mt-2 text-xs leading-5 text-muted">Trace a conclusion through claims and passages. Model-inferred edges will be labelled separately.</p><button onClick={() => setView("Evidence graph")} className="mt-4 text-xs font-semibold text-accent">Explore graph →</button></div><div className="surface p-5"><div className="flex items-center gap-2 text-sm font-semibold"><History size={17} className="text-accent"/> Temporal intelligence</div><p className="mt-2 text-xs leading-5 text-muted">Future source events will trigger targeted reassessment, preserving previous report versions.</p><button onClick={() => setView("Source timeline")} className="mt-4 text-xs font-semibold text-accent">View timeline →</button></div><div className="surface p-5"><div className="flex items-center gap-2 text-sm font-semibold"><FlaskConical size={17} className="text-accent"/> Hypothesis lab</div><p className="mt-2 text-xs leading-5 text-muted">Candidate research opportunities will be grounded in retrieved literature and marked as hypotheses, not discoveries.</p><button onClick={() => setView("Hypothesis lab")} className="mt-4 text-xs font-semibold text-accent">Open lab →</button></div></div>
        </>}

        {view === "Research workspace" && <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(310px,0.8fr)]"><section className="surface p-5 md:p-6"><div className="flex items-center justify-between"><div><div className="eyebrow">Research workspace</div><h1 className="mt-2 max-w-2xl text-xl font-semibold">{activeRunId ? (runs.find((run) => run.id === activeRunId)?.question ?? "Research workspace") : "AI-assisted learning outcomes"}</h1><p className="mt-1 text-xs text-muted">{activeRunId ? "Active research request · live metadata discovery" : "Example project · sample claims below are illustrative"}</p></div>{activeRunId ? <StatusPill tone={runs.find((run) => run.id === activeRunId)?.status === "completed" ? "teal" : runs.find((run) => run.id === activeRunId)?.status === "failed" ? "red" : "amber"}>{runs.find((run) => run.id === activeRunId)?.status ?? "queued"}</StatusPill> : <StatusPill tone="amber">Demo data</StatusPill>}</div><div className="mt-6 flex flex-wrap gap-2">{["Overview","Claims","Evidence","Limitations"].map(tab=><button key={tab} onClick={()=>setNotice(`${tab} section is represented by the current demo data; live retrieval is not connected.`)} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold hover:bg-paper">{tab}</button>)}</div><div className="mt-5"><label className="text-xs font-semibold">Research question</label><textarea value={query} onChange={e=>setQuery(e.target.value)} rows={3} placeholder="Ask a focused scientific question..." className="field mt-2 resize-y"/><div className="mt-3 flex flex-wrap items-center justify-between gap-3"><label className="text-xs text-muted">Research mode <select value={mode} onChange={e=>setMode(e.target.value)} className="ml-2 rounded-lg border border-line bg-white px-2 py-1.5 text-xs text-ink"><option>Quick scan</option><option>Deep research</option><option>Academic review</option><option>Forensic analysis</option></select></label><button onClick={startResearch} disabled={submitting} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50"><Sparkles size={14}/> {submitting ? "Creating..." : "Create run"}</button></div></div>
          {activeRunId && <section className="mt-5 rounded-2xl border border-line bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><div className="text-sm font-semibold">Research run status</div><div className="mt-1 text-xs text-muted">Run ID {activeRunId.slice(0, 8)} · status is refreshed automatically</div></div>
              <div className="flex items-center gap-2"><StatusPill tone={runs.find((run) => run.id === activeRunId)?.status === "completed" ? "teal" : runs.find((run) => run.id === activeRunId)?.status === "failed" ? "red" : "amber"}>{runs.find((run) => run.id === activeRunId)?.status ?? "queued"}</StatusPill><button onClick={() => { setActiveRunId(null); setCurrentReport(null); }} className="rounded-lg border border-line px-2.5 py-1.5 text-[11px] font-semibold hover:bg-paper">Clear</button></div>
            </div>
            {runs.find((run) => run.id === activeRunId)?.status === "running" || runs.find((run) => run.id === activeRunId)?.status === "queued" ? <p className="mt-3 text-xs leading-5 text-muted">Searching scholarly metadata, saving paper versions and abstract passages, and preparing a versioned discovery snapshot. This can take a short while.</p> : null}
            {runs.find((run) => run.id === activeRunId)?.error_message && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-800">{runs.find((run) => run.id === activeRunId)?.error_message}</p>}
          </section>}
          {activeRunId && <section className="mt-5 overflow-hidden rounded-2xl border border-line bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div><div className="text-sm font-semibold">Review & audit history</div><div className="mt-1 text-xs text-muted">Material changes with actor, timestamp, before/after state, and reason</div></div>
              <button onClick={async()=>{setAuditLoading(true);setAuditError("");try{setAuditEvents(await listRunAuditEvents(activeRunId,100));}catch(error){setAuditError(error instanceof Error?error.message:"Could not refresh audit history.");}finally{setAuditLoading(false);}}} disabled={auditLoading} className="rounded-lg border border-line px-3 py-2 text-[11px] font-semibold hover:bg-paper disabled:opacity-50">{auditLoading ? "Refreshing…" : "Refresh history"}</button>
            </div>
            {auditError && <div role="status" className="m-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">{auditError}</div>}
            {auditLoading && auditEvents.length===0 && <p className="p-5 text-xs text-muted">Loading audit history…</p>}
            {!auditLoading && auditEvents.length===0 && <p className="p-5 text-xs leading-5 text-muted">No audit events are recorded for this run yet. Creating a run, saving a report, adding a claim/evidence relation, or reviewing a relation will appear here.</p>}
            {auditEvents.length>0 && <div className="max-h-[480px] divide-y divide-line overflow-y-auto">{[...auditEvents].reverse().map((event)=><article key={event.id} className="px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="text-xs font-semibold">{event.action.replaceAll("_"," ")}</div><div className="mt-1 break-all text-[10px] text-muted">{event.target_entity_type} · {event.target_entity_id}</div></div><div className="flex flex-wrap items-center gap-2"><StatusPill tone={event.resolution_status==="accepted"||event.resolution_status==="recorded"?"teal":event.resolution_status==="needs_review"||event.resolution_status==="unreviewed"?"amber":"slate"}>{event.resolution_status.replaceAll("_"," ")}</StatusPill><span className="text-[10px] text-muted">{new Date(event.created_at).toLocaleString()}</span></div></div>
              {event.reason && <p className="mt-2 text-xs leading-5 text-slate-600">{event.reason}</p>}
              {(event.previous_value || event.new_value) && <div className="mt-3 grid gap-2 md:grid-cols-2">{event.previous_value && <div className="rounded-lg bg-red-50/70 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-red-700">Previous state</div><pre className="mt-1 whitespace-pre-wrap break-words text-[10px] leading-4 text-slate-700">{JSON.stringify(event.previous_value,null,2)}</pre></div>}{event.new_value && <div className="rounded-lg bg-teal-50/70 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-teal-700">New state</div><pre className="mt-1 whitespace-pre-wrap break-words text-[10px] leading-4 text-slate-700">{JSON.stringify(event.new_value,null,2)}</pre></div>}</div>}
              <div className="mt-2 break-all text-[10px] text-muted">Actor: {event.actor_user_id ?? "unavailable"} · Audit ID: {event.id}</div>
            </article>)}</div>}
          </section>}
          {(currentReport || reportLoading) && <section className="mt-5 overflow-hidden rounded-2xl border border-line bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div><div className="text-sm font-semibold">{currentReport?.title ?? "Loading report…"}</div><div className="mt-1 text-xs text-muted">{currentReport ? `Version ${currentReport.version_number} · ${new Date(currentReport.created_at).toLocaleString()}` : "Retrieving saved report version"}</div></div>
              {currentReport && <div className="flex flex-wrap items-center gap-2"><button onClick={()=>{void exportPassport("markdown");}} disabled={passportFormatLoading!==null} className="rounded-lg border border-line px-3 py-2 text-[11px] font-semibold hover:bg-paper disabled:opacity-50">{passportFormatLoading==="markdown"?"Preparing…":"Evidence Passport .md"}</button><button onClick={()=>{void exportPassport("json");}} disabled={passportFormatLoading!==null} className="rounded-lg border border-line px-3 py-2 text-[11px] font-semibold hover:bg-paper disabled:opacity-50">{passportFormatLoading==="json"?"Preparing…":"Export JSON"}</button><StatusPill tone={currentReport.review_required ? "amber" : "blue"}>{currentReport.review_required ? "Review required" : "Discovery snapshot"}</StatusPill></div>}
            </div>
            {currentReport && reportVersions.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-paper px-5 py-3">
              <label className="flex items-center gap-2 text-xs font-semibold">View saved version
                <select value={currentReport.id} onChange={(event)=>{const selected=reportVersions.find((report)=>report.id===event.target.value);if(selected)setCurrentReport(selected);}} className="max-w-[260px] rounded-lg border border-line bg-white px-2.5 py-2 text-xs font-medium">
                  {reportVersions.map((report)=><option key={report.id} value={report.id}>Version {report.version_number}{report.review_required ? " · review required" : ""}</option>)}
                </select>
              </label>
              <div className="flex flex-wrap items-center gap-2">
                {reportVersions.length > 1 && <><select aria-label="Compare older version with latest" value={compareReportId} onChange={(event)=>setCompareReportId(event.target.value)} className="max-w-[190px] rounded-lg border border-line bg-white px-2.5 py-2 text-xs"><option value="">Choose version to compare…</option>{reportVersions.filter((report)=>report.id!==latestReport?.id).map((report)=><option key={report.id} value={report.id}>Version {report.version_number}</option>)}</select><button onClick={()=>setShowVersionCompare((value)=>!value)} disabled={!compareReportId} className="rounded-lg border border-line bg-white px-3 py-2 text-[11px] font-semibold hover:bg-slate-50 disabled:opacity-50">{showVersionCompare ? "Hide comparison" : "Compare with latest"}</button></>}
                <span className="text-[10px] text-muted">{reportVersions.length} saved version(s)</span>
              </div>
            </div>}
            {showVersionCompare && comparedReport && latestReport && comparedReport.id !== latestReport.id && <div className="border-b border-line px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-semibold">Version comparison: {comparedReport.version_number} → {latestReport.version_number}</div><div className="flex flex-wrap gap-2 text-[10px]"><StatusPill tone="red">Removed from latest</StatusPill><StatusPill tone="teal">Added in latest</StatusPill></div></div>
              <p className="mt-1 text-xs leading-5 text-muted">Deterministic line-level comparison of saved Markdown, not a semantic judgement about scientific significance.</p>
              <div className="mt-3 max-h-[360px] space-y-1 overflow-auto rounded-xl bg-slate-950 p-3 font-mono text-[11px] leading-5">
                {versionDiff.map((row,index)=><div key={`${row.kind}-${index}`} className={row.kind==="removed"?"whitespace-pre-wrap break-words bg-red-950/50 px-2 text-red-200":row.kind==="added"?"whitespace-pre-wrap break-words bg-emerald-950/50 px-2 text-emerald-200":"whitespace-pre-wrap break-words px-2 text-slate-300"}>{row.kind==="removed"?"− ":row.kind==="added"?"+ ":"  "}{row.text || " "}</div>)}
              </div>
            </div>}
            {passportError && <div role="status" className="mx-5 mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">{passportError}</div>}{currentReport && <div className="space-y-3 px-5 py-5 text-sm leading-6 text-slate-700">
              {currentReport.change_summary && <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{currentReport.change_summary}</p>}
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                h1: ({children}) => <h1 className="mt-4 text-2xl font-semibold tracking-tight text-ink">{children}</h1>,
                h2: ({children}) => <h2 className="mt-6 border-b border-line pb-2 text-lg font-semibold text-ink">{children}</h2>,
                h3: ({children}) => <h3 className="mt-4 text-base font-semibold text-ink">{children}</h3>,
                p: ({children}) => <p className="mt-3 leading-7">{children}</p>,
                ul: ({children}) => <ul className="mt-3 list-disc space-y-1 pl-6">{children}</ul>,
                ol: ({children}) => <ol className="mt-3 list-decimal space-y-1 pl-6">{children}</ol>,
                li: ({children}) => <li className="pl-1">{children}</li>,
                blockquote: ({children}) => <blockquote className="mt-3 border-l-2 border-accent pl-4 italic text-slate-600">{children}</blockquote>,
                a: ({children, href}) => <a className="font-medium text-accent underline underline-offset-2" href={href} target="_blank" rel="noreferrer">{children}</a>,
                strong: ({children}) => <strong className="font-semibold text-ink">{children}</strong>,
                code: ({children}) => <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">{children}</code>,
              }}>{currentReport.content_markdown}</ReactMarkdown>
              <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">Evidence integrity note: this is a metadata/abstract discovery report. Any model-extracted claims remain unreviewed; the current pipeline does not claim full-text verification or calibrated scientific truth.</div>
            </div>}
          </section>}
          <div className="mt-5 grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
            <section className="rounded-2xl border border-line bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold"><Search size={16} className="text-accent"/> Find academic papers</div>
              <p className="mt-1 text-xs leading-5 text-muted">Search Crossref and OpenAlex metadata. Results are not automatically evidence for a claim.</p>
              <form onSubmit={(event) => { event.preventDefault(); void runAcademicSearch(); }} className="mt-3 flex gap-2">
                <input className="field min-w-0 flex-1" value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="Search papers, methods, or topics"/>
                <button type="submit" disabled={sourceLoading} className="rounded-xl bg-accent px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-50">{sourceLoading ? "Searching…" : "Search"}</button>
              </form>
              {sourceError && <div role="status" className="mt-3 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">{sourceError}</div>}
              {sourceResults.length > 0 && <div className="mt-3 max-h-[460px] space-y-2 overflow-y-auto pr-1">{sourceResults.map((paper) => {
                const key = paperKey(paper);
                const saved = savedPaperKeys.includes(key);
                return <article key={key} className="rounded-xl border border-line p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><div className="text-sm font-semibold leading-5">{paper.title}</div><div className="mt-1 text-[11px] text-muted">{paper.authors.slice(0, 4).join(", ")}{paper.authors.length > 4 ? " et al." : ""}{paper.publication_year ? ` · ${paper.publication_year}` : ""} · {paper.provider}</div></div>
                    <button onClick={() => void savePaper(paper)} disabled={saved || savingPaperKey === key} className="shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-[11px] font-semibold hover:bg-paper disabled:opacity-60">{saved ? "Saved" : savingPaperKey === key ? "Saving…" : "Add to library"}</button>
                  </div>
                  {paper.abstract && <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted">{paper.abstract}</p>}
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-muted">{paper.doi && <span>DOI: {paper.doi}</span>}{paper.landing_url && <a href={paper.landing_url} target="_blank" rel="noreferrer" className="font-semibold text-accent hover:underline">Open source ↗</a>}</div>
                </article>;
              })}</div>}
            </section>
            <section className="rounded-2xl border border-line bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold"><Upload size={16} className="text-accent"/> Ingest a research PDF</div>
              <p className="mt-1 text-xs leading-5 text-muted">Extract selectable text into page-aware passages. Scanned PDFs need OCR, and extracted passages are not verified claims.</p>
              <label className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-paper px-4 py-7 text-center transition hover:border-accent hover:bg-accent-soft/40">
                <Upload size={22} className="text-muted"/>
                <span className="mt-2 text-xs font-semibold">{uploadingPdf ? "Uploading and extracting…" : "Choose a PDF from your device"}</span>
                <span className="mt-1 text-[10px] text-muted">PDF · configured maximum upload size applies</span>
                <input className="sr-only" type="file" accept="application/pdf,.pdf" disabled={uploadingPdf} onChange={(event) => { const file = event.target.files?.[0]; void handlePdfUpload(file); event.currentTarget.value = ""; }}/>
              </label>
              {uploadMessage && <div role="status" className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700">{uploadMessage}</div>}
            </section>
          </div>
          <div className="mt-7 border-t border-line pt-5"><div className="flex items-center justify-between"><div className="font-semibold">Claim ledger</div><div className="relative"><Search size={14} className="absolute left-3 top-2.5 text-muted"/><input className="field w-52 pl-8 py-2 text-xs" value={searchTerm} onChange={e=>setSearchTerm(e.target.value)} placeholder="Filter claims"/></div></div><div className="mt-3 space-y-3">{claims.map(c=><button key={c.id} onClick={()=>setActiveClaim(c.id)} className={`w-full rounded-xl border p-4 text-left ${activeClaim===c.id ? "border-accent bg-accent-soft/40" : "border-line hover:bg-paper"}`}><div className="flex items-start justify-between gap-3"><div><div className="text-[10px] font-semibold text-muted">{c.id}</div><div className="mt-1 text-sm font-semibold">{c.title}</div></div><StatusPill tone={c.tone}>{c.state}</StatusPill></div><div className="mt-2 text-xs leading-5 text-muted">{c.summary}</div></button>)}</div></div></section><aside className="surface h-fit p-5"><div className="flex items-center gap-2 font-semibold"><FileSearch size={17} className="text-accent"/> Claim inspector</div><p className="mt-1 text-xs text-muted">Select a claim to inspect its evidence status.</p>{(()=>{const c=demoClaims.find(x=>x.id===activeClaim)??demoClaims[0];return <><div className="mt-5 rounded-xl bg-paper p-4"><div className="text-[10px] font-semibold text-muted">{c.id}</div><div className="mt-1 text-sm font-semibold">{c.title}</div><div className="mt-3"><StatusPill tone={c.tone}>{c.state}</StatusPill></div></div><div className="mt-5"><div className="text-xs font-semibold">Evidence assessment</div><p className="mt-2 text-xs leading-5 text-muted">{c.summary}</p></div><div className="mt-5"><div className="text-xs font-semibold">Provenance basis</div><div className="mt-2 rounded-xl border border-dashed border-line p-3 text-xs leading-5 text-muted">No live source passages are attached in this UI prototype. Verified provenance will be displayed here when ingestion is implemented.</div></div></>})()}<div className="mt-5 flex gap-2 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900"><AlertTriangle size={16} className="mt-0.5 shrink-0"/> Demo evidence must not be treated as a scientific finding.</div></aside></div>}

        {view === "Evidence graph" && <section className="surface p-5 md:p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><div className="eyebrow">Provenance explorer</div><h1 className="mt-2 text-xl font-semibold">Evidence relationship map</h1><p className="mt-1 text-xs leading-5 text-muted">{graphData ? "Live persisted relationships for the selected research run." : "The diagram below is illustrative until a completed run has persisted its source/evidence records."}</p></div>{graphData ? <StatusPill tone="teal">Persisted graph</StatusPill> : <StatusPill tone="amber">Illustrative graph</StatusPill>}</div>{graphLoading && <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs text-muted">Loading persisted graph…</div>}{graphError && <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{graphError}</div>}{graphData && <div className="mt-6 space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[{label:"Nodes",value:graphData.nodes.length},{label:"Relationships",value:graphData.edges.length},{label:"Claim nodes",value:graphData.nodes.filter((n)=>n.type==="claim").length},{label:"Source papers",value:graphData.nodes.filter((n)=>n.type==="paper").length}].map((m)=><div key={m.label} className="rounded-xl border border-line bg-paper p-3"><div className="text-xs text-muted">{m.label}</div><div className="mt-1 text-xl font-semibold">{m.value}</div></div>)}</div><div className="grid gap-5 xl:grid-cols-[1fr_1fr]"><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Persisted nodes</div><div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto">{graphData.nodes.map((node)=><article key={node.id} className="rounded-lg bg-paper p-3"><div className="flex flex-wrap items-center gap-2"><StatusPill tone={node.type==="claim"?"blue":"slate"}>{node.type.replace("_"," ")}</StatusPill>{node.review_required && <StatusPill tone="amber">Review required</StatusPill>}{node.publication_status && <StatusPill>{node.publication_status}</StatusPill>}{node.extraction_basis && <StatusPill tone={node.extraction_basis==="model_inferred"?"amber":"teal"}>{node.extraction_basis.replaceAll("_"," ")}</StatusPill>}</div><div className="mt-2 break-words text-xs font-semibold leading-5 text-ink">{node.label}</div>{node.doi && <div className="mt-1 break-all text-[10px] text-muted">{node.doi}</div>}{node.type==="study" && <div className="mt-2 space-y-1 text-[11px] leading-5 text-slate-600">{node.population && <div><span className="font-semibold">Population:</span> {node.population}</div>}{node.method && <div><span className="font-semibold">Method:</span> {node.method}</div>}{node.intervention && <div><span className="font-semibold">Intervention:</span> {node.intervention}</div>}{node.outcomes?.length ? <div><span className="font-semibold">Outcomes:</span> {node.outcomes.join("; ")}</div> : null}{node.limitations?.length ? <div><span className="font-semibold">Limitations:</span> {node.limitations.join("; ")}</div> : null}{node.source_passage_id && <div className="break-all"><span className="font-semibold">Source passage:</span> {node.source_passage_id}</div>}</div>}<div className="mt-1 break-all text-[10px] text-muted">{node.id}</div></article>)}</div></div><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Persisted relationships</div><div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto">{graphData.edges.map((edge,index)=><article key={edge.id ?? `${edge.source}-${edge.target}-${index}`} className="rounded-lg border border-line p-3"><div className="flex flex-wrap items-center gap-2"><StatusPill tone={edge.type==="contradicts"?"red":edge.type==="supports"?"teal":"blue"}>{edge.type.replaceAll("_"," ")}</StatusPill>{edge.reviewer_status && <StatusPill>{edge.reviewer_status}</StatusPill>}</div><div className="mt-2 text-xs font-medium leading-5">{graphData.nodes.find((n)=>n.id===edge.source)?.label ?? edge.source}</div><div className="my-1 text-[10px] font-semibold uppercase tracking-wide text-muted">↓ {edge.type.replaceAll("_"," ")} ↓</div><div className="text-xs font-medium leading-5">{graphData.nodes.find((n)=>n.id===edge.target)?.label ?? edge.target}</div>{edge.provenance_basis && <div className="mt-2 text-[10px] text-muted">Basis: {edge.provenance_basis}{edge.confidence != null ? ` · confidence ${edge.confidence}` : ""}</div>}{edge.rationale && <p className="mt-2 text-xs leading-5 text-muted">{edge.rationale}</p>}{edge.id && edge.reviewer_status === "unreviewed" && <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3"><button onClick={() => { void reviewGraphRelation(edge.id as string, "accepted"); }} disabled={reviewingRelationId === edge.id} className="rounded-lg bg-teal-600 px-3 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50">{reviewingRelationId === edge.id ? "Saving…" : "Accept as reviewed"}</button><button onClick={() => { void reviewGraphRelation(edge.id as string, "rejected"); }} disabled={reviewingRelationId === edge.id} className="rounded-lg border border-line px-3 py-1.5 text-[11px] font-semibold hover:bg-paper disabled:opacity-50">Reject relation</button></div>}</article>)}{graphData.edges.length===0 && <p className="text-xs leading-5 text-muted">No saved evidence relationships yet. A discovery run stores papers and passages first; claim/evidence relationships will appear after claim extraction and review.</p>}</div></div></div><p className="text-[11px] leading-5 text-muted">{graphData.note}</p></div>}{graphData ? null : <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_300px]"><div className="relative min-h-[430px] overflow-hidden rounded-2xl border border-line bg-[radial-gradient(#dfe4ee_1px,transparent_1px)] [background-size:20px_20px]"><svg className="absolute inset-0 h-full w-full" viewBox="0 0 760 430" preserveAspectRatio="xMidYMid meet" aria-label="Illustrative evidence graph"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9aa5bb"/></marker></defs><g stroke="#aab3c6" strokeWidth="1.7" markerEnd="url(#arrow)" fill="none"><path d="M190 90 L305 164"/><path d="M190 218 L305 187"/><path d="M445 173 L565 105"/><path d="M445 194 L565 270"/><path d="M190 340 L305 220"/><path d="M445 208 L565 350"/></g><g fontSize="11" fill="#65718a"><text x="223" y="115">supports</text><text x="225" y="211">qualifies</text><text x="478" y="127">derived from</text><text x="480" y="246">depends on</text><text x="218" y="297">cites</text></g>{[{x:36,y:58,w:155,h:64,title:"Paper A",sub:"Paper version"},{x:36,y:187,w:155,h:64,title:"Paper B",sub:"Study record"},{x:305,y:143,w:140,h:76,title:"Claim C-001",sub:"Atomic claim"},{x:565,y:72,w:160,h:66,title:"Passage P-04",sub:"Page / section"},{x:565,y:236,w:160,h:66,title:"Conclusion R-01",sub:"Report version"},{x:36,y:308,w:155,h:64,title:"Source event",sub:"Correction / update"},{x:565,y:322,w:160,h:66,title:"Impact queue",sub:"Requires reassessment"}].map((n,i)=><g key={n.title} onClick={()=>setNotice(`${n.title}: illustrative node. Actual graph data will come from stored evidence records.`)} className="cursor-pointer"><rect x={n.x} y={n.y} width={n.w} height={n.h} rx="12" fill={i===2?"#eef0ff":"#ffffff"} stroke={i===2?"#7082ed":"#d9dfeb"} strokeWidth={i===2?2:1.2}/><text x={n.x+12} y={n.y+27} fontSize="13" fontWeight="600" fill="#172033">{n.title}</text><text x={n.x+12} y={n.y+47} fontSize="10" fill="#65718a">{n.sub}</text></g>)}</svg></div><aside className="space-y-4"><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Relationship legend</div>{[["supports","bg-teal-500"],["contradicts","bg-red-500"],["qualifies","bg-amber-500"],["derived from","bg-indigo-500"],["depends on","bg-slate-500"]].map(([label,color])=><div key={label} className="mt-3 flex items-center gap-2 text-xs text-muted"><span className={`h-2 w-2 rounded-full ${color}`}/>{label}</div>)}</div><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Graph safeguards</div><ul className="mt-3 space-y-2 text-xs leading-5 text-muted"><li>• Explicit and inferred edges are distinguished.</li><li>• Missing relationships are not treated as evidence of absence.</li><li>• Source events trigger reassessment, not automatic invalidation.</li></ul></div><div className="rounded-xl bg-paper p-4"><div className="text-xs font-semibold">Next milestone</div><p className="mt-2 text-xs leading-5 text-muted">Persist papers, passages, claims and edge provenance before connecting the graph UI to a live database.</p></div></aside></div>}</section>}

        {view === "Source timeline" && <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="surface p-5 md:p-6">
            <div className="eyebrow">Temporal evidence lifecycle</div><h1 className="mt-2 text-xl font-semibold">Source timeline</h1>
            <p className="mt-1 text-sm leading-6 text-muted">Record a correction, retraction or conflicting finding, then trace which claims and report versions should be reviewed.</p>
            <form onSubmit={submitSourceEvent} className="mt-5 rounded-2xl border border-line bg-paper p-4">
              <div className="text-sm font-semibold">Record a source event</div><p className="mt-1 text-xs leading-5 text-muted">This version accepts manual events; it does not automatically monitor publishers.</p>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <label className="text-xs font-semibold">Saved paper<select value={eventPaperId} onChange={(e)=>setEventPaperId(e.target.value)} className="field mt-1.5" disabled={!libraryPapers.length}><option value="">Select paper…</option>{libraryPapers.map(p=><option key={p.id} value={p.id}>{p.title.slice(0,90)}{p.doi ? ` · ${p.doi}` : ""}</option>)}</select><button type="button" onClick={()=>{void runPaperStatusCheck();}} disabled={!eventPaperId || checkingStatus} className="mt-2 rounded-lg border border-line px-3 py-1.5 text-[11px] font-semibold hover:bg-white disabled:opacity-50">{checkingStatus ? "Checking Crossref/OpenAlex…" : "Check external status"}</button></label>
                <label className="text-xs font-semibold">Event type<select value={eventType} onChange={(e)=>setEventType(e.target.value as typeof eventType)} className="field mt-1.5"><option value="retraction">Retraction</option><option value="correction">Correction</option><option value="expression_of_concern">Expression of concern</option><option value="new_version">New version</option><option value="metadata_change">Metadata change</option><option value="conflicting_study">Conflicting study</option></select></label>
              </div>
              <label className="mt-3 block text-xs font-semibold">Description<textarea value={eventDescription} onChange={(e)=>setEventDescription(e.target.value)} className="field mt-1.5 resize-y" rows={3} minLength={8} placeholder="Describe the notice or conflicting result and why it requires review."/></label>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <label className="text-xs font-semibold">Source URL (optional)<input value={eventSourceUrl} onChange={(e)=>setEventSourceUrl(e.target.value)} className="field mt-1.5" type="url" placeholder="https://publisher.example/notice"/></label>
                <label className="text-xs font-semibold">Verification status<select value={eventVerification} onChange={(e)=>setEventVerification(e.target.value as typeof eventVerification)} className="field mt-1.5"><option value="unverified">Unverified — review only</option><option value="metadata_confirmed">Metadata confirmed</option><option value="human_verified">Human verified</option></select></label>
              </div>
              <div className="mt-4 flex justify-end"><button type="submit" disabled={recordingEvent || !libraryPapers.length} className="rounded-xl bg-accent px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{recordingEvent ? "Recording…" : "Record event & analyse impact"}</button></div>
            </form>
            {timelineError && <div role="status" className="mt-3 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900">{timelineError}</div>}
            {statusCheck && <div className="mt-4 rounded-xl border border-line p-4">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="text-sm font-semibold">External status-check preview</div><div className="mt-1 text-xs text-muted">DOI: {statusCheck.doi ?? "Unavailable"} · no source event is created automatically</div></div><StatusPill tone={statusCheck.signals.length ? "amber" : "blue"}>{statusCheck.signals.length ? `${statusCheck.signals.length} candidate signal(s)` : "No signal found"}</StatusPill></div>
              <div className="mt-2 text-[11px] leading-5 text-muted">Crossref: {statusCheck.providers.crossref ?? "not checked"} · OpenAlex: {statusCheck.providers.openalex ?? "not checked"}</div>
              {statusCheck.signals.length===0 && <p className="mt-3 text-xs leading-5 text-muted">No update signal was returned in this check. This is not proof that no correction or retraction exists.</p>}
              <div className="mt-3 space-y-2">{statusCheck.signals.map((signal,index)=><div key={`${signal.provider}-${signal.update_type}-${index}`} className="rounded-lg bg-paper p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap gap-2"><StatusPill tone={signal.event_type==="retraction"?"red":"amber"}>{signal.event_type.replaceAll("_"," ")}</StatusPill><StatusPill>{signal.provider}</StatusPill></div><button type="button" onClick={()=>handleStatusSignal(signal)} className="rounded-lg bg-accent px-3 py-1.5 text-[11px] font-semibold text-white">Review this signal</button></div><p className="mt-2 text-xs leading-5 text-slate-700">{signal.description}</p>{signal.source_url && <a href={signal.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block break-all text-[11px] font-semibold text-accent underline">{signal.source_url}</a>}</div>)}</div>
              <p className="mt-3 text-[11px] leading-5 text-muted">{statusCheck.note}</p>
            </div>}

            {eventResult && <div role="status" className="mt-3 rounded-lg border border-teal-200 bg-teal-50 p-3 text-xs leading-5 text-teal-900">{eventResult}</div>}
            <div className="mt-7 flex items-center justify-between gap-3"><div><div className="text-sm font-semibold">Recorded events</div><div className="mt-1 text-xs text-muted">Source events and their persisted impact summaries</div></div><button onClick={async()=>{setTimelineLoading(true);try{const [papers,events]=await Promise.all([listLibraryPapers(100),listSourceEvents(50)]);setLibraryPapers(papers);setSourceEvents(events);setTimelineError("");}catch(error){setTimelineError(error instanceof Error?error.message:"Refresh failed.");}finally{setTimelineLoading(false);}}} disabled={timelineLoading} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold hover:bg-paper disabled:opacity-50">{timelineLoading ? "Loading…" : "Refresh"}</button></div>
            {timelineLoading && <p className="mt-3 text-xs text-muted">Loading source events…</p>}
            {!timelineLoading && sourceEvents.length===0 && <div className="mt-4 rounded-xl border border-dashed border-line p-5 text-xs leading-5 text-muted">{libraryPapers.length ? "No events have been recorded yet." : "Save an academic paper or upload a PDF in the Research Workspace before recording a source event."}</div>}
            <div className="mt-4 space-y-3">{sourceEvents.map((event)=>{
              const impact=event.metadata_snapshot.impact_summary as {impacted_paper_count?:number;claims_flagged_for_review?:number;affected_run_count?:number;report_versions_flagged_for_review?:number}|undefined;
              return <article key={event.id} className="rounded-xl border border-line p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="text-[10px] font-semibold text-muted">{new Date(event.observed_at).toLocaleString()}</div><h3 className="mt-1 text-sm font-semibold">{event.paper_title}</h3><div className="mt-2 flex flex-wrap gap-2"><StatusPill tone={event.event_type==="retraction"?"red":event.event_type==="correction"?"amber":"blue"}>{event.event_type.replaceAll("_"," ")}</StatusPill><StatusPill tone={event.verification_status==="unverified"?"amber":"teal"}>{event.verification_status.replaceAll("_"," ")}</StatusPill></div></div><div className="rounded-lg bg-paper px-3 py-2 text-right"><div className="text-lg font-semibold">{impact?.claims_flagged_for_review ?? "—"}</div><div className="text-[10px] text-muted">claims flagged</div></div></div><p className="mt-3 text-xs leading-5 text-muted">{event.description}</p>{event.source_url && <a href={event.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-block break-all text-xs font-semibold text-accent underline">{event.source_url}</a>}{impact && <div className="mt-3 grid gap-2 sm:grid-cols-3"><div className="rounded-lg bg-paper p-2"><div className="text-sm font-semibold">{impact.impacted_paper_count ?? 0}</div><div className="text-[10px] text-muted">papers in dependency chain</div></div><div className="rounded-lg bg-paper p-2"><div className="text-sm font-semibold">{impact.affected_run_count ?? 0}</div><div className="text-[10px] text-muted">research runs</div></div><div className="rounded-lg bg-paper p-2"><div className="text-sm font-semibold">{impact.report_versions_flagged_for_review ?? 0}</div><div className="text-[10px] text-muted">report versions flagged</div></div></div>}<div className="mt-3 break-all text-[10px] text-muted">Paper ID: {event.paper_id}</div></article>;
            })}</div>
            <p className="mt-5 text-[11px] leading-5 text-muted">Impact analysis flags related claims and reports for review. A source event does not automatically establish that any dependent claim is false.</p>
          </section>
          <aside className="surface h-fit p-5"><div className="flex items-center gap-2 font-semibold"><GitCompare size={17} className="text-accent"/> Impact overview</div><div className="mt-4 grid gap-3"><div className="rounded-xl bg-paper p-4"><div className="text-2xl font-semibold">{sourceEvents.length}</div><div className="text-xs text-muted">source events recorded</div></div><div className="rounded-xl bg-paper p-4"><div className="text-2xl font-semibold">{sourceEvents.filter(e=>e.verification_status!=="unverified").length}</div><div className="text-xs text-muted">events marked verified</div></div></div><div className="mt-5 rounded-xl border border-line p-4"><div className="text-sm font-semibold">Impact process</div><ol className="mt-3 list-decimal space-y-2 pl-5 text-xs leading-5 text-muted"><li>Start from the source event.</li><li>Traverse recorded source dependencies.</li><li>Find claims linked to passages from affected papers.</li><li>Flag those claims and dependent report versions for review.</li></ol></div><button onClick={()=>setView("Evidence graph")} className="mt-4 flex items-center gap-2 text-xs font-semibold text-accent">Inspect evidence graph <ArrowRight size={14}/></button></aside>
        </div>}

        {view === "Hypothesis lab" && <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="surface p-5 md:p-6">
            <div className="eyebrow">Research discovery</div>
            <h1 className="mt-2 text-xl font-semibold">Hypothesis Lab</h1>
            <p className="mt-1 text-sm leading-6 text-muted">Turn gaps and disagreements in the retrieved evidence into candidate research questions. Candidates are not novelty claims and require prior-art review.</p>
            {activeRunId && <div className="mt-3 rounded-lg bg-paper px-3 py-2 text-xs text-muted">Active run: {activeRunId.slice(0,8)} · {currentReport?.title ?? "No saved report loaded"}</div>}
            {activeSynthesis ? <div className="mt-6 space-y-5">
              <div className="rounded-xl border border-line p-4">
                <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-semibold">Research synthesis context</div><StatusPill tone="amber">Human review required</StatusPill></div>
                <p className="mt-2 text-sm leading-6 text-slate-700">{activeSynthesis.executive_summary ?? "The report does not include an executive synthesis summary."}</p>
                {activeSynthesis.uncertainty_statement && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900">Uncertainty: {activeSynthesis.uncertainty_statement}</p>}
              </div>
              <div>
                <div className="text-sm font-semibold">Candidate research questions</div>
                <p className="mt-1 text-xs leading-5 text-muted">Generated from retrieved abstracts when the optional server-side model is configured. Re-run prior-art search before claiming novelty.</p>
                {activeSynthesis.candidate_research_questions?.length ? <div className="mt-3 space-y-3">{activeSynthesis.candidate_research_questions.map((question,index)=><article key={question} className="rounded-xl border border-line p-4"><div className="flex items-center justify-between gap-3"><StatusPill tone="blue">Candidate {index+1}</StatusPill><button onClick={()=>{setQuery(question);setView("Research workspace");}} className="rounded-lg border border-line px-3 py-1.5 text-[11px] font-semibold hover:bg-paper">Investigate this question</button></div><p className="mt-3 text-sm font-medium leading-6">{question}</p><p className="mt-2 text-[11px] leading-5 text-muted">Candidate only · novelty has not been established · human prior-art check required</p></article>)}</div> : <div className="mt-3 rounded-xl border border-dashed border-line p-4 text-xs leading-5 text-muted">This report did not produce any candidate research questions. Try a more focused research question or review the evidence and limitations.</div>}
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Evidence-linked findings</div><div className="mt-3 space-y-3">{activeSynthesis.findings?.length ? activeSynthesis.findings.map((finding,index)=><article key={`${index}-${finding.statement}`} className="rounded-lg bg-paper p-3"><div className="flex flex-wrap gap-2"><StatusPill tone={finding.relation_type==="supports"?"teal":finding.relation_type==="contradicts"?"red":"blue"}>{finding.relation_type ?? "qualifies"}</StatusPill></div><p className="mt-2 text-xs font-medium leading-5">{finding.statement}</p>{finding.context_note && <p className="mt-1 text-xs leading-5 text-muted">{finding.context_note}</p>}{finding.evidence_passage_ids?.length ? <p className="mt-2 break-words text-[10px] text-muted">Evidence passage IDs: {finding.evidence_passage_ids.join(", ")}</p> : null}</article>) : <p className="text-xs leading-5 text-muted">No evidence-linked findings were returned for this report.</p>}</div></div>
                <div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Possible disagreements</div><div className="mt-3 space-y-3">{activeSynthesis.disagreements?.length ? activeSynthesis.disagreements.map((item,index)=><article key={`${index}-${item.description}`} className="rounded-lg bg-paper p-3"><p className="text-xs leading-5">{item.description}</p>{item.comparability_note && <p className="mt-1 text-xs leading-5 text-muted">Comparability: {item.comparability_note}</p>}<p className="mt-2 break-words text-[10px] text-muted">Passage IDs: {item.evidence_passage_ids?.join(", ")}</p></article>) : <p className="text-xs leading-5 text-muted">No possible disagreements were identified in this synthesis. This does not prove the source corpus contains no conflicting work.</p>}</div></div>
              </div>
              {activeSynthesis.limitations?.length ? <div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Reported limitations</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-muted">{activeSynthesis.limitations.map(item=><li key={item}>{item}</li>)}</ul></div> : null}
              <div className="rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">This synthesis may use abstracts only. It has not independently verified the truth of the claims, proven global novelty, or completed full-text systematic review.</div>
            </div> : <div className="mt-6">
              <div className="rounded-xl border border-dashed border-line p-5">
                <div className="flex items-center gap-2 text-sm font-semibold"><CircleHelp size={17} className="text-muted"/> No model-generated hypothesis set available</div>
                <p className="mt-2 text-xs leading-5 text-muted">Open a completed research report to view its synthesis. The optional model synthesis is enabled only when OPENAI_API_KEY and OPENAI_MODEL are configured in the backend environment; otherwise Chronicle still returns an academic discovery snapshot.</p>
              </div>
              <div className="mt-5 grid gap-4 md:grid-cols-2">{[
                {title:"Unresolved disagreement",tag:"Evidence conflict",text:"Compare conflicting claims and check whether populations, measurements or settings explain the difference."},
                {title:"Cross-domain method transfer",tag:"Candidate connection",text:"Search for prior work before proposing that a method from one field could answer a problem in another."},
                {title:"Coverage blind spot",tag:"Missing evidence",text:"Identify populations or outcomes underrepresented in the retrieved corpus, without equating missing retrieval with absence of research."},
                {title:"Replication opportunity",tag:"Validation design",text:"Identify claims with limited or dependent evidence and outline a falsifiable replication question."}
              ].map(card=><div key={card.title} className="rounded-xl border border-line p-4"><StatusPill tone="blue">{card.tag}</StatusPill><h3 className="mt-3 text-sm font-semibold">{card.title}</h3><p className="mt-2 text-xs leading-5 text-muted">{card.text}</p><div className="mt-4 text-[10px] text-muted">Research design template · not a generated discovery</div></div>)}</div>
            </div>}
          </section>
          <aside className="surface h-fit p-5"><div className="flex items-center gap-2 font-semibold"><Microscope size={17} className="text-accent"/> Hypothesis checklist</div><ul className="mt-4 space-y-3 text-xs leading-5 text-muted"><li>• Locate the closest prior work.</li><li>• Cite the evidence that motivates the hypothesis.</li><li>• Explain alternative interpretations.</li><li>• Define what result would falsify it.</li><li>• Record human review before calling it novel.</li></ul><div className="mt-5 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">A missing link in a retrieved graph is not proof that no one has studied it.</div><button onClick={()=>setView("Research workspace")} className="mt-4 flex items-center gap-2 text-xs font-semibold text-accent">Return to research workspace <ArrowRight size={14}/></button></aside>
        </div>}
      </div>
      <footer className="border-t border-line bg-white px-5 py-4 text-[11px] text-muted md:px-8"><div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-2"><span>Chronicle · Major project prototype</span><span>Academic metadata search, PDF ingestion and discovery runs are connected; full-text verification and scheduled source monitoring are not yet implemented.</span></div></footer>
    </main>

    {showNewRun && <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true" aria-labelledby="new-run-title"><div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between"><div><div className="eyebrow">New research run</div><h2 id="new-run-title" className="mt-2 text-xl font-semibold">What do you want to investigate?</h2><p className="mt-1 text-sm text-muted">Creates a discovery run using Crossref/OpenAlex. Optional model synthesis requires backend credentials.</p></div><button onClick={()=>setShowNewRun(false)} className="rounded-lg p-2 text-muted hover:bg-paper" aria-label="Close">×</button></div><label className="mt-5 block text-xs font-semibold">Research question</label><textarea value={query} onChange={e=>setQuery(e.target.value)} rows={4} className="field mt-2 resize-y" placeholder="e.g. What evidence supports the use of retrieval-augmented generation for scientific question answering?"/><label className="mt-4 block text-xs font-semibold">Mode</label><select value={mode} onChange={e=>setMode(e.target.value)} className="field mt-2"><option>Quick scan</option><option>Deep research</option><option>Academic review</option><option>Forensic analysis</option></select><div className="mt-5 flex justify-end gap-2"><button onClick={()=>setShowNewRun(false)} className="rounded-xl border border-line px-4 py-2.5 text-sm font-semibold">Cancel</button><button onClick={startResearch} disabled={submitting} className="rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{submitting ? "Creating..." : "Create run"}</button></div></div></div>}
  </div>;
}
