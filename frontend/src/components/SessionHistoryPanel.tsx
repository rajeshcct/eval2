import { useEffect, useState } from "react";
import { fetchSessions, deleteSession } from "../lib/ws";
import type { SessionSummary } from "../lib/ws";

interface SessionHistoryPanelProps {
  /** Called when the user wants to view a report for a past session. */
  onViewReport: (sessionId: string) => void;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function truncate(text: string, max = 60): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

export default function SessionHistoryPanel({ onViewReport }: SessionHistoryPanelProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
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

  useEffect(() => {
    void load();
  }, []);

  async function handleDelete(id: string) {
    if (!confirm("Delete this session and all its rounds? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
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

  return (
    <div className="flex flex-col gap-1">
      {sessions.map((session) => (
        <div
          key={session.id}
          className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-900/30 px-3 py-2"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-200" title={session.aut_description}>
              {truncate(session.aut_description)}
            </p>
            <p className="text-xs text-slate-500">{formatDateTime(session.started_at)}</p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {session.has_report ? (
              <span className="rounded bg-emerald-950 px-1.5 py-0.5 text-xs text-emerald-400">
                Done
              </span>
            ) : (
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-500">
                No report
              </span>
            )}

            {session.has_report && (
              <button
                type="button"
                onClick={() => onViewReport(session.id)}
                className="rounded border border-indigo-800 px-2 py-0.5 text-xs text-indigo-300 hover:bg-indigo-950"
              >
                View
              </button>
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
      ))}
    </div>
  );
}
