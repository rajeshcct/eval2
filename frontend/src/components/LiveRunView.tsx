import { useMemo } from "react";
import { CATEGORY_ORDER, deriveLiveState } from "../lib/liveState";
import type { ProgressEvent } from "../lib/ws";
import DescriberSection from "./DescriberSection";
import OverallProgress from "./OverallProgress";
import CategoryCard from "./CategoryCard";
import ErrorBanner from "./ErrorBanner";

const LABELS: Record<string, string> = {
  functionality: "Functionality",
  security: "Security",
  compliance: "Compliance",
};

interface LiveRunViewProps {
  events: ProgressEvent[];
  /** Raw WS-level error (e.g. connection refused), distinct from a
   * well-formed `error` ProgressEvent — see src/lib/ws.ts. Shown above
   * everything else since it means the run may not be receiving events at
   * all. */
  socketError: string | null;
  /** Phase VI: true when the connection opened, then dropped mid-run —
   * before session_completed or a well-formed error event arrived. Distinct
   * from socketError; see App.tsx's handleStart for exactly how each is
   * derived. */
  disconnected: boolean;
  /** Starts a brand-new run with the same connection settings (there's no
   * resume/reconnect — see App.tsx's handleRetry). */
  onRetry: () => void;
  onCancel: () => void;
}

/**
 * Phase IV — the Live Run View. Watches a session round by round from the
 * flat `events` list (App.tsx owns the WebSocket and just accumulates
 * every ProgressEvent it receives; this component is a pure function of
 * that list via deriveLiveState). session_completed itself is handled by
 * App.tsx, which transitions to the Report view — this component only
 * needs to render everything up to that point.
 */
export default function LiveRunView({ events, socketError, disconnected, onRetry, onCancel }: LiveRunViewProps) {
  const live = useMemo(() => deriveLiveState(events), [events]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-50">Evaluation running…</h1>
        <button
          onClick={onCancel}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Cancel / back to form
        </button>
      </div>

      {disconnected && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-800 bg-amber-950/40 px-3 py-2 text-sm text-amber-200"
        >
          <span>
            Connection to the server was lost before this run finished. The evaluation may still be
            running on the server, but this browser stopped receiving updates.
          </span>
          <button
            type="button"
            onClick={onRetry}
            className="shrink-0 rounded-md border border-amber-700 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-900/60"
          >
            Retry (start a new run)
          </button>
        </div>
      )}
      {socketError && (
        <div role="alert" className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {socketError}
        </div>
      )}
      <ErrorBanner errors={live.errors} />

      <OverallProgress categories={live.categories} />

      <DescriberSection started={live.describerStarted} result={live.describer} />

      <div className="flex flex-col gap-4">
        {CATEGORY_ORDER.map((category) => (
          <CategoryCard key={category} state={live.categories[category]} label={LABELS[category]} />
        ))}
      </div>
    </div>
  );
}
