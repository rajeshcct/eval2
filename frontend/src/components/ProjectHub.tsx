import { useState } from "react";
import { createProject } from "../lib/ws";
import type { ProjectTarget } from "../lib/types";
import ProjectsPanel from "./ProjectsPanel";

interface ProjectHubProps {
  /** Called once a project is chosen (or just created) — the app then opens that
   * project's workspace: its past sessions plus the pre-filled evaluation form. */
  onOpenProject: (project: ProjectTarget) => void;
}

type Choice = "new" | "existing";

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
      className={`flex items-start gap-3 rounded-lg border px-4 py-4 text-left transition-colors ${
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
 * The default (start) page section: every evaluation lives in a project, so the
 * first thing to do is either create a new project or continue with an existing
 * one. Creating a project opens its (blank) evaluation form straight away;
 * picking an existing project opens its past sessions and a form pre-filled from
 * its last session.
 */
export default function ProjectHub({ onOpenProject }: ProjectHubProps) {
  const [choice, setChoice] = useState<Choice | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  function selectChoice(next: Choice) {
    setChoice(next);
    setActionError(null);
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
      onOpenProject({ id: project.id, name: project.name });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      setCreating(false);
    }
  }

  return (
    <section
      className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6"
      aria-labelledby="project-hub-title"
    >
      <div>
        <h2
          id="project-hub-title"
          className="em-sec em-sec--org font-mono text-[11px] uppercase tracking-[0.2em] text-slate-400"
        >
          Project
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Every evaluation belongs to a project. Create a new one, or continue with an existing project to see its
          past sessions and run another evaluation with the same settings.
        </p>
      </div>

      <div role="radiogroup" aria-label="Project" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ChoiceCard
          selected={choice === "new"}
          title="Create new project"
          text="Start a fresh project and configure its first evaluation."
          onSelect={() => selectChoice("new")}
        />
        <ChoiceCard
          selected={choice === "existing"}
          title="Continue with existing project"
          text="See past sessions and run a new evaluation, pre-filled from the last one."
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
              autoFocus
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
          <div>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating || !name.trim()}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {creating ? "Creating…" : "Create Project & Continue"}
            </button>
          </div>
        </div>
      )}

      {choice === "existing" && (
        <div className="flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-900/30 p-4">
          <span className="text-sm font-medium text-slate-200">Select a project</span>
          <ProjectsPanel onOpen={onOpenProject} onCreateInstead={() => selectChoice("new")} />
        </div>
      )}

      {actionError && (
        <div role="alert" className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {actionError}
        </div>
      )}
    </section>
  );
}
