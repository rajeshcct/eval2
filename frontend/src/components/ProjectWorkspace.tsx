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
      <div className="border-b border-slate-800/60 bg-slate-900/30 px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-indigo-500/30 bg-indigo-600/10">
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24" className="text-indigo-400">
                  <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Project</span>
            </div>
            <h1 className="text-xl font-bold text-slate-50 truncate">{project.name}</h1>
            {project.description && (
              <p className="mt-1 text-sm text-slate-400 line-clamp-2">{project.description}</p>
            )}
            <p className="mt-1.5 text-xs text-slate-600">
              {project.session_count} {project.session_count === 1 ? "session" : "sessions"}
            </p>
          </div>

          <button
            onClick={() => onRunNew({ id: project.id, name: project.name })}
            className="shrink-0 flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-500"
          >
            <svg width="15" height="15" fill="none" viewBox="0 0 24 24"><path d="M5 3l14 9-14 9V3z" fill="currentColor"/></svg>
            Run Evaluation
          </button>
        </div>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl">
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
