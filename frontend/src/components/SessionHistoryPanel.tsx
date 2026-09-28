import { useEffect, useRef, useState } from "react";
import { assignSessionProject, deleteSession, fetchProjects, fetchSessions } from "../lib/ws";
import type { Project, SessionSummary } from "../lib/ws";

interface SessionHistoryPanelProps {
  /** Opens a session's report */
  onViewReport: (sessionId: string) => void;
  /** Called after a session is deleted or moved into/out of a project, so the
   * Projects list can reload. */
  onChanged?: () => void;
  /** Bump this number to make the list reload (e.g. after a delete elsewhere). */
  refreshKey?: number;
}

/** How many rows show before "View all sessions →" reveals the rest. */
const INITIAL_VISIBLE = 5;

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function truncate(text: string, max = 60): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function sessionsLabel(count: number): string {
  return `${count} ${count === 1 ? "session" : "sessions"}`;
}

export default function SessionHistoryPanel({ onViewReport, onChanged, refreshKey }: SessionHistoryPanelProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  // "Add to project" — one row at a time can have its picker open.
  const [assigningId, setAssigningId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [pickedId, setPickedId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // `silent` reloads keep the current rows on screen instead of flashing the
  // "Loading…" state, so an open picker or an expanded list isn't disturbed.
  async function load(silent = false) {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await fetchSessions(50);
      setSessions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const loadedOnce = useRef(false);
  useEffect(() => {
    void load(loadedOnce.current);
    loadedOnce.current = true;
  }, [refreshKey]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this session and all its rounds? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      onChanged?.();
    } catch (e) {
      alert(`Failed to delete session: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeletingId(null);
    }
  }

  async function loadProjects() {
    setProjectsLoading(true);
    setProjectsError(null);
    try {
      setProjects(await fetchProjects());
    } catch (e) {
      setProjectsError(e instanceof Error ? e.message : String(e));
    } finally {
      setProjectsLoading(false);
    }
  }

  function openAssign(session: SessionSummary) {
    setAssigningId(session.id);
    setPickedId(session.project_id ?? "");
    setSaveError(null);
    // Fetched fresh each time the picker opens so new projects and counts show up.
    void loadProjects();
  }

  function closeAssign() {
    setAssigningId(null);
    setSaveError(null);
  }

  async function handleSaveAssign(session: SessionSummary) {
    const projectId = pickedId || null; // "" = take the session out of its project
    setSaving(true);
    setSaveError(null);
    try {
      await assignSessionProject(session.id, projectId);
      const project = projects.find((p) => p.id === projectId);
      setSessions((prev) =>
        prev.map((s) =>
          s.id === session.id ? { ...s, project_id: projectId, project_name: project ? project.name : null } : s,
        ),
      );
      setAssigningId(null);
      onChanged?.();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
        Loading past sessions…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
        {error}{" "}
        <button
          type="button"
          onClick={() => void load()}
          className="underline hover:no-underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <p className="py-2 text-sm text-slate-500">No past sessions found.</p>
    );
  }

  const visible = showAll ? sessions : sessions.slice(0, INITIAL_VISIBLE);
  const hasMore = sessions.length > INITIAL_VISIBLE;

  return (
    <div className="flex flex-col gap-1">
      {visible.map((session) => {
        // Prefer the agent's display name; older sessions have none, so fall
        // back to the (truncated) capability description as before.
        const title = session.agent_name?.trim() || truncate(session.aut_description);
        const isAssigning = assigningId === session.id;

        return (
          <div
            key={session.id}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-md border border-slate-800 bg-slate-900/30 px-3 py-2"
          >
            <div className="min-w-0 flex-1 basis-40">
              <p className="truncate text-sm font-medium text-slate-200" title={session.aut_description}>
                {title}
              </p>
              <p className="truncate text-xs text-slate-500">
                {formatDateTime(session.started_at)}
                {session.project_name ? ` · ${session.project_name}` : ""}
              </p>
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {session.has_report ? (
                <button
                  type="button"
                  onClick={() => onViewReport(session.id)}
                  className="rounded border border-indigo-800 px-2 py-0.5 text-xs text-indigo-300 hover:bg-indigo-950"
                >
                  View Report
                </button>
              ) : (
                <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-500">
                  No report
                </span>
              )}

              <button
                type="button"
                onClick={() => (isAssigning ? closeAssign() : openAssign(session))}
                aria-expanded={isAssigning}
                className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                {session.project_id ? "Change project" : "Add to project"}
              </button>

              <button
                type="button"
                onClick={() => void handleDelete(session.id)}
                disabled={deletingId === session.id}
                className="rounded border border-red-900 px-2 py-0.5 text-xs text-red-400 hover:bg-red-950/60 disabled:opacity-50"
              >
                {deletingId === session.id ? "…" : "Delete"}
              </button>
            </div>

            {isAssigning && (
              <div className="flex basis-full flex-col gap-2 border-t border-slate-800 pt-2">
                {projectsLoading && projects.length === 0 ? (
                  <p className="text-xs text-slate-400">Loading projects…</p>
                ) : projectsError ? (
                  <p className="text-xs text-red-300">
                    {projectsError}{" "}
                    <button type="button" onClick={() => void loadProjects()} className="underline hover:no-underline">
                      Retry
                    </button>
                  </p>
                ) : projects.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    No projects yet. Create one in &ldquo;Organize this evaluation&rdquo; below, then come back.
                  </p>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor={`assign_${session.id}`} className="text-xs text-slate-400">
                      Project
                    </label>
                    <select
                      id={`assign_${session.id}`}
                      value={pickedId}
                      onChange={(e) => setPickedId(e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    >
                      <option value="">No project</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({sessionsLabel(p.session_count)})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void handleSaveAssign(session)}
                      disabled={saving || pickedId === (session.project_id ?? "")}
                      className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    >
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={closeAssign}
                      className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                  </div>
                )}
                {saveError && (
                  <p role="alert" className="text-xs text-red-300">
                    {saveError}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}

      {hasMore && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-1 self-start text-sm text-indigo-400 hover:text-indigo-300"
        >
          {showAll ? "Show fewer" : "View all sessions →"}
        </button>
      )}
    </div>
  );
}
