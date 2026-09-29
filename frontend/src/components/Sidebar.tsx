import { useEffect, useState } from "react";
import { fetchProjects, createProject } from "../lib/ws";
import type { Project } from "../lib/ws";
import type { AuthUser } from "../lib/auth";

export type SidebarView = "new-session" | "project" | "all-sessions";

interface SidebarProps {
  user: AuthUser;
  activeView: SidebarView;
  activeProjectId: string | null;
  onNav: (view: SidebarView, projectId?: string) => void;
  onLogout: () => void;
  refreshKey?: number;
}

export default function Sidebar({
  user,
  activeView,
  activeProjectId,
  onNav,
  onLogout,
  refreshKey,
}: SidebarProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [collapsed, setCollapsed] = useState(false);

  // Create project inline
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function loadProjects() {
    setLoadingProjects(true);
    try {
      const data = await fetchProjects();
      setProjects(data);
    } catch {
      // silently ignore; projects area shows its own state
    } finally {
      setLoadingProjects(false);
    }
  }

  useEffect(() => {
    void loadProjects();
  }, [refreshKey]);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const proj = await createProject(newName.trim(), null);
      setProjects((prev) => [proj, ...prev]);
      setNewName("");
      setShowCreate(false);
      onNav("project", proj.id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  const initials = (user.display_name || user.username)
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <aside
      className={`flex h-screen flex-col border-r border-slate-800/80 bg-[#080d1f] transition-all duration-200 ${
        collapsed ? "w-16" : "w-64"
      } shrink-0`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/60 px-4 py-4">
        {!collapsed && (
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600/20 border border-indigo-500/30">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-indigo-400">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <span className="text-sm font-semibold tracking-tight text-slate-100">EvalMind</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="rounded-md p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-300 transition-colors"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
          ) : (
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
          )}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
        {/* New Evaluation */}
        <NavItem
          icon={
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
          }
          label="New Evaluation"
          active={activeView === "new-session"}
          collapsed={collapsed}
          onClick={() => onNav("new-session")}
        />

        {/* All Sessions */}
        <NavItem
          icon={
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="2"/><rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="2"/><rect x="14" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="2"/><rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="2"/></svg>
          }
          label="All Sessions"
          active={activeView === "all-sessions"}
          collapsed={collapsed}
          onClick={() => onNav("all-sessions")}
        />

        {/* Projects Section */}
        {!collapsed && (
          <div className="mt-4 mb-1 flex items-center justify-between px-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">Projects</span>
            <button
              onClick={() => { setShowCreate((v) => !v); setCreateError(null); setNewName(""); }}
              className="rounded p-0.5 text-slate-600 hover:bg-slate-800 hover:text-slate-400 transition-colors"
              title="Create new project"
            >
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
            </button>
          </div>
        )}

        {/* Inline project create */}
        {!collapsed && showCreate && (
          <div className="mx-1 mb-2 flex flex-col gap-1.5 rounded-lg border border-slate-700/60 bg-slate-800/40 p-2">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); if (e.key === "Escape") setShowCreate(false); }}
              placeholder="Project name…"
              className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            />
            {createError && <p className="text-[10px] text-red-400">{createError}</p>}
            <div className="flex gap-1">
              <button
                onClick={() => void handleCreate()}
                disabled={creating || !newName.trim()}
                className="flex-1 rounded-md bg-indigo-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {creating ? "…" : "Create"}
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Project list */}
        {collapsed ? (
          /* Collapsed: just the folder icon, clicking opens first project */
          <button
            onClick={() => setCollapsed(false)}
            className="flex w-full items-center justify-center rounded-lg p-2 text-slate-500 hover:bg-slate-800/60 hover:text-slate-300 transition-colors"
            title="Projects"
          >
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        ) : loadingProjects ? (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500" />
            Loading…
          </div>
        ) : projects.length === 0 ? (
          <p className="px-3 py-2 text-xs text-slate-600">No projects yet.</p>
        ) : (
          projects.map((proj) => (
            <button
              key={proj.id}
              onClick={() => onNav("project", proj.id)}
              className={`group flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors ${
                activeView === "project" && activeProjectId === proj.id
                  ? "bg-indigo-600/20 text-indigo-200"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              <span className="shrink-0">
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">{proj.name}</span>
              <span className="ml-auto shrink-0 rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500 group-hover:text-slate-400">
                {proj.session_count}
              </span>
            </button>
          ))
        )}
      </nav>

      {/* User footer */}
      <div className="border-t border-slate-800/60 p-3">
        <div className={`flex items-center gap-3 rounded-lg p-2 ${collapsed ? "justify-center" : ""}`}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-bold text-white shadow-sm">
            {initials}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-200">{user.display_name || user.username}</p>
              <p className="truncate text-[10px] text-slate-500">@{user.username}</p>
            </div>
          )}
          {!collapsed && (
            <button
              onClick={onLogout}
              title="Sign out"
              className="shrink-0 rounded-md p-1.5 text-slate-600 hover:bg-slate-800 hover:text-red-400 transition-colors"
            >
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

function NavItem({
  icon,
  label,
  active,
  collapsed,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
        active
          ? "bg-indigo-600/20 text-indigo-200"
          : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
      } ${collapsed ? "justify-center px-0" : ""}`}
    >
      <span className={`shrink-0 ${active ? "text-indigo-400" : ""}`}>{icon}</span>
      {!collapsed && <span className="text-sm font-medium">{label}</span>}
    </button>
  );
}
