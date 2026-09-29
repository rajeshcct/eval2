import { useEffect, useRef, useState } from "react";
import type { CategoryReport, FinalReport, RoundHistoryEntry } from "../lib/ws";
import { deleteSession, rejudgeSession } from "../lib/ws";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  deriveAllStats,
  deriveOverall,
  deriveTokenUsage,
  formatCost,
  formatDateTime,
} from "../lib/reportDerive";
import type { CategoryStat, Tone } from "../lib/reportDerive";
import {
  AgentProfileCard,
  CopySessionId,
  EvaluationOverviewCard,
  ExecutiveSummary,
  HowEvaluatedSection,
  PerformanceSummarySection,
  SessionDetailsCard,
  TokenUsageCard,
} from "./ReportSummary";

interface ReportViewProps {
  report: FinalReport;
  onReset: () => void;
  /** "Start another session": go to a fresh New Session form, optionally with the
   * given project already selected. */
  onStartAnother: (project: { id: string; name: string } | null) => void;
}

function scorePillClass(score: number | null): string {
  if (score === null) return "text-slate-500 print:text-slate-600";
  if (score >= 8) return "text-emerald-300 print:text-emerald-700";
  if (score >= 5) return "text-amber-300 print:text-amber-700";
  return "text-red-300 print:text-red-700";
}

function formatScore(score: number | null): string {
  return score === null ? "—" : String(score);
}

/** Compact pass-rate bar for a category's round_history — the report's
 * one piece of at-a-glance data visualization, sitting next to the
 * Robust/Broken badge so a reader gets the shape of the result before
 * scanning individual rounds. */
function PassRateBar({ history }: { history: RoundHistoryEntry[] }) {
  const counted = history.filter((r) => r.passed !== null);
  const total = counted.length;
  if (total === 0) return null;
  const passed = counted.filter((r) => r.passed).length;
  const pct = Math.round((passed / total) * 100);

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-800 print:bg-slate-200">
        <div
          className="h-full rounded-full bg-emerald-500 print:bg-emerald-600"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[11px] text-slate-500 print:text-slate-600">
        {passed}/{total} passed
      </span>
    </div>
  );
}

/** One row of a category's round_history — same headline-scores-plus-
 * click-to-expand shape as Phase IV's live CategoryCard, so the report
 * reads consistently with the live view a reader may have just watched.
 * RoundHistoryEntry (unlike the live view's RoundResult) also carries the
 * round's task/output text and latency/token/cost figures, shown here in
 * the expanded state alongside the secondary scores.
 *
 * `forcedOpen` is driven by the report-level "Download PDF" action: the
 * printed document should show full round detail rather than a collapsed
 * accordion, since there's no click affordance on paper. It only adds to
 * visibility — a round the reader collapsed manually can still be forced
 * open for print without losing their on-screen state once printing ends. */
function RoundHistoryRow({ round, forcedOpen }: { round: RoundHistoryEntry; forcedOpen: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const isOpen = expanded || forcedOpen;

  return (
    <div className="break-inside-avoid border-b border-slate-800 last:border-b-0 print:border-slate-200">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        title="Click to show secondary metrics, task, and output"
        className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-800/50 print:py-1.5"
      >
        <span className="w-16 font-mono text-slate-400 print:text-slate-600">Round {round.round_number}</span>
        <span className="w-20 font-mono text-slate-500 print:text-slate-600">diff {round.difficulty ?? "—"}</span>
        <span className="flex flex-1 gap-4 font-mono">
          <span className={scorePillClass(round.task_completion)}>tc {formatScore(round.task_completion)}</span>
          <span className={scorePillClass(round.security)}>sec {formatScore(round.security)}</span>
          <span className={scorePillClass(round.compliance)}>comp {formatScore(round.compliance)}</span>
        </span>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            round.passed
              ? "bg-emerald-950 text-emerald-300 print:bg-emerald-100 print:text-emerald-800"
              : "bg-red-950 text-red-300 print:bg-red-100 print:text-red-800"
          }`}
        >
          {round.passed === null ? "N/A" : round.passed ? "PASS" : "FAIL"}
        </span>
        <span className="text-slate-600 print:hidden">{isOpen ? "−" : "+"}</span>
      </button>

      {isOpen && (
        <div className="flex flex-col gap-3 bg-slate-950/50 px-4 py-3 text-sm text-slate-400 print:bg-slate-50 print:text-slate-600">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <span>accuracy: {formatScore(round.accuracy)}</span>
            <span>relevance: {formatScore(round.relevance)}</span>
            <span>hallucination: {formatScore(round.hallucination)}</span>
            <span>safety: {formatScore(round.safety)}</span>
          </div>
          {round.reasoning && (
            <div className="rounded-md border border-slate-800 bg-slate-900/40 p-3 print:border-slate-200 print:bg-white">
              <span className="font-medium text-slate-300 print:text-slate-800">Judge reasoning: </span>
              {round.reasoning}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <span>latency: {round.latency_ms !== null ? `${round.latency_ms} ms` : "—"}</span>
            <span>tokens: {round.tokens_used !== null ? round.tokens_used : "—"}</span>
            <span>cost: {round.estimated_cost !== null ? formatCost(round.estimated_cost) : "—"}</span>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:[&>*:only-child]:col-span-2">
          {round.task && (
            <div className="whitespace-pre-wrap break-words rounded-md border border-slate-800 bg-slate-900/40 p-3 print:border-slate-200 print:bg-white">
              <span className="font-medium text-slate-300 print:text-slate-800">Task: </span>
              {round.task}
            </div>
          )}
          {round.output && (
            <div className="whitespace-pre-wrap break-words rounded-md border border-slate-800 bg-slate-900/40 p-3 print:border-slate-200 print:bg-white">
              <span className="font-medium text-slate-300 print:text-slate-800">Output: </span>
              {round.output}
            </div>
          )}
          </div>
        </div>
      )}
    </div>
  );
}

const CHART_WIDTH = 600;
const CHART_HEIGHT = 140;
const CHART_PAD_LEFT = 22;
const CHART_PAD_RIGHT = 12;
const CHART_PAD_TOP = 10;
const CHART_PAD_BOTTOM = 20;

type ChartKey = "task_completion" | "security" | "compliance";
const CHART_SERIES: { key: ChartKey; color: string; label: string }[] = [
  { key: "task_completion", color: "#818cf8", label: "task completion" },
  { key: "security", color: "#fb7185", label: "security" },
  { key: "compliance", color: "#34d399", label: "compliance" },
];

/** The report's core signal made visible at a glance: how task_completion /
 * security / compliance moved round-over-round, with the breaking point (if
 * any) marked. Previously this shape only existed implicitly, spread across
 * collapsed accordion rows a reader had to open one by one. Hand-rolled SVG
 * rather than a charting dependency — keeps it printing cleanly to PDF and
 * avoids adding recharts/chart.js just for three lines. Skipped entirely
 * below 2 scored rounds, since a single point can't show a trend. */
function ScoreTrendChart({ report }: { report: CategoryReport }) {
  const rounds = report.round_history.filter(
    (r) => r.task_completion !== null || r.security !== null || r.compliance !== null,
  );
  if (rounds.length < 2) return null;

  const innerWidth = CHART_WIDTH - CHART_PAD_LEFT - CHART_PAD_RIGHT;
  const innerHeight = CHART_HEIGHT - CHART_PAD_TOP - CHART_PAD_BOTTOM;

  const xFor = (i: number) =>
    CHART_PAD_LEFT + (rounds.length === 1 ? innerWidth / 2 : (i / (rounds.length - 1)) * innerWidth);
  const yFor = (score: number) => CHART_PAD_TOP + innerHeight - (score / 10) * innerHeight;

  function pathFor(key: ChartKey): string {
    const pts = rounds
      .map((r, i) => (r[key] !== null ? `${xFor(i)},${yFor(r[key] as number)}` : null))
      .filter((p): p is string => p !== null);
    return pts.length > 0 ? `M ${pts.join(" L ")}` : "";
  }

  const breakIndex =
    report.breaking_point_round !== null
      ? rounds.findIndex((r) => r.round_number === report.breaking_point_round)
      : -1;

  return (
    <div className="border-b border-slate-800 px-4 py-3 print:border-slate-200 print:break-inside-avoid">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500 print:text-slate-600">
          Score by round
        </span>
        <div className="flex items-center gap-3 font-mono text-[10px]">
          {CHART_SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1 text-slate-400 print:text-slate-600">
              <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="h-28 w-full" preserveAspectRatio="none">
        {[0, 5, 10].map((tick) => (
          <g key={tick}>
            <line
              x1={CHART_PAD_LEFT}
              x2={CHART_WIDTH - CHART_PAD_RIGHT}
              y1={yFor(tick)}
              y2={yFor(tick)}
              stroke="currentColor"
              className="text-slate-800 print:text-slate-200"
              strokeWidth={1}
              strokeDasharray={tick === 0 ? undefined : "3,3"}
            />
            <text
              x={1}
              y={yFor(tick) + 3}
              fontSize={9}
              fill="currentColor"
              className="text-slate-600 print:text-slate-500"
            >
              {tick}
            </text>
          </g>
        ))}

        {breakIndex >= 0 && (
          <line
            x1={xFor(breakIndex)}
            x2={xFor(breakIndex)}
            y1={CHART_PAD_TOP}
            y2={CHART_HEIGHT - CHART_PAD_BOTTOM}
            stroke="#f87171"
            strokeWidth={1.5}
            strokeDasharray="4,3"
          />
        )}

        {CHART_SERIES.map((s) => {
          const d = pathFor(s.key);
          return d ? <path key={s.key} d={d} fill="none" stroke={s.color} strokeWidth={1.75} /> : null;
        })}

        {CHART_SERIES.map((s) =>
          rounds.map((r, i) =>
            r[s.key] !== null ? (
              <circle key={`${s.key}-${i}`} cx={xFor(i)} cy={yFor(r[s.key] as number)} r={2} fill={s.color} />
            ) : null,
          ),
        )}

        {rounds.map((r, i) => (
          <text
            key={`x-${i}`}
            x={xFor(i)}
            y={CHART_HEIGHT - 4}
            fontSize={9}
            textAnchor="middle"
            fill="currentColor"
            className="text-slate-600 print:text-slate-500"
          >
            R{r.round_number}
          </text>
        ))}
      </svg>
      {breakIndex >= 0 && (
        <div className="mt-1 text-[10px] text-red-400 print:text-red-700">
          Broke at round {report.breaking_point_round}
        </div>
      )}
    </div>
  );
}

/** A category's headline block in the full report: result badge, breaking
 * point, and the score chart. Its round-by-round rows live in RoundsSection
 * below, so the nav can jump to either. The badge and banner read the same
 * CategoryStat the summary cards use, so they can't disagree with them. */
function CategorySection({ report, stat }: { report: CategoryReport; stat: CategoryStat }) {
  const broken = stat.state === "failed";
  const incomplete = stat.state === "incomplete";

  return (
    <section
      id={stat.key}
      className="scroll-mt-16 break-inside-avoid rounded-lg border border-slate-800 bg-slate-900/40 print:border-slate-300 print:bg-white"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-4 py-3 print:border-slate-200">
        <h3 className="font-serif text-base font-semibold text-slate-100 print:text-slate-900">
          {CATEGORY_LABELS[stat.key] ?? stat.key}
        </h3>
        <div className="flex items-center gap-3">
          <PassRateBar history={report.round_history} />
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${
              broken
                ? "bg-red-950 text-red-300 print:bg-red-100 print:text-red-800"
                : incomplete
                  ? "bg-amber-950 text-amber-300 print:bg-amber-100 print:text-amber-800"
                  : "bg-emerald-950 text-emerald-300 print:bg-emerald-100 print:text-emerald-800"
            }`}
          >
            {broken ? "Broken" : incomplete ? "Incomplete" : "Robust"}
          </span>
        </div>
      </div>

      {broken ? (
        <div className="border-b border-slate-800 bg-red-950/30 px-4 py-2 text-xs text-red-300 print:border-slate-200 print:bg-red-50 print:text-red-800">
          <div>Breaking point: round {report.breaking_point_round}</div>
          {report.breaking_point_summary && (
            <div className="mt-1 text-red-300/90 print:text-red-800/90">{report.breaking_point_summary}</div>
          )}
        </div>
      ) : incomplete ? null : (
        <div className="border-b border-slate-800 bg-emerald-950/20 px-4 py-2 text-xs text-emerald-300 print:border-slate-200 print:bg-emerald-50 print:text-emerald-800">
          Robust — every evaluated round passed within the tested range
        </div>
      )}
      {report.incomplete && (
        <div className="border-b border-amber-900 bg-amber-950/30 px-4 py-2 text-xs text-amber-300 print:border-slate-200 print:bg-amber-50 print:text-amber-800">
          Run cut short by an error — only {report.round_history.length} round(s) completed for this category, so
          this is not a full pass.
        </div>
      )}

      <ScoreTrendChart report={report} />
    </section>
  );
}

/** Every category's round list, together, under one anchor. */
function RoundsSection({
  entries,
  forcedOpen,
}: {
  entries: { key: string; report: CategoryReport }[];
  forcedOpen: boolean;
}) {
  return (
    <section id="rounds" className="scroll-mt-16 flex flex-col gap-3">
      <h2 className="font-serif text-lg font-semibold text-slate-100 print:text-slate-900">Round-by-round results</h2>
      {entries.map(({ key, report }) => (
        <div
          key={key}
          className="rounded-lg border border-slate-800 bg-slate-900/40 print:border-slate-300 print:bg-white"
        >
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 print:border-slate-200">
            <span className="text-sm font-medium text-slate-200 print:text-slate-900">
              {CATEGORY_LABELS[key] ?? key}
            </span>
            <span className="font-mono text-[11px] text-slate-500 print:text-slate-600">
              {report.round_history.length} round{report.round_history.length === 1 ? "" : "s"}
            </span>
          </div>
          {report.round_history.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500 print:text-slate-600">No rounds recorded for this category.</p>
          ) : (
            report.round_history.map((round) => (
              <RoundHistoryRow key={round.round_number} round={round} forcedOpen={forcedOpen} />
            ))
          )}
        </div>
      ))}
    </section>
  );
}

/** Totals + averages, with missing token/cost data surfaced explicitly (never
 * silently folded into an average, matching aggregator.py's own
 * PerformanceAndCost docstring). "Not available" wording and the
 * no-data-vs-zero rule come from deriveTokenUsage, same as the Token Usage
 * card on the summary, so the two never disagree. */
function PerformanceCostTable({ perf }: { perf: FinalReport["performance_and_cost"] }) {
  const usage = deriveTokenUsage(perf);
  const na = "Not available";

  return (
    <section className="break-inside-avoid lg:col-span-2 rounded-lg border border-slate-800 bg-slate-900/40 p-4 print:border-slate-300 print:bg-white">
      <h3 className="font-serif text-base font-semibold text-slate-100 print:text-slate-900">Performance &amp; Cost</h3>
      <div className="mt-3 grid grid-cols-2 gap-4 font-mono text-sm sm:grid-cols-3 lg:grid-cols-4">
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Total rounds</div>
          <div className="text-slate-200 print:text-slate-900">{perf.total_rounds}</div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Total latency</div>
          <div className="text-slate-200 print:text-slate-900">{perf.total_latency_ms} ms</div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Avg latency / round</div>
          <div className="text-slate-200 print:text-slate-900">{perf.average_latency_ms} ms</div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Total tokens</div>
          <div className="text-slate-200 print:text-slate-900">
            {usage.totalTokens !== null ? usage.totalTokens : na}
          </div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Avg tokens / round</div>
          <div className="text-slate-200 print:text-slate-900">
            {perf.average_tokens_used !== null ? perf.average_tokens_used : na}
          </div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Total estimated cost</div>
          <div className="text-slate-200 print:text-slate-900">
            {usage.estimatedCost !== null ? formatCost(usage.estimatedCost) : na}
          </div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Avg cost / round</div>
          <div className="text-slate-200 print:text-slate-900">
            {perf.average_estimated_cost !== null ? formatCost(perf.average_estimated_cost) : na}
          </div>
        </div>
      </div>

      {(perf.rounds_missing_token_data > 0 || perf.rounds_missing_cost_data > 0) && (
        <div className="mt-3 flex flex-col gap-1 text-xs text-slate-500 print:text-slate-600">
          {perf.rounds_missing_token_data > 0 && (
            <span>
              {perf.rounds_missing_token_data}/{perf.total_rounds} rounds had no token data (excluded from the average).
            </span>
          )}
          {perf.rounds_missing_cost_data > 0 && (
            <span>
              {perf.rounds_missing_cost_data}/{perf.total_rounds} rounds had no cost data (excluded from the average).
            </span>
          )}
        </div>
      )}
    </section>
  );
}

const STAMP_RING: Record<Tone, string> = {
  success: "border-emerald-500 text-emerald-300 print:border-emerald-700 print:text-emerald-700",
  warning: "border-amber-500 text-amber-300 print:border-amber-700 print:text-amber-700",
  danger: "border-red-500 text-red-300 print:border-red-700 print:text-red-700",
  neutral: "border-slate-500 text-slate-300 print:border-slate-600 print:text-slate-600",
};
const STAMP_INNER: Record<Tone, string> = {
  success: "border-emerald-500/40 print:border-emerald-700/40",
  warning: "border-amber-500/40 print:border-amber-700/40",
  danger: "border-red-500/40 print:border-red-700/40",
  neutral: "border-slate-500/40 print:border-slate-600/40",
};

/** The report's signature element: a certification-style stamp derived from
 * the actual category results (see deriveOverall) — not decoration, so the one
 * glanceable mark on the page is honest about the result underneath it. */
function VerdictStamp({ label, tone }: { label: string; tone: Tone }) {
  return (
    <div
      className={`relative inline-flex -rotate-6 items-center justify-center rounded-full border-[3px] px-4 py-2 ${STAMP_RING[tone]}`}
    >
      <div className={`pointer-events-none absolute inset-[3px] rounded-full border ${STAMP_INNER[tone]}`} />
      <span className="font-mono text-[11px] font-bold tracking-[0.18em] whitespace-nowrap">{label}</span>
    </div>
  );
}

/** Three-dot menu for the rarely-used actions, so the toolbar keeps to the
 * three primary ones. Closes on outside click or Escape. */
function ActionMenu({
  onStartAnother,
  onDelete,
  deleting,
}: {
  onStartAnother: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions"
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border border-slate-700 px-2.5 py-1.5 text-sm leading-none text-slate-300 hover:bg-slate-800"
      >
        ⋯
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 w-52 overflow-hidden rounded-md border border-slate-700 bg-slate-900 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onStartAnother();
            }}
            className="block w-full px-3 py-2 text-left text-sm text-slate-200 hover:bg-slate-800"
          >
            Start another session
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={deleting}
            onClick={() => {
              setOpen(false);
              onDelete();
            }}
            className="block w-full border-t border-slate-800 px-3 py-2 text-left text-sm text-red-400 hover:bg-red-950/50 disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete session"}
          </button>
        </div>
      )}
    </div>
  );
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** Sticky section bar for the full report: one button per section that
 * actually exists (a category that wasn't evaluated has nothing to jump to).
 * Going back to the summary is the button in the toolbar at the top. */
function FullReportNav({ sections }: { sections: { id: string; label: string }[] }) {
  const item =
    "rounded px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800 hover:text-slate-50 focus:outline-none focus:ring-1 focus:ring-indigo-500";
  return (
    <nav
      aria-label="Report sections"
      className="sticky top-0 z-20 flex flex-wrap items-center gap-1 rounded-md border border-slate-800 bg-slate-950/90 px-2 py-1.5 backdrop-blur print:hidden"
    >
      {sections.map((s) => (
        <button key={s.id} type="button" onClick={() => jumpTo(s.id)} className={item}>
          {s.label}
        </button>
      ))}
    </nav>
  );
}

/**
 * Phase V — the Final Report view, now opening on an executive summary.
 *
 * Renders a fully-received FinalReport regardless of how it arrived: straight
 * off session_completed at the end of a live run, or fetched independently via
 * GET /api/sessions/{id}/report on the reload-by-session_id path (see App.tsx)
 * — this component itself doesn't know or care which, it's a pure function of
 * the report object.
 *
 * Two views over that one report: "summary" (agent profile, overview, session
 * details, token usage, how it was evaluated, per-category performance summary)
 * and "full" (the original detail — category charts, round-by-round rows,
 * verdict, cost table). Both stay in the DOM so "Download PDF" prints the whole
 * document whichever view is on screen; only the active one is visible.
 */
export default function ReportView({ report, onReset, onStartAnother }: ReportViewProps) {
  const [expandAllForPrint, setExpandAllForPrint] = useState(false);
  const [currentReport, setCurrentReport] = useState<FinalReport>(report);
  const [rejudging, setRejudging] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [view, setView] = useState<"summary" | "full">("summary");

  // Revert the forced-open state once the print dialog closes (or the
  // "Save as PDF" flow finishes/cancels) so the on-screen accordion goes
  // back to whatever the reader had expanded themselves.
  useEffect(() => {
    function handleAfterPrint() {
      setExpandAllForPrint(false);
    }
    window.addEventListener("afterprint", handleAfterPrint);
    return () => window.removeEventListener("afterprint", handleAfterPrint);
  }, []);

  function showView(next: "summary" | "full") {
    setView(next);
    window.scrollTo({ top: 0 });
  }

  function handleDownloadPdf() {
    setExpandAllForPrint(true);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => window.print());
    });
  }

  function handleDownloadJson() {
    const blob = new Blob([JSON.stringify(currentReport, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `evalmind-report-${currentReport.session_id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  /** Asks first, then opens a new session form. If this report's session belongs
   * to a project, the new session is pre-filed under that same project. */
  function handleStartAnother() {
    const projectId = currentReport.project_id ?? null;
    const projectName = currentReport.project_name?.trim() || "this project";
    const message = projectId
      ? `Start another session in project “${projectName}”?\n\nThe new session will be saved in the same project.`
      : "Start another session?\n\nThis session isn’t in a project, so the new one won’t be either unless you pick one.";
    if (!confirm(message)) return;
    onStartAnother(projectId ? { id: projectId, name: projectName } : null);
  }

  async function handleRejudge() {
    if (!confirm("Re-run the Judge over all existing rounds? This overwrites the stored scores and rebuilds the report.")) return;
    setRejudging(true);
    try {
      const updated = await rejudgeSession(currentReport.session_id);
      setCurrentReport(updated);
    } catch (e) {
      alert(`Re-judge failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRejudging(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this session and all its rounds? This cannot be undone.")) return;
    setDeleting(true);
    try {
      await deleteSession(currentReport.session_id);
      onReset();
    } catch (e) {
      alert(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
      setDeleting(false);
    }
  }

  // Every status, count and sentence below comes from these two derivations, so
  // the summary cards, the category sections and the header pill always agree.
  const stats = deriveAllStats(currentReport);
  const overall = deriveOverall(stats);
  const evaluatedEntries = CATEGORY_ORDER.flatMap((key) => {
    const cat = currentReport.categories[key];
    return cat && cat.round_history.length > 0 ? [{ key, report: cat }] : [];
  });
  const navSections = [
    ...evaluatedEntries.map((e) => ({ id: e.key, label: CATEGORY_LABELS[e.key] ?? e.key })),
    ...(evaluatedEntries.length > 0 ? [{ id: "rounds", label: "Rounds" }] : []),
    { id: "analysis", label: "Analysis" },
  ];

  return (
    <div className="mx-auto flex w-full max-w-[1450px] flex-col gap-4 print:max-w-none print:gap-3">
      {/* Toolbar — screen only, no equivalent on the printed page. Three primary
       * actions; the rarely-used ones live in the ⋯ menu. */}
      <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
        {view === "full" ? (
          <button
            type="button"
            onClick={() => showView("summary")}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            ← Back to summary
          </button>
        ) : (
          <button
            type="button"
            onClick={onReset}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            ← Back to sessions
          </button>
        )}
        <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => void handleRejudge()}
          disabled={rejudging}
          className="rounded-md border border-amber-800 bg-amber-950/30 px-3 py-1.5 text-sm font-medium text-amber-200 hover:bg-amber-900/50 disabled:opacity-50"
        >
          {rejudging ? "Re-judging…" : "Re-judge"}
        </button>
        <button
          onClick={handleDownloadJson}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Export JSON
        </button>
        <button
          onClick={handleDownloadPdf}
          className="rounded-md border border-indigo-700 bg-indigo-950/40 px-3 py-1.5 text-sm font-medium text-indigo-200 hover:bg-indigo-900/50"
        >
          Download PDF
        </button>
        <ActionMenu onStartAnother={handleStartAnother} onDelete={() => void handleDelete()} deleting={deleting} />
        </div>
      </div>

      {/* ---- Executive summary (first screen) ---- */}
      <div className={view === "summary" ? "flex flex-col gap-4" : "hidden print:flex print:flex-col print:gap-3"}>
        <ExecutiveSummary
          report={currentReport}
          stats={stats}
          overall={overall}
          onViewFull={() => showView("full")}
          onDownloadPdf={handleDownloadPdf}
          onExportJson={handleDownloadJson}
        />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <AgentProfileCard report={currentReport} />
          <SessionDetailsCard report={currentReport} />
          <EvaluationOverviewCard report={currentReport} stats={stats} />
          <TokenUsageCard report={currentReport} />
        </div>
        <HowEvaluatedSection />
        <PerformanceSummarySection stats={stats} />
      </div>

      {/* ---- Full detailed report ---- */}
      <div
        className={
          view === "full"
            ? "flex flex-col gap-4"
            : "hidden print:flex print:flex-col print:gap-3 print:break-before-page"
        }
      >
        <FullReportNav sections={navSections} />

        {/* Masthead */}
        <div className="relative border-b border-slate-800 pb-5 print:border-slate-300 print:pb-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-slate-500 print:text-slate-600">
            EvalMind — AI Capability Evaluation
          </p>
          <h2 className="mt-1 font-serif text-3xl font-semibold tracking-tight text-slate-50 sm:pr-56 print:pr-56 print:text-slate-900">
            Full Evaluation Report
          </h2>

          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-slate-500 print:text-slate-600">
            <span>session</span>
            <span className="text-slate-300 print:text-slate-800">{currentReport.session_id}</span>
            <CopySessionId sessionId={currentReport.session_id} />
            <span className="mx-1 text-slate-700 print:text-slate-400">·</span>
            <span>started {formatDateTime(currentReport.started_at)}</span>
            <span className="mx-1 text-slate-700 print:text-slate-400">·</span>
            <span>generated {formatDateTime(currentReport.generated_at)}</span>
          </div>

          <div className="mt-4 sm:absolute sm:right-0 sm:top-0 sm:mt-0">
            <VerdictStamp label={overall.label} tone={overall.tone} />
          </div>
        </div>

        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,380px),1fr))] gap-4 print:grid-cols-1">
          {evaluatedEntries.map(({ key, report: cat }) => {
            const stat = stats.find((s) => s.key === key);
            return stat ? <CategorySection key={key} report={cat} stat={stat} /> : null;
          })}
        </div>

        {evaluatedEntries.length > 0 && <RoundsSection entries={evaluatedEntries} forcedOpen={expandAllForPrint} />}

        <section id="analysis" className="scroll-mt-16 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <h2 className="font-serif text-lg font-semibold text-slate-100 print:text-slate-900 lg:col-span-2">Analysis</h2>

          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 print:border-slate-300 print:bg-white">
            <h3 className="font-mono text-xs font-medium uppercase tracking-wide text-slate-500 print:text-slate-600">
              System Under Test
            </h3>
            <p className="mt-1 text-sm text-slate-300 print:text-slate-800">{currentReport.aut_description}</p>
          </div>

          <div className="rounded-lg border border-indigo-800/60 bg-indigo-950/20 p-4 print:border-indigo-300 print:bg-indigo-50">
            <h3 className="font-serif text-sm font-semibold uppercase tracking-wide text-indigo-300 print:text-indigo-800">
              Overall Verdict
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-200 print:text-slate-800">
              {currentReport.overall_verdict}
            </p>
            <p className="mt-2 text-xs text-slate-500 print:text-slate-600">
              AI-written narrative. The pass/fail counts elsewhere in this report are computed directly from the round
              data.
            </p>
          </div>

          <PerformanceCostTable perf={currentReport.performance_and_cost} />
        </section>
      </div>

      {/* Footer — print only, gives every page a source line since a
       * multi-page PDF can be separated from the on-screen context it
       * was generated in. */}
      <div className="hidden print:mt-2 print:block print:border-t print:border-slate-300 print:pt-2 print:text-center print:font-mono print:text-[10px] print:text-slate-400">
        EvalMind — session {currentReport.session_id} — generated {formatDateTime(currentReport.generated_at)}
      </div>
    </div>
  );
}
