import { useEffect, useState } from "react";
import { deleteSession, fetchProjects, fetchSessions } from "../lib/ws";
import type { Project, SessionSummary } from "../lib/ws";

interface ProjectsPanelProps {
  /** Opens a session's report (same handler Past Sessions uses). */
  onViewReport: (sessionId: string) => void;
  /** Bump this number to make the panel reload (after a project is created or a
   * session is moved into or out of one). */
  refreshKey: number;
  /** Called after a session is deleted here, so other lists (Past Sessions) reload. */
  onChanged?: () => void;
}

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

/**
 * "Projects" — every project with its session count; click one to see the
 * sessions filed under it. Sits above Past Sessions on the New Evaluation
 * Session page. Sessions keep their own session_id; a project is only a group.
 */
export default function ProjectsPanel({ onViewReport, refreshKey, onChanged }: ProjectsPanelProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [projectRows, sessionRows] = await Promise.all([fetchProjects(), fetchSessions(200)]);
      setProjects(projectRows);
      setSessions(sessionRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // Runs on mount and again whenever the parent bumps refreshKey. Only the first
  // load shows the spinner, so a refresh doesn't make the list flicker.
  useEffect(() => {
    void load();
  }, [refreshKey]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this session and all its rounds? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteSession(id);
      const removed = sessions.find((s) => s.id === id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      // Drop the count straight away; the reload triggered by onChanged confirms it.
      if (removed?.project_id) {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === removed.project_id ? { ...p, session_count: Math.max(0, p.session_count - 1) } : p,
          ),
        );
      }
      onChanged?.();
    } catch (e) {
      alert(`Failed to delete session: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
        Loading projects…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
        {error}{" "}
        <button type="button" onClick={() => void load()} className="underline hover:no-underline">
          Retry
        </button>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <p className="py-2 text-sm text-slate-500">
        No projects yet. Create one in &ldquo;Organize this evaluation&rdquo; below.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {projects.map((project) => {
        const open = expandedId === project.id;
        const inProject = sessions.filter((s) => s.project_id === project.id);

        return (
          <div key={project.id} className="rounded-md border border-slate-800 bg-slate-900/30">
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setExpandedId(open ? null : project.id)}
              className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-slate-800/50"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span aria-hidden className="text-xs text-slate-500">
                  {open ? "▾" : "▸"}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-200">{project.name}</span>
                  {project.description && (
                    <span className="block truncate text-xs text-slate-500">{project.description}</span>
                  )}
                </span>
              </span>
              <span className="shrink-0 font-mono text-xs text-slate-400">
                {sessionsLabel(project.session_count)}
              </span>
            </button>

            {open && (
              <div className="flex flex-col gap-1 border-t border-slate-800 p-2">
                {inProject.length === 0 ? (
                  <p className="px-1 py-1 text-xs text-slate-500">No sessions in this project yet.</p>
                ) : (
                  inProject.map((session) => (
                    <div
                      key={session.id}
                      className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-md bg-slate-950/40 px-3 py-2"
                    >
                      <div className="min-w-0 flex-1 basis-40">
                        <p className="truncate text-sm text-slate-200" title={session.aut_description}>
                          {session.agent_name?.trim() || truncate(session.aut_description)}
                        </p>
                        <p className="truncate text-xs text-slate-500">{formatDateTime(session.started_at)}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                      {session.has_report ? (
                        <button
                          type="button"
                          onClick={() => onViewReport(session.id)}
                          className="shrink-0 rounded border border-indigo-800 px-2 py-0.5 text-xs text-indigo-300 hover:bg-indigo-950"
                        >
                          View Report
                        </button>
                      ) : (
                        <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-500">
                          No report
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => void handleDelete(session.id)}
                        disabled={deletingId === session.id}
                        className="rounded border border-red-900 px-2 py-0.5 text-xs text-red-400 hover:bg-red-950/60 disabled:opacity-50"
                      >
                        {deletingId === session.id ? "…" : "Delete"}
                      </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
