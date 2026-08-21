import { useState } from "react";
import type { CategoryLiveState } from "../lib/liveState";
import type { RoundResult } from "../lib/ws";

interface CategoryCardProps {
  state: CategoryLiveState;
  label: string;
}

function statusBadge(status: CategoryLiveState["status"]): { text: string; className: string } {
  switch (status) {
    case "pending":
      return { text: "Not started", className: "bg-slate-800 text-slate-400" };
    case "running":
      return { text: "Running", className: "bg-blue-950 text-blue-300 animate-pulse" };
    case "broken":
      return { text: "Broken", className: "bg-red-950 text-red-300" };
    case "robust_within_tested_range":
      return { text: "Robust", className: "bg-emerald-950 text-emerald-300" };
  }
}

function scorePill(score: number): string {
  // 0-10 scale, PASS_THRESHOLD lives server-side in agents/judge.py — this
  // is a purely visual gradient (green = high, red = low), not a
  // recomputation of pass/fail, which always comes straight from the
  // round's own `passed` field.
  if (score >= 8) return "text-emerald-300";
  if (score >= 5) return "text-amber-300";
  return "text-red-300";
}

function RoundRow({ round }: { round: RoundResult }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-slate-800 last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        title="Click to show secondary metrics (accuracy, relevance, hallucination, safety)"
        className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-800/50"
      >
        <span className="w-16 text-slate-400">Round {round.round_number}</span>
        <span className="w-20 text-slate-500">diff {round.difficulty}</span>
        <span className="flex flex-1 gap-4">
          <span className={scorePill(round.task_completion)}>tc {round.task_completion}</span>
          <span className={scorePill(round.security)}>sec {round.security}</span>
          <span className={scorePill(round.compliance)}>comp {round.compliance}</span>
        </span>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            round.passed ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"
          }`}
        >
          {round.passed ? "PASS" : "FAIL"}
        </span>
        <span className="text-slate-600">{expanded ? "−" : "+"}</span>
      </button>

      {expanded && (
        <div className="grid grid-cols-2 gap-2 bg-slate-950/50 px-3 py-2 text-xs text-slate-400 sm:grid-cols-4">
          <span>accuracy: {round.accuracy}</span>
          <span>relevance: {round.relevance}</span>
          <span>hallucination: {round.hallucination}</span>
          <span>safety: {round.safety}</span>
          <span className="col-span-2 sm:col-span-4 text-slate-500">{round.reasoning}</span>
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

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h3 className="text-base font-semibold text-slate-100">{label}</h3>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${badge.className}`}>{badge.text}</span>
      </div>

      {state.status === "broken" && (
        <div className="border-b border-slate-800 bg-red-950/30 px-4 py-2 text-xs text-red-300">
          Breaking point: round {state.breakingPointRound}
        </div>
      )}
      {state.status === "robust_within_tested_range" && (
        <div className="border-b border-slate-800 bg-emerald-950/20 px-4 py-2 text-xs text-emerald-300">
          Robust — survived every round up to the cap
        </div>
      )}

      <div>
        {state.rounds.length === 0 && !state.inProgressRound && (
          <p className="px-4 py-3 text-sm text-slate-500">Waiting to start…</p>
        )}
        {state.rounds.map((round) => (
          <RoundRow key={round.round_id} round={round} />
        ))}
        {state.inProgressRound && (
          <div className="flex items-center gap-3 px-3 py-2 text-sm text-blue-300">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" aria-hidden />
            Round {state.inProgressRound.roundNumber} (difficulty {state.inProgressRound.difficulty})
            running…
          </div>
        )}
      </div>
    </section>
  );
}
