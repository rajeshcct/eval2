import { useEffect, useState } from "react";
import { fetchProjects } from "../lib/ws";
import type { Project } from "../lib/ws";
import type { ProjectTarget } from "../lib/types";
import SessionHistoryPanel from "./SessionHistoryPanel";

interface ProjectWorkspaceProps {
  projectId: string;
  onViewReport: (sessionId: string) => void;
  onRunNew: (project: ProjectTarget) => void;
  onProjectsChanged?: () => void;
}

export default function ProjectWorkspace({
  projectId,
  onViewReport,
  onRunNew,
  onProjectsChanged,
}: ProjectWorkspaceProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchProjects()
      .then((projects) => {
        const found = projects.find((p) => p.id === projectId) ?? null;
        setProject(found);
        if (!found) setError("Project not found.");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400" />
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="rounded-xl border border-red-800/40 bg-red-950/20 px-6 py-5 text-sm text-red-300">
          {error ?? "Project not found."}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Project header */}
      <div className="border-b border-slate-800/60 bg-gradient-to-b from-indigo-950/40 to-slate-900/20 px-6 py-6">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center justify-between gap-x-6 gap-y-4">
          <div className="flex min-w-0 flex-1 items-center gap-4">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-600/30 to-violet-600/10 shadow-lg shadow-indigo-950/40">
              <svg width="24" height="24" fill="none" viewBox="0 0 24 24" className="text-indigo-300">
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-indigo-300">Project</span>
                <span className="rounded-full border border-slate-700 bg-slate-900/60 px-2.5 py-0.5 font-mono text-[11px] text-slate-300">
                  {project.session_count} {project.session_count === 1 ? "session" : "sessions"}
                </span>
              </div>
              <h1 className="mt-0.5 truncate text-2xl font-bold tracking-tight text-slate-50">{project.name}</h1>
              {project.description && (
                <p className="mt-1 max-w-xl text-sm text-slate-400 line-clamp-2">{project.description}</p>
              )}
            </div>
          </div>

          <button
            onClick={() => onRunNew({ id: project.id, name: project.name })}
            className="shrink-0 flex items-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-900/40 transition-all hover:brightness-110"
          >
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24"><path d="M5 3l14 9-14 9V3z" fill="currentColor"/></svg>
            Run Evaluation
          </button>
        </div>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto w-full max-w-4xl">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300">Past Sessions</h2>
            <button
              onClick={() => setRefreshKey((k) => k + 1)}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
            >
              Refresh
            </button>
          </div>

          <SessionHistoryPanel
            onViewReport={onViewReport}
            onChanged={() => {
              setRefreshKey((k) => k + 1);
              onProjectsChanged?.();
            }}
            refreshKey={refreshKey}
            projectId={projectId}
          />
        </div>
      </div>
    </div>
  );
}
