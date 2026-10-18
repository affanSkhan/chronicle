"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createResearchRun, getEvidenceGraph, importPaper, listReportVersions, listResearchRuns, searchAcademicSources, uploadPdf, type AcademicSearchResult, type EvidenceGraphResponse, type ReportVersionSummary, type ResearchMode as ApiResearchMode, type ResearchRun } from "@/lib/api";
import {
  Activity, ArrowRight, BookOpen, Clock3, FileSearch, FlaskConical, GitBranch, GitCompare,
  History, LayoutDashboard, Microscope, Network, Plus, Search,
  ShieldCheck, Sparkles, Upload, Workflow, AlertTriangle, CircleDashed
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
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [currentReport, setCurrentReport] = useState<ReportVersionSummary | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [graphData, setGraphData] = useState<EvidenceGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
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
    const loadRuns = async () => {
      try {
        const latest = await listResearchRuns();
        if (!cancelled) setRuns(latest);
      } catch {
        // The rest of the workspace remains usable when the backend is offline.
      }
    };
    void loadRuns();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (view !== "Evidence graph" || !activeRunId) {
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
  }, [view, activeRunId]);

  useEffect(() => {
    if (!activeRunId) return;
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
            if (!cancelled) setCurrentReport(reports[0] ?? null);
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
  }, [activeRunId]);


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
      setView("Research workspace");
      setNotice(`Run ${created.id.slice(0, 8)} submitted. Searching Crossref/OpenAlex and building an academic discovery snapshot…`);
      setShowNewRun(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not reach the Chronicle API. Check that the API is running.");
    } finally {
      setSubmitting(false);
    }
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
        <div className="flex items-center gap-2"><span className="hidden rounded-full bg-amber-50 px-3 py-1.5 text-[11px] font-medium text-amber-800 sm:inline-flex">Demo data</span><button onClick={() => setShowNewRun(true)} className="inline-flex items-center gap-2 rounded-xl bg-accent px-3.5 py-2.5 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700"><Plus size={15}/> New research</button></div>
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
              <div className="flex items-center gap-2"><StatusPill tone="blue">{run.mode}</StatusPill><StatusPill>{run.status}</StatusPill></div>
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
          {(currentReport || reportLoading) && <section className="mt-5 overflow-hidden rounded-2xl border border-line bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div><div className="text-sm font-semibold">{currentReport?.title ?? "Loading report…"}</div><div className="mt-1 text-xs text-muted">{currentReport ? `Version ${currentReport.version_number} · ${new Date(currentReport.created_at).toLocaleString()}` : "Retrieving saved report version"}</div></div>
              {currentReport && <StatusPill tone={currentReport.review_required ? "amber" : "blue"}>{currentReport.review_required ? "Review required" : "Discovery snapshot"}</StatusPill>}
            </div>
            {currentReport && <div className="space-y-3 px-5 py-5 text-sm leading-6 text-slate-700">
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

        {view === "Evidence graph" && <section className="surface p-5 md:p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><div className="eyebrow">Provenance explorer</div><h1 className="mt-2 text-xl font-semibold">Evidence relationship map</h1><p className="mt-1 text-xs leading-5 text-muted">{graphData ? "Live persisted relationships for the selected research run." : "The diagram below is illustrative until a completed run has persisted its source/evidence records."}</p></div>{graphData ? <StatusPill tone="teal">Persisted graph</StatusPill> : <StatusPill tone="amber">Illustrative graph</StatusPill>}</div>{graphLoading && <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs text-muted">Loading persisted graph…</div>}{graphError && <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">{graphError}</div>}{graphData && <div className="mt-6 space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[{label:"Nodes",value:graphData.nodes.length},{label:"Relationships",value:graphData.edges.length},{label:"Claim nodes",value:graphData.nodes.filter((n)=>n.type==="claim").length},{label:"Source papers",value:graphData.nodes.filter((n)=>n.type==="paper").length}].map((m)=><div key={m.label} className="rounded-xl border border-line bg-paper p-3"><div className="text-xs text-muted">{m.label}</div><div className="mt-1 text-xl font-semibold">{m.value}</div></div>)}</div><div className="grid gap-5 xl:grid-cols-[1fr_1fr]"><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Persisted nodes</div><div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto">{graphData.nodes.map((node)=><article key={node.id} className="rounded-lg bg-paper p-3"><div className="flex flex-wrap items-center gap-2"><StatusPill tone={node.type==="claim"?"blue":"slate"}>{node.type.replace("_"," ")}</StatusPill>{node.review_required && <StatusPill tone="amber">Review required</StatusPill>}{node.publication_status && <StatusPill>{node.publication_status}</StatusPill>}</div><div className="mt-2 break-words text-xs font-semibold leading-5 text-ink">{node.label}</div>{node.doi && <div className="mt-1 break-all text-[10px] text-muted">{node.doi}</div>}<div className="mt-1 break-all text-[10px] text-muted">{node.id}</div></article>)}</div></div><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Persisted relationships</div><div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto">{graphData.edges.map((edge,index)=><article key={edge.id ?? `${edge.source}-${edge.target}-${index}`} className="rounded-lg border border-line p-3"><div className="flex flex-wrap items-center gap-2"><StatusPill tone={edge.type==="contradicts"?"red":edge.type==="supports"?"teal":"blue"}>{edge.type.replaceAll("_"," ")}</StatusPill>{edge.reviewer_status && <StatusPill>{edge.reviewer_status}</StatusPill>}</div><div className="mt-2 text-xs font-medium leading-5">{graphData.nodes.find((n)=>n.id===edge.source)?.label ?? edge.source}</div><div className="my-1 text-[10px] font-semibold uppercase tracking-wide text-muted">↓ {edge.type.replaceAll("_"," ")} ↓</div><div className="text-xs font-medium leading-5">{graphData.nodes.find((n)=>n.id===edge.target)?.label ?? edge.target}</div>{edge.provenance_basis && <div className="mt-2 text-[10px] text-muted">Basis: {edge.provenance_basis}{edge.confidence != null ? ` · confidence ${edge.confidence}` : ""}</div>}{edge.rationale && <p className="mt-2 text-xs leading-5 text-muted">{edge.rationale}</p>}</article>)}{graphData.edges.length===0 && <p className="text-xs leading-5 text-muted">No saved evidence relationships yet. A discovery run stores papers and passages first; claim/evidence relationships will appear after claim extraction and review.</p>}</div></div></div><p className="text-[11px] leading-5 text-muted">{graphData.note}</p></div>}{graphData ? null : <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_300px]"><div className="relative min-h-[430px] overflow-hidden rounded-2xl border border-line bg-[radial-gradient(#dfe4ee_1px,transparent_1px)] [background-size:20px_20px]"><svg className="absolute inset-0 h-full w-full" viewBox="0 0 760 430" preserveAspectRatio="xMidYMid meet" aria-label="Illustrative evidence graph"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9aa5bb"/></marker></defs><g stroke="#aab3c6" strokeWidth="1.7" markerEnd="url(#arrow)" fill="none"><path d="M190 90 L305 164"/><path d="M190 218 L305 187"/><path d="M445 173 L565 105"/><path d="M445 194 L565 270"/><path d="M190 340 L305 220"/><path d="M445 208 L565 350"/></g><g fontSize="11" fill="#65718a"><text x="223" y="115">supports</text><text x="225" y="211">qualifies</text><text x="478" y="127">derived from</text><text x="480" y="246">depends on</text><text x="218" y="297">cites</text></g>{[{x:36,y:58,w:155,h:64,title:"Paper A",sub:"Paper version"},{x:36,y:187,w:155,h:64,title:"Paper B",sub:"Study record"},{x:305,y:143,w:140,h:76,title:"Claim C-001",sub:"Atomic claim"},{x:565,y:72,w:160,h:66,title:"Passage P-04",sub:"Page / section"},{x:565,y:236,w:160,h:66,title:"Conclusion R-01",sub:"Report version"},{x:36,y:308,w:155,h:64,title:"Source event",sub:"Correction / update"},{x:565,y:322,w:160,h:66,title:"Impact queue",sub:"Requires reassessment"}].map((n,i)=><g key={n.title} onClick={()=>setNotice(`${n.title}: illustrative node. Actual graph data will come from stored evidence records.`)} className="cursor-pointer"><rect x={n.x} y={n.y} width={n.w} height={n.h} rx="12" fill={i===2?"#eef0ff":"#ffffff"} stroke={i===2?"#7082ed":"#d9dfeb"} strokeWidth={i===2?2:1.2}/><text x={n.x+12} y={n.y+27} fontSize="13" fontWeight="600" fill="#172033">{n.title}</text><text x={n.x+12} y={n.y+47} fontSize="10" fill="#65718a">{n.sub}</text></g>)}</svg></div><aside className="space-y-4"><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Relationship legend</div>{[["supports","bg-teal-500"],["contradicts","bg-red-500"],["qualifies","bg-amber-500"],["derived from","bg-indigo-500"],["depends on","bg-slate-500"]].map(([label,color])=><div key={label} className="mt-3 flex items-center gap-2 text-xs text-muted"><span className={`h-2 w-2 rounded-full ${color}`}/>{label}</div>)}</div><div className="rounded-xl border border-line p-4"><div className="text-sm font-semibold">Graph safeguards</div><ul className="mt-3 space-y-2 text-xs leading-5 text-muted"><li>• Explicit and inferred edges are distinguished.</li><li>• Missing relationships are not treated as evidence of absence.</li><li>• Source events trigger reassessment, not automatic invalidation.</li></ul></div><div className="rounded-xl bg-paper p-4"><div className="text-xs font-semibold">Next milestone</div><p className="mt-2 text-xs leading-5 text-muted">Persist papers, passages, claims and edge provenance before connecting the graph UI to a live database.</p></div></aside></div>}</section>}

        {view === "Source timeline" && <div className="grid gap-5 xl:grid-cols-[1fr_320px]"><section className="surface p-5 md:p-6"><div className="eyebrow">Temporal evidence lifecycle</div><h1 className="mt-2 text-xl font-semibold">Source timeline</h1><p className="mt-1 text-sm text-muted">Follow source events and the claims that may need reassessment.</p><div className="mt-6 space-y-0">{[{date:"18 Oct 2026 · Demo",title:"Research snapshot created",text:"An initial report version records the current evidence state.",tone:"blue"},{date:"Future integration",title:"Correction / retraction detected",text:"A source provider reports a post-publication event. No live monitor is connected yet.",tone:"amber"},{date:"Planned",title:"Affected claims queued for review",text:"Traverse dependency links and recompute assessments only for impacted claims.",tone:"slate"}].map((x,i)=><div key={x.title} className="flex gap-4"><div className="flex flex-col items-center"><span className={`mt-1 h-3 w-3 rounded-full ${x.tone==="blue"?"bg-accent":x.tone==="amber"?"bg-amber-500":"bg-slate-400"}`}/>{i<2&&<span className="my-2 min-h-20 w-px flex-1 bg-line"/>}</div><div className="pb-7"><div className="text-[10px] font-semibold uppercase tracking-wider text-muted">{x.date}</div><div className="mt-1 text-sm font-semibold">{x.title}</div><p className="mt-1 max-w-2xl text-xs leading-5 text-muted">{x.text}</p></div></div>)}</div><div className="rounded-xl border border-dashed border-line p-4 text-xs leading-5 text-muted">Future status integrations will store the provider, observed timestamp, source event, old/new values and verification state. This timeline is currently a designed workflow, not a live alert feed.</div></section><aside className="surface h-fit p-5"><div className="flex items-center gap-2 font-semibold"><GitCompare size={17} className="text-accent"/> Impact summary</div><div className="mt-4 rounded-xl bg-paper p-4"><div className="text-2xl font-semibold">—</div><div className="text-xs text-muted">Live source changes tracked</div></div><div className="mt-3 rounded-xl bg-paper p-4"><div className="text-2xl font-semibold">—</div><div className="text-xs text-muted">Affected claims computed</div></div><p className="mt-4 text-xs leading-5 text-muted">Counts remain unavailable until source-event ingestion and dependency traversal are implemented. No alerts are being sent.</p><button onClick={()=>setView("Evidence graph")} className="mt-4 flex items-center gap-2 text-xs font-semibold text-accent">Inspect dependencies <ArrowRight size={14}/></button></aside></div>}

        {view === "Hypothesis lab" && <div className="grid gap-5 xl:grid-cols-[1fr_320px]"><section className="surface p-5 md:p-6"><div className="eyebrow">Research discovery</div><h1 className="mt-2 text-xl font-semibold">Hypothesis lab</h1><p className="mt-1 text-sm leading-6 text-muted">Candidate opportunities should be grounded in sources, checked against prior work and treated as hypotheses—not claims of novelty.</p><div className="mt-6 grid gap-4 md:grid-cols-2">{[{title:"Unresolved contradiction",tag:"Evidence conflict",text:"Find claims with conflicting findings that may be explained by differences in population, measurement or setting."},{title:"Disconnected methods",tag:"Cross-domain connection",text:"Search for methods used in one research area but not yet observed in a related area in the retrieved corpus."},{title:"Coverage blind spot",tag:"Missing evidence",text:"Identify populations or outcomes with little retrieved evidence and make the corpus boundary explicit."},{title:"Replication opportunity",tag:"Validation design",text:"Identify important claims supported by limited or dependent evidence and propose a falsifiable replication question."}].map(card=><div key={card.title} className="rounded-xl border border-line p-4"><StatusPill tone="blue">{card.tag}</StatusPill><h3 className="mt-3 text-sm font-semibold">{card.title}</h3><p className="mt-2 text-xs leading-5 text-muted">{card.text}</p><div className="mt-4 text-[10px] text-muted">Template only · no discovery run executed</div></div>)}</div></section><aside className="surface h-fit p-5"><div className="flex items-center gap-2 font-semibold"><Microscope size={17} className="text-accent"/> Hypothesis checklist</div><ul className="mt-4 space-y-3 text-xs leading-5 text-muted"><li>• Locate the closest prior work.</li><li>• Cite the evidence that motivates the hypothesis.</li><li>• Explain alternative interpretations.</li><li>• Define what result would falsify it.</li><li>• Record human review before calling it novel.</li></ul><div className="mt-5 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">A missing link in a retrieved graph is not proof that no one has studied it.</div></aside></div>}
      </div>
      <footer className="border-t border-line bg-white px-5 py-4 text-[11px] text-muted md:px-8"><div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-2"><span>Chronicle · Major project prototype</span><span>Current UI uses illustrative demo data. Live research services are not connected.</span></div></footer>
    </main>

    {showNewRun && <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true" aria-labelledby="new-run-title"><div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between"><div><div className="eyebrow">New research run</div><h2 id="new-run-title" className="mt-2 text-xl font-semibold">What do you want to investigate?</h2><p className="mt-1 text-sm text-muted">The initial version records the UI request only.</p></div><button onClick={()=>setShowNewRun(false)} className="rounded-lg p-2 text-muted hover:bg-paper" aria-label="Close">×</button></div><label className="mt-5 block text-xs font-semibold">Research question</label><textarea value={query} onChange={e=>setQuery(e.target.value)} rows={4} className="field mt-2 resize-y" placeholder="e.g. What evidence supports the use of retrieval-augmented generation for scientific question answering?"/><label className="mt-4 block text-xs font-semibold">Mode</label><select value={mode} onChange={e=>setMode(e.target.value)} className="field mt-2"><option>Quick scan</option><option>Deep research</option><option>Academic review</option><option>Forensic analysis</option></select><div className="mt-5 flex justify-end gap-2"><button onClick={()=>setShowNewRun(false)} className="rounded-xl border border-line px-4 py-2.5 text-sm font-semibold">Cancel</button><button onClick={startResearch} disabled={submitting} className="rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{submitting ? "Creating..." : "Create run"}</button></div></div></div>}
  </div>;
}
