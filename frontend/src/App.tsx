import { useCallback, useEffect, useRef, useState } from "react";
import NewSessionForm from "./components/NewSessionForm";
import LiveRunView from "./components/LiveRunView";
import ReportView from "./components/ReportView";
import LoginPage from "./components/LoginPage";
import Sidebar from "./components/Sidebar";
import ProjectWorkspace from "./components/ProjectWorkspace";
import SessionHistoryPanel from "./components/SessionHistoryPanel";
import { fetchSessionReport, startRun, sendWsMessage, fetchProjects, createProject } from "./lib/ws";
import type { FinalReport, ProgressEvent, DescriptionComparisonResult, Project } from "./lib/ws";
import type { SessionStartRequest, ProjectTarget } from "./lib/types";
import { getStoredToken, getStoredUser, fetchMe, logout as authLogout } from "./lib/auth";
import type { AuthUser } from "./lib/auth";
import type { SidebarView } from "./components/Sidebar";

// ---------------------------------------------------------------------------
// ProjectPickerStep — shown when the user clicks "New Evaluation" before
// a project has been chosen. Lists existing projects + create-new form.
// ---------------------------------------------------------------------------
function ProjectPickerStep({
  onSelect,
  onRefreshSidebar,
}: {
  onSelect: (project: ProjectTarget) => void;
  onRefreshSidebar: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchProjects()
      .then(setProjects)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const proj = await createProject(newName.trim(), newDesc.trim() || null);
      onRefreshSidebar();
      onSelect({ id: proj.id, name: proj.name });
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
      setCreating(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Create new project */}
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-5">
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="flex w-full items-center gap-3 text-left"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-dashed border-indigo-500/40 bg-indigo-600/10">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" className="text-indigo-400">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-200">Create new project</p>
              <p className="text-xs text-slate-500">Start a fresh project for this evaluation</p>
            </div>
          </button>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm font-semibold text-slate-200">New project</p>
            <input
              autoFocus
              type="text"
              placeholder="Project name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); }}
              className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50"
            />
            <textarea
              rows={2}
              placeholder="Description (optional)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50"
            />
            {createError && <p className="text-xs text-red-400">{createError}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => void handleCreate()}
                disabled={creating || !newName.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-500 disabled:opacity-50 transition-colors"
              >
                {creating ? "Creating…" : "Create & Continue"}
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewName(""); setNewDesc(""); setCreateError(null); }}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-400 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Existing projects */}
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Or continue with an existing project</p>
        {loading && (
          <div className="flex items-center gap-2 py-3 text-sm text-slate-500">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500" /> Loading projects…
          </div>
        )}
        {error && <p className="rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-2 text-sm text-red-400">{error}</p>}
        {!loading && !error && projects.length === 0 && (
          <p className="py-2 text-sm text-slate-600">No existing projects yet.</p>
        )}
        {projects.map((proj) => (
          <button
            key={proj.id}
            onClick={() => onSelect({ id: proj.id, name: proj.name })}
            className="flex w-full items-center gap-4 rounded-xl border border-slate-700/60 bg-slate-900/40 px-5 py-4 text-left transition-all hover:border-indigo-500/40 hover:bg-indigo-600/5"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-800">
              <svg width="15" height="15" fill="none" viewBox="0 0 24 24" className="text-slate-400">
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-200">{proj.name}</p>
              {proj.description && <p className="truncate text-xs text-slate-500">{proj.description}</p>}
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-0.5 font-mono text-xs text-slate-400">
                {proj.session_count} {proj.session_count === 1 ? "session" : "sessions"}
              </span>
              <svg width="16" height="16" fill="none" viewBox="0 0 24 24" className="text-indigo-400">
                <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}


type AppState = "form" | "live" | "report";
type ReportStatus = "loading" | "loaded" | "error";

const SESSION_ID_PARAM = "session_id";

function readSessionIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get(SESSION_ID_PARAM);
}

function setSessionIdInUrl(sessionId: string | null) {
  const url = new URL(window.location.href);
  if (sessionId) {
    url.searchParams.set(SESSION_ID_PARAM, sessionId);
  } else {
    url.searchParams.delete(SESSION_ID_PARAM);
  }
  window.history.replaceState(null, "", url.toString());
}

export default function App() {
  // ── Auth ──────────────────────────────────────────────────────────────────
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecking, setAuthChecking] = useState(true);

  useEffect(() => {
    const stored = getStoredUser();
    const token = getStoredToken();
    if (stored && token) {
      // Optimistically set the user, then verify with the server
      setUser(stored);
      setAuthChecking(false);
      fetchMe().then((me) => {
        if (!me) {
          setUser(null);
        }
      });
    } else {
      setAuthChecking(false);
    }
  }, []);

  function handleAuth(u: AuthUser) {
    setUser(u);
  }

  async function handleLogout() {
    await authLogout();
    setUser(null);
    setSidebarView("new-session");
    setActiveProjectId(null);
    handleReset();
  }

  // ── Sidebar navigation ─────────────────────────────────────────────────
  const [sidebarView, setSidebarView] = useState<SidebarView>("new-session");
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);

  function handleNav(view: SidebarView, projectId?: string) {
    setSidebarView(view);
    setActiveProjectId(projectId ?? null);
    // If navigating away from a live run or report, reset cleanly
    if (appState !== "form") {
      handleReset();
    }
  }

  // ── Evaluation state ───────────────────────────────────────────────────
  const [appState, setAppState] = useState<AppState>("form");
  const [starting, setStarting] = useState(false);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [finalReport, setFinalReport] = useState<FinalReport | null>(null);
  const [reportStatus, setReportStatus] = useState<ReportStatus>("loaded");
  const [reportError, setReportError] = useState<string | null>(null);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [presetProject, setPresetProject] = useState<ProjectTarget | null>(null);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [mismatchData, setMismatchData] = useState<DescriptionComparisonResult | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const lastRequestRef = useRef<SessionStartRequest | null>(null);
  const hasOpenedRef = useRef(false);
  const intentionalCloseRef = useRef(false);
  const terminalEventReceivedRef = useRef(false);

  const loadReportById = useCallback(async (sessionId: string) => {
    setAppState("report");
    setReportStatus("loading");
    setReportError(null);
    setPendingSessionId(sessionId);
    setSessionIdInUrl(sessionId);
    try {
      const report = await fetchSessionReport(sessionId);
      setFinalReport(report);
      setReportStatus("loaded");
    } catch (e) {
      setReportStatus("error");
      setReportError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // On first load, handle ?session_id=... deep-link
  useEffect(() => {
    const existing = readSessionIdFromUrl();
    if (existing) {
      loadReportById(existing);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEvent = useCallback((event: ProgressEvent) => {
    if ((event as { type: string }).type === "ping") return;
    // eslint-disable-next-line no-console
    console.log("[ws:/ws/run]", event.type, event.data);
    if (event.type === "session_completed" || event.type === "error") {
      terminalEventReceivedRef.current = true;
    }
    setEvents((prev) => [...prev, event]);
    if (event.type === "capability_mismatch") {
      setMismatchData(event.data as DescriptionComparisonResult);
    }
    if (event.type === "session_completed") {
      setFinalReport(event.data);
      setReportStatus("loaded");
      setSessionIdInUrl(event.data.session_id);
      setAppState("report");
      setSidebarRefreshKey((k) => k + 1); // refresh project session counts
    }
  }, []);

  function handleStart(request: SessionStartRequest) {
    setSocketError(null);
    setDisconnected(false);
    setEvents([]);
    setFinalReport(null);
    setReportStatus("loaded");
    setReportError(null);
    setPendingSessionId(null);
    setStarting(true);
    lastRequestRef.current = request;
    hasOpenedRef.current = false;
    intentionalCloseRef.current = false;
    terminalEventReceivedRef.current = false;
    setMismatchData(null);

    const socket = startRun(request, {
      onEvent: handleEvent,
      onOpen: () => {
        hasOpenedRef.current = true;
        setStarting(false);
        setAppState("live");
      },
      onSocketError: () => {
        setStarting(false);
        if (!hasOpenedRef.current) {
          setSocketError("Could not reach the backend — is it running at the configured URL?");
        }
      },
      onClose: () => {
        socketRef.current = null;
        if (hasOpenedRef.current && !intentionalCloseRef.current && !terminalEventReceivedRef.current) {
          setDisconnected(true);
        }
      },
    });
    socketRef.current = socket;
  }

  function handleRetry() {
    if (lastRequestRef.current) {
      handleStart(lastRequestRef.current);
    }
  }

  function handleReset() {
    intentionalCloseRef.current = true;
    socketRef.current?.close();
    socketRef.current = null;
    setAppState("form");
    setEvents([]);
    setFinalReport(null);
    setSocketError(null);
    setDisconnected(false);
    setMismatchData(null);
    setReportStatus("loaded");
    setReportError(null);
    setPendingSessionId(null);
    setSessionIdInUrl(null);
    setPresetProject(null);
  }

  function handleStartAnother(project: ProjectTarget | null) {
    handleReset();
    setPresetProject(project);
    setSidebarView("new-session");
  }

  // Called by ProjectWorkspace "Run Evaluation" button
  function handleRunFromProject(project: ProjectTarget) {
    handleReset();
    setPresetProject(project);
    setSidebarView("new-session");
    setAppState("form");
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (authChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400" />
      </div>
    );
  }

  if (!user) {
    return <LoginPage onAuth={handleAuth} />;
  }

  // ── Authenticated layout: Sidebar + Main area ─────────────────────────
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        user={user}
        activeView={sidebarView}
        activeProjectId={activeProjectId}
        onNav={handleNav}
        onLogout={() => void handleLogout()}
        refreshKey={sidebarRefreshKey}
      />

      {/* Main content area */}
      <main className="flex flex-1 flex-col overflow-hidden">

        {/* ── Live Run ─────────────────────────────────────────────────── */}
        {appState === "live" && (
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <LiveRunView
              events={events}
              socketError={socketError}
              disconnected={disconnected}
              onRetry={handleRetry}
              onCancel={handleReset}
              mismatchData={mismatchData}
              onMismatchResponse={(action: "continue" | "abort") => {
                if (socketRef.current) sendWsMessage(socketRef.current, { action });
                setMismatchData(null);
              }}
            />
          </div>
        )}

        {/* ── Report loading / error ──────────────────────────────────── */}
        {appState === "report" && reportStatus === "loading" && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400" aria-hidden />
            <p className="text-sm text-slate-400">
              Loading report{pendingSessionId ? ` for session ${pendingSessionId}` : ""}…
            </p>
          </div>
        )}

        {appState === "report" && reportStatus === "error" && (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
            <div role="alert" className="rounded-xl border border-red-800/40 bg-red-950/20 px-6 py-4 text-sm text-red-300">
              Could not load report{pendingSessionId ? ` for session_id "${pendingSessionId}"` : ""}.
              {reportError ? ` ${reportError}` : ""}
            </div>
            <button onClick={handleReset} className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
              Back
            </button>
          </div>
        )}

        {/* ── Report ───────────────────────────────────────────────────── */}
        {appState === "report" && reportStatus === "loaded" && finalReport && (
          <div className="flex-1 overflow-y-auto">
            <ReportView report={finalReport} onReset={handleReset} onStartAnother={handleStartAnother} />
          </div>
        )}

        {/* ── Form views (only when not live/reporting) ─────────────────────── */}
        {appState === "form" && (
          <>
            {/* New Evaluation — project picker first, then form */}
            {sidebarView === "new-session" && (
              <div className="flex flex-1 flex-col overflow-hidden">
                {socketError && (
                  <div role="alert" className="mx-6 mt-4 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
                    {socketError}
                  </div>
                )}

                {/* Step 1: No project chosen yet → show project picker */}
                {!presetProject ? (
                  <div className="flex-1 overflow-y-auto px-6 py-8">
                    <div className="mx-auto max-w-2xl">
                      <div className="mb-8">
                        <p className="text-[10px] font-semibold uppercase tracking-widest text-indigo-400">New Evaluation</p>
                        <h1 className="mt-1 text-2xl font-bold text-slate-50">Choose a project</h1>
                        <p className="mt-1 text-sm text-slate-400">
                          Every evaluation belongs to a project. Pick an existing one or create a new project to continue.
                        </p>
                      </div>
                      <ProjectPickerStep
                        onSelect={setPresetProject}
                        onRefreshSidebar={() => setSidebarRefreshKey((k) => k + 1)}
                      />
                    </div>
                  </div>
                ) : (
                  /* Step 2: Project chosen → show the evaluation form */
                  <div className="flex-1 overflow-y-auto">
                    {/* Breadcrumb / project bar */}
                    <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-slate-800/60 bg-slate-950/80 px-6 py-3 backdrop-blur-sm">
                      <button
                        onClick={() => setPresetProject(null)}
                        className="flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
                      >
                        <svg width="12" height="12" fill="none" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
                        Change project
                      </button>
                      <div className="flex items-center gap-2">
                        <svg width="13" height="13" fill="none" viewBox="0 0 24 24" className="text-indigo-400"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        <span className="text-sm font-medium text-slate-200">{presetProject.name}</span>
                      </div>
                    </div>
                    <div className="mx-auto w-full max-w-4xl px-6 py-6">
                      <NewSessionForm
                        onStart={handleStart}
                        onLoadReport={loadReportById}
                        disabled={starting}
                        initialProject={presetProject}
                        hideHeader
                      />
                    </div>
                  </div>
                )}
              </div>
            )}


            {/* All Sessions */}
            {sidebarView === "all-sessions" && (
              <div className="flex-1 overflow-y-auto px-6 py-8">
                <div className="mx-auto max-w-3xl">
                  <div className="mb-6">
                    <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">History</p>
                    <h1 className="mt-1 text-2xl font-bold text-slate-50">All Sessions</h1>
                    <p className="mt-1 text-sm text-slate-400">Browse every evaluation run across all projects.</p>
                  </div>
                  <SessionHistoryPanel
                    onViewReport={loadReportById}
                    onChanged={() => setSidebarRefreshKey((k) => k + 1)}
                  />
                </div>
              </div>
            )}

            {/* Project workspace */}
            {sidebarView === "project" && activeProjectId && (
              <ProjectWorkspace
                projectId={activeProjectId}
                onViewReport={loadReportById}
                onRunNew={handleRunFromProject}
                onProjectsChanged={() => setSidebarRefreshKey((k) => k + 1)}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
