import { useMemo } from "react";
import { CATEGORY_ORDER, deriveLiveState } from "../lib/liveState";
import type { ProgressEvent } from "../lib/ws";
import type { DescriptionComparisonResult } from "../lib/ws";
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
  /** When non-null, the user's chatbot description and the AUT's self-report
   * diverged — show a confirmation modal with the details. */
  mismatchData: DescriptionComparisonResult | null;
  /** User's response to the mismatch warning. */
  onMismatchResponse: (action: "continue" | "abort") => void;
}

/**
 * Phase IV — the Live Run View. Watches a session round by round from the
 * flat `events` list (App.tsx owns the WebSocket and just accumulates
 * every ProgressEvent it receives; this component is a pure function of
 * that list via deriveLiveState). session_completed itself is handled by
 * App.tsx, which transitions to the Report view — this component only
 * needs to render everything up to that point.
 */
export default function LiveRunView({ events, socketError, disconnected, onRetry, onCancel, mismatchData, onMismatchResponse }: LiveRunViewProps) {
  const live = useMemo(() => deriveLiveState(events), [events]);

  return (
    <div className="relative isolate mx-auto flex w-full max-w-[1450px] flex-col gap-6">
      {/* decorative glow behind the header (presentation only) */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-16 left-1/2 -z-10 h-72 w-2/3 -translate-x-1/2 rounded-full bg-gradient-to-r from-indigo-600/20 via-fuchsia-600/15 to-sky-600/20 blur-3xl"
      />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="relative flex h-2.5 w-2.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
            </span>
            <span className="font-mono text-[11px] uppercase tracking-[0.3em] text-emerald-400">Live</span>
            <span className="font-mono text-[11px] uppercase tracking-[0.3em] text-slate-500">
              EvalMind — Agent under test
            </span>
          </div>
          <h1 className="mt-2 bg-gradient-to-r from-slate-50 via-indigo-200 to-fuchsia-200 bg-clip-text text-3xl font-semibold tracking-tight text-transparent sm:text-4xl">
            Evaluation running…
          </h1>
          <p className="mt-2 text-base text-slate-400">
            Your agent is being tested for functionality, security and compliance. Results stream in round by
            round.
          </p>
        </div>
        <button
          onClick={onCancel}
          className="rounded-lg border border-slate-700 bg-slate-900/60 px-4 py-2 text-sm font-medium text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800"
        >
          Cancel / back to form
        </button>
      </div>

      {/* Mismatch confirmation modal */}
      {mismatchData && (
        <div className="mx-auto w-full max-w-4xl rounded-lg border-2 border-amber-500/60 bg-gradient-to-b from-amber-950/50 to-slate-900/90 p-5 shadow-lg shadow-amber-900/20">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-600/20 text-xl">
              ⚠️
            </div>
            <div>
              <h2 className="text-lg font-semibold text-amber-200">Description Mismatch Detected</h2>
              <p className="text-sm text-amber-300/80">
                Your description and the chatbot's own answer differ (similarity: {mismatchData.similarity_score}/10)
              </p>
            </div>
          </div>

          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-slate-700 bg-slate-900/60 p-3">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-cyan-400">
                What you said
              </p>
              <p className="text-sm text-slate-300">{mismatchData.user_description_summary}</p>
            </div>
            <div className="rounded-md border border-slate-700 bg-slate-900/60 p-3">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-indigo-400">
                What the chatbot said
              </p>
              <p className="text-sm text-slate-300">{mismatchData.aut_self_report_summary}</p>
            </div>
          </div>

          {mismatchData.mismatch_notes && (
            <div className="mb-4 rounded-md border border-amber-800/40 bg-amber-950/30 px-3 py-2">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-amber-400">
                Key differences
              </p>
              <p className="text-sm text-amber-200/80">{mismatchData.mismatch_notes}</p>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => onMismatchResponse("abort")}
              className="rounded-md border border-red-700 bg-red-950/30 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-900/40"
            >
              Abort evaluation
            </button>
            <button
              type="button"
              onClick={() => onMismatchResponse("continue")}
              className="rounded-md border border-amber-600 bg-amber-600/20 px-4 py-2 text-sm font-medium text-amber-200 transition-colors hover:bg-amber-600/30"
            >
              Continue with mismatch
            </button>
          </div>
        </div>
      )}

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

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-3">
        {CATEGORY_ORDER.map((category) => (
          <CategoryCard key={category} state={live.categories[category]} label={LABELS[category]} />
        ))}
      </div>
    </div>
  );
}
