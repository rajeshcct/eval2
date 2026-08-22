import { useEffect, useState } from "react";
import type { CategoryReport, FinalReport, RoundHistoryEntry } from "../lib/ws";

const CATEGORY_ORDER = ["functionality", "security", "compliance"] as const;

const LABELS: Record<string, string> = {
  functionality: "Functionality",
  security: "Security",
  compliance: "Compliance",
};

interface ReportViewProps {
  report: FinalReport;
  onReset: () => void;
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

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** estimated_cost values can be very small (rounded to 6dp server-side, see
 * aggregator.py::_aggregate_performance_and_cost) — show more precision for
 * sub-cent amounts so a real cost doesn't just read as "$0.00". */
function formatCost(cost: number): string {
  return `$${cost.toFixed(cost > 0 && cost < 0.01 ? 6 : 2)}`;
}

function CopySessionId({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail (permissions, insecure context) — fail
      // quietly rather than showing an alarming error for a copy button.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title="Copy session_id to clipboard"
      className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200 print:hidden"
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  );
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
        <div className="flex flex-col gap-2 bg-slate-950/50 px-3 py-2 text-xs text-slate-400 print:bg-slate-50 print:text-slate-600">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <span>accuracy: {formatScore(round.accuracy)}</span>
            <span>relevance: {formatScore(round.relevance)}</span>
            <span>hallucination: {formatScore(round.hallucination)}</span>
            <span>safety: {formatScore(round.safety)}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <span>latency: {round.latency_ms !== null ? `${round.latency_ms} ms` : "—"}</span>
            <span>tokens: {round.tokens_used !== null ? round.tokens_used : "—"}</span>
            <span>cost: {round.estimated_cost !== null ? formatCost(round.estimated_cost) : "—"}</span>
          </div>
          {round.task && (
            <div>
              <span className="font-medium text-slate-300 print:text-slate-800">Task: </span>
              {round.task}
            </div>
          )}
          {round.output && (
            <div>
              <span className="font-medium text-slate-300 print:text-slate-800">Output: </span>
              {round.output}
            </div>
          )}
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

/** Compact per-category summary shown right under the masthead, before the
 * prose verdict — lets a reader take in the shape of the whole result (which
 * categories held up, which didn't, and where) in one glance rather than
 * needing to scroll through three full sections first. */
function CategoryGlanceStrip({ entries }: { entries: { key: string; report: CategoryReport }[] }) {
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 print:gap-1.5">
      {entries.map(({ key, report }) => {
        const counted = report.round_history.filter((r) => r.passed !== null);
        const passed = counted.filter((r) => r.passed).length;
        const broken = report.status === "broken";
        return (
          <div
            key={key}
            className={`flex min-w-[140px] flex-1 items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs print:py-1.5 ${
              broken
                ? "border-red-900 bg-red-950/20 print:border-red-200 print:bg-red-50"
                : "border-emerald-900 bg-emerald-950/20 print:border-emerald-200 print:bg-emerald-50"
            }`}
          >
            <span className="font-medium text-slate-200 print:text-slate-800">{LABELS[key] ?? key}</span>
            <span
              className={`font-mono ${
                broken ? "text-red-300 print:text-red-700" : "text-emerald-300 print:text-emerald-700"
              }`}
            >
              {broken ? `broke @ R${report.breaking_point_round}` : `${passed}/${counted.length} passed`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function CategorySection({
  category,
  report,
  forcedOpen,
}: {
  category: string;
  report: CategoryReport;
  forcedOpen: boolean;
}) {
  const broken = report.status === "broken";

  return (
    <section className="break-inside-avoid rounded-lg border border-slate-800 bg-slate-900/40 print:border-slate-300 print:bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-4 py-3 print:border-slate-200">
        <h3 className="font-serif text-base font-semibold text-slate-100 print:text-slate-900">
          {LABELS[category] ?? category}
        </h3>
        <div className="flex items-center gap-3">
          <PassRateBar history={report.round_history} />
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${
              broken
                ? "bg-red-950 text-red-300 print:bg-red-100 print:text-red-800"
                : "bg-emerald-950 text-emerald-300 print:bg-emerald-100 print:text-emerald-800"
            }`}
          >
            {broken ? "Broken" : "Robust"}
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
      ) : (
        <div className="border-b border-slate-800 bg-emerald-950/20 px-4 py-2 text-xs text-emerald-300 print:border-slate-200 print:bg-emerald-50 print:text-emerald-800">
          Robust — survived every round up to the cap
        </div>
      )}

      <ScoreTrendChart report={report} />

      <div>
        {report.round_history.length === 0 ? (
          <p className="px-4 py-3 text-sm text-slate-500 print:text-slate-600">No rounds recorded for this category.</p>
        ) : (
          report.round_history.map((round) => (
            <RoundHistoryRow key={round.round_number} round={round} forcedOpen={forcedOpen} />
          ))
        )}
      </div>
    </section>
  );
}

/** Phase V requirement 1's performance_and_cost section — totals +
 * averages, with rounds_missing_token_data / rounds_missing_cost_data
 * surfaced explicitly (never silently folded into the average, matching
 * aggregator.py's own PerformanceAndCost docstring). */
function PerformanceSummary({ perf }: { perf: FinalReport["performance_and_cost"] }) {
  return (
    <section className="break-inside-avoid rounded-lg border border-slate-800 bg-slate-900/40 p-4 print:border-slate-300 print:bg-white">
      <h2 className="font-serif text-lg font-semibold text-slate-100 print:text-slate-900">Performance &amp; Cost</h2>
      <div className="mt-3 grid grid-cols-2 gap-4 font-mono text-sm sm:grid-cols-3">
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
          <div className="text-slate-200 print:text-slate-900">{perf.total_tokens_used}</div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Avg tokens / round</div>
          <div className="text-slate-200 print:text-slate-900">
            {perf.average_tokens_used !== null ? perf.average_tokens_used : "no data"}
          </div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Total estimated cost</div>
          <div className="text-slate-200 print:text-slate-900">{formatCost(perf.total_estimated_cost)}</div>
        </div>
        <div>
          <div className="font-sans text-slate-500 print:text-slate-600">Avg cost / round</div>
          <div className="text-slate-200 print:text-slate-900">
            {perf.average_estimated_cost !== null ? formatCost(perf.average_estimated_cost) : "no data"}
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

/** The report's signature element: a certification-style stamp derived
 * from the actual category verdicts (not decoration) — "CERTIFIED
 * ROBUST" only when every tested category survived, "REVIEW REQUIRED"
 * otherwise, so the one glanceable mark on the page is honest about the
 * result underneath it. */
function VerdictStamp({ allRobust }: { allRobust: boolean }) {
  const label = allRobust ? "CERTIFIED ROBUST" : "REVIEW REQUIRED";
  const ring = allRobust
    ? "border-emerald-500 text-emerald-300 print:border-emerald-700 print:text-emerald-700"
    : "border-amber-500 text-amber-300 print:border-amber-700 print:text-amber-700";
  const innerRing = allRobust ? "border-emerald-500/40 print:border-emerald-700/40" : "border-amber-500/40 print:border-amber-700/40";

  return (
    <div className={`relative inline-flex -rotate-6 items-center justify-center rounded-full border-[3px] px-4 py-2 ${ring}`}>
      <div className={`pointer-events-none absolute inset-[3px] rounded-full border ${innerRing}`} />
      <span className="font-mono text-[11px] font-bold tracking-[0.18em] whitespace-nowrap">{label}</span>
    </div>
  );
}

/**
 * Phase V — the Final Report view. Renders a fully-received FinalReport
 * regardless of how it arrived: straight off session_completed at the end
 * of a live run, or fetched independently via GET
 * /api/sessions/{id}/report on the reload-by-session_id path (see
 * App.tsx) — this component itself doesn't know or care which, it's a
 * pure function of the report object.
 */
export default function ReportView({ report, onReset }: ReportViewProps) {
  const [expandAllForPrint, setExpandAllForPrint] = useState(false);

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

  function handleDownloadPdf() {
    setExpandAllForPrint(true);
    // Let the expanded round detail render before invoking the browser's
    // print pipeline, so "Save as PDF" captures the full report rather
    // than whatever accordion state was on screen.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => window.print());
    });
  }

  const presentCategories = CATEGORY_ORDER.map((c) => report.categories[c]).filter(
    (c): c is CategoryReport => Boolean(c),
  );
  const allRobust = presentCategories.length > 0 && presentCategories.every((c) => c.status !== "broken");
  const glanceEntries = CATEGORY_ORDER.flatMap((c) => {
    const cat = report.categories[c];
    return cat ? [{ key: c, report: cat }] : [];
  });

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 print:max-w-none print:gap-3">
      {/* Toolbar — screen only, no equivalent on the printed page. */}
      <div className="flex items-center justify-end gap-2 print:hidden">
        <button
          onClick={handleDownloadPdf}
          className="rounded-md border border-indigo-700 bg-indigo-950/40 px-3 py-1.5 text-sm font-medium text-indigo-200 hover:bg-indigo-900/50"
        >
          Download PDF
        </button>
        <button
          onClick={onReset}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Start another session
        </button>
      </div>

      {/* Masthead */}
      <div className="relative border-b border-slate-800 pb-5 print:border-slate-300 print:pb-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-slate-500 print:text-slate-600">
          EvalMind — AI Capability Evaluation
        </p>
        <h1 className="mt-1 pr-40 font-serif text-3xl font-semibold tracking-tight text-slate-50 print:pr-32 print:text-slate-900">
          Evaluation Report
        </h1>

        <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-slate-500 print:text-slate-600">
          <span>session</span>
          <span className="text-slate-300 print:text-slate-800">{report.session_id}</span>
          <CopySessionId sessionId={report.session_id} />
          <span className="mx-1 text-slate-700 print:text-slate-400">·</span>
          <span>started {formatDateTime(report.started_at)}</span>
          <span className="mx-1 text-slate-700 print:text-slate-400">·</span>
          <span>generated {formatDateTime(report.generated_at)}</span>
        </div>

        {presentCategories.length > 0 && (
          <div className="absolute right-0 top-0">
            <VerdictStamp allRobust={allRobust} />
          </div>
        )}
      </div>

      <CategoryGlanceStrip entries={glanceEntries} />

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 print:border-slate-300 print:bg-white">
        <h2 className="font-mono text-xs font-medium uppercase tracking-wide text-slate-500 print:text-slate-600">
          System Under Test
        </h2>
        <p className="mt-1 text-sm text-slate-300 print:text-slate-800">{report.aut_description}</p>
      </section>

      <section className="rounded-lg border border-indigo-800/60 bg-indigo-950/20 p-4 print:border-indigo-300 print:bg-indigo-50">
        <h2 className="font-serif text-sm font-semibold uppercase tracking-wide text-indigo-300 print:text-indigo-800">
          Overall Verdict
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-200 print:text-slate-800">{report.overall_verdict}</p>
      </section>

      <div className="flex flex-col gap-4">
        {CATEGORY_ORDER.map((category) => {
          const cat = report.categories[category];
          return cat ? (
            <CategorySection key={category} category={category} report={cat} forcedOpen={expandAllForPrint} />
          ) : null;
        })}
      </div>

      <PerformanceSummary perf={report.performance_and_cost} />

      {/* Footer — print only, gives every page a source line since a
       * multi-page PDF can be separated from the on-screen context it
       * was generated in. */}
      <div className="hidden print:mt-2 print:block print:border-t print:border-slate-300 print:pt-2 print:text-center print:font-mono print:text-[10px] print:text-slate-400">
        EvalMind — session {report.session_id} — generated {formatDateTime(report.generated_at)}
      </div>
    </div>
  );
}
