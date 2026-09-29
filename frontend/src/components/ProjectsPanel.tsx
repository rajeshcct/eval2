import { useEffect, useState } from "react";
import { fetchProjects } from "../lib/ws";
import type { Project } from "../lib/ws";
import type { ProjectTarget } from "../lib/types";

interface ProjectsPanelProps {
  /** Called when a project is picked — the app then opens that project's workspace
   * (its past sessions + the evaluation form pre-filled from its last session). */
  onOpen: (project: ProjectTarget) => void;
  /** Shown in the empty state so someone with no projects can jump to "Create new". */
  onCreateInstead: () => void;
}

/** With more projects than this, a filter box appears above the list. */
const FILTER_THRESHOLD = 6;

function sessionsLabel(count: number): string {
  return `${count} ${count === 1 ? "session" : "sessions"}`;
}

/**
 * The "Continue with existing project" list on the start page: every project with
 * its session count. Clicking one opens it. Sessions themselves are shown inside
 * the project, not here.
 */
export default function ProjectsPanel({ onOpen, onCreateInstead }: ProjectsPanelProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setProjects(await fetchProjects());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

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
        No projects yet.{" "}
        <button type="button" onClick={onCreateInstead} className="text-indigo-400 hover:text-indigo-300">
          Create your first project
        </button>
      </p>
    );
  }

  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? projects.filter(
        (p) => p.name.toLowerCase().includes(needle) || (p.description ?? "").toLowerCase().includes(needle),
      )
    : projects;

  return (
    <div className="flex flex-col gap-2">
      {projects.length > FILTER_THRESHOLD && (
        <input
          type="text"
          aria-label="Filter projects"
          placeholder="Filter projects…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      )}

      {visible.length === 0 && <p className="py-2 text-sm text-slate-500">No project matches “{filter}”.</p>}

      {visible.map((project) => (
        <button
          key={project.id}
          type="button"
          onClick={() => onOpen({ id: project.id, name: project.name })}
          className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-4 py-3 text-left transition-colors hover:border-slate-700"
        >
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-slate-200">{project.name}</span>
            {project.description && (
              <span className="block truncate text-xs text-slate-500">{project.description}</span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-3">
            <span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-0.5 font-mono text-xs text-slate-300">
              {sessionsLabel(project.session_count)}
            </span>
            <span aria-hidden className="text-sm text-indigo-400">
              →
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
