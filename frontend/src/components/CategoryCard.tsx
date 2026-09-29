import { useState } from "react";
import type { CategoryLiveState } from "../lib/liveState";
import type { RoundResult } from "../lib/ws";
import { themeFor } from "./categoryTheme";

interface CategoryCardProps {
  state: CategoryLiveState;
  label: string;
}

function statusBadge(status: CategoryLiveState["status"]): { text: string; className: string } {
  switch (status) {
    case "pending":
      return { text: "Not started", className: "bg-slate-800 text-slate-400" };
    case "running":
      return { text: "Running", className: "bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40 animate-pulse" };
    case "broken":
      return { text: "Broken", className: "bg-red-500/15 text-red-300 ring-1 ring-red-500/40" };
    case "robust_within_tested_range":
      return { text: "Robust", className: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40" };
  }
}

function scoreTone(score: number): { text: string; bar: string } {
  // 0-10 scale, PASS_THRESHOLD lives server-side in agents/judge.py — this
  // is a purely visual gradient (green = high, red = low), not a
  // recomputation of pass/fail, which always comes straight from the
  // round's own `passed` field.
  if (score >= 8) return { text: "text-emerald-300", bar: "bg-emerald-400" };
  if (score >= 5) return { text: "text-amber-300", bar: "bg-amber-400" };
  return { text: "text-red-300", bar: "bg-red-400" };
}

function ScoreBar({ short, title, value }: { short: string; title: string; value: number }) {
  const tone = scoreTone(value);
  const width = Math.min(10, Math.max(0, Number(value) || 0)) * 10;
  return (
    <div title={title} className="rounded-lg bg-slate-950/50 px-2.5 py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-slate-500">{short}</span>
        <span className={`font-mono text-sm font-semibold ${tone.text}`}>{value}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function RoundRow({ round }: { round: RoundResult }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-t border-slate-800/80">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        title="Click to show secondary metrics (accuracy, relevance, hallucination, safety)"
        className="w-full px-4 py-3 text-left transition-colors hover:bg-slate-800/40"
      >
        <div className="flex items-center gap-3">
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ring-1 ${
              round.passed
                ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40"
                : "bg-red-500/15 text-red-300 ring-red-500/40"
            }`}
            aria-hidden
          >
            {round.round_number}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-200">Round {round.round_number}</p>
            <p className="text-xs text-slate-500">diff {round.difficulty}</p>
          </div>
          <span
            className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
              round.passed ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
            }`}
          >
            {round.passed ? "PASS" : "FAIL"}
          </span>
          <span className="w-4 text-center text-slate-500">{expanded ? "−" : "+"}</span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <ScoreBar short="tc" title="Task completion" value={round.task_completion} />
          <ScoreBar short="sec" title="Security" value={round.security} />
          <ScoreBar short="comp" title="Compliance" value={round.compliance} />
        </div>
      </button>

      {expanded && (
        <div className="grid grid-cols-2 gap-2 bg-slate-950/50 px-4 py-3 text-xs text-slate-400">
          <span className="rounded-md bg-slate-900/70 px-2.5 py-1.5">accuracy: {round.accuracy}</span>
          <span className="rounded-md bg-slate-900/70 px-2.5 py-1.5">relevance: {round.relevance}</span>
          <span className="rounded-md bg-slate-900/70 px-2.5 py-1.5">hallucination: {round.hallucination}</span>
          <span className="rounded-md bg-slate-900/70 px-2.5 py-1.5">safety: {round.safety}</span>
          <span className="col-span-2 text-sm leading-relaxed text-slate-400">{round.reasoning}</span>
        </div>
      )}
    </div>
  );
}

/**
 * Phase IV requirement 2 — one live card per category. Starts on
 * category_started, appends a row per round_completed (round number,
 * difficulty, the three primary scores + pass/fail badge as the headline;
 * secondary scores on click-to-expand), and locks in final status +
 * breaking point on category_completed.
 */
export default function CategoryCard({ state, label }: CategoryCardProps) {
  const badge = statusBadge(state.status);
  const theme = themeFor(label);
  const running = state.status === "running";
  const passedCount = state.rounds.filter((r) => r.passed).length;
  const failedCount = state.rounds.length - passedCount;

  return (
    <section
      className={`overflow-hidden rounded-2xl border bg-slate-900/60 transition-shadow ${
        running ? `${theme.border} shadow-lg ${theme.glow}` : "border-slate-800"
      }`}
    >
      <div className={`h-1.5 bg-gradient-to-r ${theme.gradient} ${running ? "animate-pulse" : ""}`} aria-hidden />

      <div className="flex items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-3">
          <span
            className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br text-xl ${theme.gradient}`}
            aria-hidden
          >
            {theme.icon}
          </span>
          <div>
            <h3 className="text-lg font-semibold text-slate-50">{label}</h3>
            <p className="text-xs text-slate-500">
              {state.rounds.length === 0
                ? "No rounds completed yet"
                : `${state.rounds.length} rounds · ${passedCount} passed · ${failedCount} failed`}
            </p>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${badge.className}`}>{badge.text}</span>
      </div>

      {state.status === "broken" && (
        <div className="flex items-center gap-2 border-t border-red-900/50 bg-red-500/10 px-5 py-2.5 text-sm text-red-300">
          <span aria-hidden>⚠️</span>
          Breaking point: round {state.breakingPointRound}
        </div>
      )}
      {state.status === "robust_within_tested_range" && (
        <div className="flex items-center gap-2 border-t border-emerald-900/50 bg-emerald-500/10 px-5 py-2.5 text-sm text-emerald-300">
          <span aria-hidden>✅</span>
          Robust — survived every round up to the cap
        </div>
      )}

      <div>
        {state.rounds.length === 0 && !state.inProgressRound && (
          <p className="border-t border-dashed border-slate-800 px-5 py-6 text-center text-sm text-slate-500">
            Waiting to start…
          </p>
        )}
        {state.rounds.map((round) => (
          <RoundRow key={round.round_id} round={round} />
        ))}
        {state.inProgressRound && (
          <div className={`flex items-center gap-3 border-t border-slate-800/80 px-5 py-4 text-sm ${theme.soft} ${theme.text}`}>
            <span
              className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden
            />
            Round {state.inProgressRound.roundNumber} (difficulty {state.inProgressRound.difficulty})
            running…
          </div>
        )}
      </div>
    </section>
  );
}
