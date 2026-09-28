import { useEffect, useState } from "react";
import { createProject, fetchProjects } from "../lib/ws";
import type { Project } from "../lib/ws";

/** The project the next-started session will be filed under. Only the id is
 * sent to the backend (as `project_id` on the start request); the name is kept
 * so the form can say where the session is going. */
export interface ProjectTarget {
  id: string;
  name: string;
}

interface OrganizeSessionPanelProps {
  target: ProjectTarget | null;
  onTargetChange: (target: ProjectTarget | null) => void;
  /** Called after a new project is created, so the Projects list can reload. */
  onProjectCreated?: () => void;
}

type Choice = "new" | "existing";

function sessionsLabel(count: number): string {
  return `${count} ${count === 1 ? "session" : "sessions"}`;
}

function ChoiceCard({
  selected,
  title,
  text,
  onSelect,
}: {
  selected: boolean;
  title: string;
  text: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`flex items-start gap-3 rounded-md border px-3 py-3 text-left transition-colors ${
        selected
          ? "border-indigo-500 bg-indigo-600/20"
          : "border-slate-700 bg-slate-900 hover:bg-slate-800"
      }`}
    >
      <span
        aria-hidden
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
          selected ? "border-indigo-400" : "border-slate-600"
        }`}
      >
        {selected && <span className="h-2 w-2 rounded-full bg-indigo-400" />}
      </span>
      <span className="min-w-0">
        <span className={`block text-sm font-medium ${selected ? "text-indigo-100" : "text-slate-200"}`}>
          {title}
        </span>
        <span className="mt-0.5 block text-xs text-slate-500">{text}</span>
      </span>
    </button>
  );
}

/**
 * "Organize this evaluation" — groups sessions into projects.
 *
 * Project -> Sessions -> Rounds. A session keeps its own unique session_id (and
 * stays reachable by it); the project is only an extra grouping pointer. This
 * panel sits under Past Sessions on the New Evaluation Session page and decides
 * where the session you are ABOUT to start will be filed: choosing or creating a
 * project sets `target`, which NewSessionForm sends as `project_id` when
 * "Start Evaluation" is pressed. Skipping (or never touching the panel) leaves
 * the session unfiled.
 */
export default function OrganizeSessionPanel({ target, onTargetChange, onProjectCreated }: OrganizeSessionPanelProps) {
  const [choice, setChoice] = useState<Choice | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(false);

  async function loadProjects() {
    setLoading(true);
    setLoadError(null);
    try {
      setProjects(await fetchProjects());
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadProjects();
  }, []);

  function selectChoice(next: Choice) {
    setChoice(next);
    setActionError(null);
    // Refresh the list whenever the picker is opened so counts and any project
    // created elsewhere are current.
    if (next === "existing") void loadProjects();
  }

  async function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) {
      setActionError("Project name is required.");
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      const project = await createProject(trimmed, description.trim() ? description.trim() : null);
      setProjects((prev) =>
        [...prev.filter((p) => p.id !== project.id), project].sort((a, b) => a.name.localeCompare(b.name)),
      );
      onTargetChange({ id: project.id, name: project.name });
      onProjectCreated?.();
      setName("");
      setDescription("");
      setChoice(null);
      setSkipped(false);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  function handleAddToExisting() {
    const project = projects.find((p) => p.id === selectedId);
    if (!project) {
      setActionError("Select a project first.");
      return;
    }
    onTargetChange({ id: project.id, name: project.name });
    setSelectedId(null);
    setChoice(null);
    setActionError(null);
    setSkipped(false);
  }

  function handleSkip() {
    onTargetChange(null);
    setChoice(null);
    setSelectedId(null);
    setActionError(null);
    setSkipped(true);
  }

  return (
    <section className="flex flex-col gap-4 border-t border-slate-800 pt-6" aria-labelledby="organize-title">
      <div>
        <h2 id="organize-title" className="text-sm font-medium text-slate-200">
          Organize this evaluation
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Choose where this session should be saved. It applies to the next evaluation you start, and it never
          changes the session ID.
        </p>
      </div>

      {target ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-900 bg-emerald-950/20 px-3 py-2 text-sm">
          <span className="text-slate-300">
            This session will be saved to <span className="font-medium text-emerald-300">{target.name}</span>.
          </span>
          <button
            type="button"
            onClick={() => onTargetChange(null)}
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Remove
          </button>
        </div>
      ) : (
        skipped && <p className="text-xs text-slate-500">This session won&apos;t be added to a project.</p>
      )}

      <div role="radiogroup" aria-label="Where to save this session" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ChoiceCard
          selected={choice === "new"}
          title="Create new project"
          text="Start a new group for this and future sessions."
          onSelect={() => selectChoice("new")}
        />
        <ChoiceCard
          selected={choice === "existing"}
          title="Add to existing project"
          text="File this session with related evaluations."
          onSelect={() => selectChoice("existing")}
        />
      </div>

      {choice === "new" && (
        <div className="flex flex-col gap-4 rounded-md border border-slate-800 bg-slate-900/30 p-4">
          <div className="flex flex-col gap-2">
            <label htmlFor="project_name" className="text-sm font-medium text-slate-200">
              Project name
            </label>
            <input
              id="project_name"
              type="text"
              maxLength={120}
              placeholder="Enter project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleCreate();
                }
              }}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="project_description" className="text-sm font-medium text-slate-200">
              Project description <span className="text-slate-500">(optional)</span>
            </label>
            <textarea
              id="project_description"
              rows={2}
              maxLength={500}
              placeholder="Brief description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
        </div>
      )}

      {choice === "existing" && (
        <div className="flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-900/30 p-4">
          <span className="text-sm font-medium text-slate-200">Select a project</span>

          {loading && projects.length === 0 ? (
            <div className="flex items-center gap-2 py-2 text-sm text-slate-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
              Loading projects…
            </div>
          ) : loadError ? (
            <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {loadError}{" "}
              <button type="button" onClick={() => void loadProjects()} className="underline hover:no-underline">
                Retry
              </button>
            </div>
          ) : projects.length === 0 ? (
            <p className="py-1 text-sm text-slate-500">No projects yet. Create one to get started.</p>
          ) : (
            <div role="radiogroup" aria-label="Existing projects" className="flex max-h-56 flex-col gap-1 overflow-y-auto">
              {projects.map((p) => {
                const selected = selectedId === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => {
                      setSelectedId(p.id);
                      setActionError(null);
                    }}
                    className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
                      selected
                        ? "border-indigo-500 bg-indigo-600/20"
                        : "border-slate-800 bg-slate-900/50 hover:bg-slate-800"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className={`block truncate text-sm font-medium ${selected ? "text-indigo-100" : "text-slate-200"}`}>
                        {p.name}
                      </span>
                      {p.description && (
                        <span className="block truncate text-xs text-slate-500">{p.description}</span>
                      )}
                    </span>
                    <span className="shrink-0 font-mono text-xs text-slate-400">{sessionsLabel(p.session_count)}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {actionError && (
        <div role="alert" className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {actionError}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {choice === "new" && (
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating || !name.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            {creating ? "Creating…" : "Create Project & Add Session"}
          </button>
        )}
        {choice === "existing" && (
          <button
            type="button"
            onClick={handleAddToExisting}
            disabled={!selectedId}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            Add Session to Project
          </button>
        )}
        <button
          type="button"
          onClick={handleSkip}
          className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
        >
          Skip for now
        </button>
      </div>
    </section>
  );
}
