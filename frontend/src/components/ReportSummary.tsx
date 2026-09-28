import { useState } from "react";
import type { ReactNode } from "react";
import type { FinalReport } from "../lib/ws";
import {
  STATE_LABELS,
  deriveAgentProfile,
  deriveOverview,
  deriveSessionDetails,
  deriveTokenUsage,
  formatCost,
  formatDateTime,
  formatDuration,
} from "../lib/reportDerive";
import type { CategoryStat, OverallSummary, Tone } from "../lib/reportDerive";

/**
 * The executive-summary half of the report — everything a reader sees on the
 * first screen, before the round-by-round detail. Purely presentational: every
 * status, count and sentence comes from lib/reportDerive.ts (one source of truth,
 * so no two cards can disagree), and anything the backend doesn't have is shown
 * as "Not available" or left out, never invented.
 */

// ==========================================================================
// Shared styling — same slate cards / indigo accent as the rest of the app,
// each with a light `print:` counterpart so "Download PDF" stays ink-friendly.
// ==========================================================================
const CARD =
  "rounded-lg border border-slate-800 bg-slate-900/40 p-4 print:break-inside-avoid print:border-slate-300 print:bg-white";
const CARD_TITLE = "font-serif text-lg font-semibold text-slate-100 print:text-slate-900";
const EYEBROW = "font-mono text-[11px] uppercase tracking-wide text-slate-500 print:text-slate-600";
const VALUE = "text-sm text-slate-200 print:text-slate-900";

export const TONE_BOX: Record<Tone, string> = {
  success: "border-emerald-900 bg-emerald-950/20 print:border-emerald-200 print:bg-emerald-50",
  danger: "border-red-900 bg-red-950/20 print:border-red-200 print:bg-red-50",
  warning: "border-amber-800 bg-amber-950/20 print:border-amber-200 print:bg-amber-50",
  neutral: "border-slate-800 bg-slate-900/40 print:border-slate-300 print:bg-white",
};

export const TONE_TEXT: Record<Tone, string> = {
  success: "text-emerald-300 print:text-emerald-700",
  danger: "text-red-300 print:text-red-700",
  warning: "text-amber-300 print:text-amber-700",
  neutral: "text-slate-400 print:text-slate-600",
};

const TONE_PILL: Record<Tone, string> = {
  success:
    "border-emerald-700 bg-emerald-950/50 text-emerald-300 print:border-emerald-300 print:bg-emerald-100 print:text-emerald-800",
  danger: "border-red-800 bg-red-950/50 text-red-300 print:border-red-300 print:bg-red-100 print:text-red-800",
  warning:
    "border-amber-700 bg-amber-950/50 text-amber-300 print:border-amber-300 print:bg-amber-100 print:text-amber-800",
  neutral: "border-slate-700 bg-slate-800/60 text-slate-300 print:border-slate-300 print:bg-slate-100 print:text-slate-700",
};

export function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-3 py-1 font-mono text-[11px] font-semibold tracking-[0.12em] ${TONE_PILL[tone]}`}
    >
      {label}
    </span>
  );
}

export function CopySessionId({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail (permissions, insecure context) — fail quietly
      // rather than showing an alarming error for a copy button.
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className={EYEBROW}>{label}</dt>
      <dd className={`mt-1 break-words ${VALUE}`}>{children}</dd>
    </div>
  );
}

function NotAvailable({ text = "Not available" }: { text?: string }) {
  return <span className="italic text-slate-500 print:text-slate-600">{text}</span>;
}

/** Long free text (a purpose or brief) collapses to a few lines with a toggle;
 * the printed PDF always gets the full text. */
function ExpandableText({ text, limit = 280 }: { text: string; limit?: number }) {
  const [open, setOpen] = useState(false);
  const long = text.length > limit;
  const shown = !long || open ? text : `${text.slice(0, limit).trimEnd()}…`;

  return (
    <div>
      <p className="whitespace-pre-line">
        <span className={long && !open ? "print:hidden" : ""}>{shown}</span>
        {long && !open && <span className="hidden print:inline">{text}</span>}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-xs text-indigo-400 hover:text-indigo-300 print:hidden"
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

// ==========================================================================
// 1. Header + Evaluation Summary
// ==========================================================================
interface ExecutiveSummaryProps {
  report: FinalReport;
  stats: CategoryStat[];
  overall: OverallSummary;
  onViewFull: () => void;
  onDownloadPdf: () => void;
  onExportJson: () => void;
}

export function ExecutiveSummary({
  report,
  stats,
  overall,
  onViewFull,
  onDownloadPdf,
  onExportJson,
}: ExecutiveSummaryProps) {
  const agentName = report.session_meta?.agent_name;
  const duration = formatDuration(report.duration_seconds);

  return (
    <div className="flex flex-col gap-4">
      <header className={CARD}>
        <p className={`${EYEBROW} tracking-[0.3em]`}>EvalMind — AI Capability Evaluation</p>
        <h1 className="mt-1 font-serif text-3xl font-semibold tracking-tight text-slate-50 print:text-slate-900">
          Evaluation Report
        </h1>
        {report.project_name && (
          <p className="mt-1 text-xs text-slate-500 print:text-slate-600">
            Project: <span className="text-slate-300 print:text-slate-800">{report.project_name}</span>
          </p>
        )}

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Agent name">{agentName ? agentName : <NotAvailable />}</Field>
          <Field label="Session ID">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs">{report.session_id}</span>
              <CopySessionId sessionId={report.session_id} />
            </span>
          </Field>
          <Field label="Evaluated">{formatDateTime(report.started_at)}</Field>
          <Field label="Duration">{duration ? duration : <NotAvailable />}</Field>
          <Field label="Status">
            <StatusPill label={overall.label} tone={overall.tone} />
          </Field>
        </dl>
      </header>

      <section className={CARD}>
        <h2 className={CARD_TITLE}>Evaluation Summary</h2>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {stats.map((s) => (
            <div key={s.key} className={`rounded-md border p-3 ${TONE_BOX[s.tone]}`}>
              <div className="text-sm font-medium text-slate-200 print:text-slate-800">{s.label}</div>
              <div className={`mt-1 font-mono text-xl font-semibold ${TONE_TEXT[s.tone]}`}>{s.headline}</div>
              {s.state !== "not_evaluated" && (
                <div className={`mt-1 text-xs ${TONE_TEXT[s.tone]}`}>{STATE_LABELS[s.state]}</div>
              )}
              {s.note && <div className="mt-1 text-xs text-amber-300 print:text-amber-700">{s.note}</div>}
            </div>
          ))}
        </div>

        <p className="mt-4 text-sm leading-relaxed text-slate-300 print:text-slate-800">{overall.text}</p>

        <div className="mt-4 flex flex-wrap gap-2 print:hidden">
          <button
            type="button"
            onClick={onViewFull}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500"
          >
            View Full Report
          </button>
          <button
            type="button"
            onClick={onDownloadPdf}
            className="rounded-md border border-indigo-700 bg-indigo-950/40 px-4 py-2 text-sm font-medium text-indigo-200 hover:bg-indigo-900/50"
          >
            Download PDF
          </button>
          <button
            type="button"
            onClick={onExportJson}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
          >
            Export JSON
          </button>
        </div>
      </section>
    </div>
  );
}

// ==========================================================================
// 2. Agent Profile
// ==========================================================================
export function AgentProfileCard({ report }: { report: FinalReport }) {
  const profile = deriveAgentProfile(report);
  const hasTechnical = Boolean(profile.endpoint || profile.connection || profile.authentication);

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>Agent Profile</h2>

      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
        <Field label="Name">{profile.name ? profile.name : <NotAvailable />}</Field>
        <Field label="Agent type">{profile.type ? profile.type : <NotAvailable />}</Field>
        <div className="min-w-0 sm:col-span-2">
          <dt className={EYEBROW}>Purpose</dt>
          <dd className={`mt-1 ${VALUE}`}>
            {profile.purpose ? <ExpandableText text={profile.purpose} /> : <NotAvailable />}
          </dd>
        </div>
        <div className="min-w-0 sm:col-span-2">
          <dt className={EYEBROW}>Description</dt>
          <dd className={`mt-1 ${VALUE}`}>
            {profile.description ? (
              <ExpandableText text={profile.description} />
            ) : (
              <NotAvailable text="Description not provided" />
            )}
          </dd>
        </div>
      </dl>

      {hasTechnical && (
        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-4 border-t border-slate-800 pt-4 sm:grid-cols-2 print:border-slate-200">
          {profile.endpoint && (
            <div className="min-w-0 sm:col-span-2">
              <dt className={EYEBROW}>Endpoint</dt>
              <dd className={`mt-1 break-all font-mono text-xs ${VALUE}`}>{profile.endpoint}</dd>
            </div>
          )}
          {profile.connection && <Field label="Connection type">{profile.connection}</Field>}
          {profile.authentication && <Field label="Authentication">{profile.authentication}</Field>}
        </dl>
      )}
    </section>
  );
}

// ==========================================================================
// 3. Evaluation Overview
// ==========================================================================
export function EvaluationOverviewCard({ report, stats }: { report: FinalReport; stats: CategoryStat[] }) {
  const o = deriveOverview(report, stats);
  const duration = formatDuration(o.durationSeconds);

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>Evaluation Overview</h2>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className={`rounded-md border p-2 ${TONE_BOX.success}`}>
          <div className={`font-mono text-lg font-semibold ${TONE_TEXT.success}`}>{o.passedRounds}</div>
          <div className="text-[11px] text-slate-400 print:text-slate-600">Passed</div>
        </div>
        <div className={`rounded-md border p-2 ${o.failedRounds > 0 ? TONE_BOX.danger : TONE_BOX.neutral}`}>
          <div className={`font-mono text-lg font-semibold ${o.failedRounds > 0 ? TONE_TEXT.danger : TONE_TEXT.neutral}`}>
            {o.failedRounds}
          </div>
          <div className="text-[11px] text-slate-400 print:text-slate-600">Failed</div>
        </div>
        <div
          className={`rounded-md border p-2 ${o.categoriesNeedingReview > 0 ? TONE_BOX.warning : TONE_BOX.neutral}`}
        >
          <div
            className={`font-mono text-lg font-semibold ${
              o.categoriesNeedingReview > 0 ? TONE_TEXT.warning : TONE_TEXT.neutral
            }`}
          >
            {o.categoriesNeedingReview}
          </div>
          <div className="text-[11px] text-slate-400 print:text-slate-600">
            Review required <span className="text-slate-500">({o.categoriesNeedingReview === 1 ? "category" : "categories"})</span>
          </div>
        </div>
      </div>

      <dl className="mt-4 flex flex-col gap-3">
        <Field label="Total rounds executed">{o.totalRounds}</Field>
        {o.roundsPerCategory.length > 0 && (
          <Field label="Rounds per category">
            {o.roundsPerCategory.map((c) => `${c.label} ${c.rounds}`).join(" · ")}
          </Field>
        )}
        <Field label="Categories evaluated">
          {o.evaluatedCategories.length > 0 ? o.evaluatedCategories.join(", ") : <NotAvailable text="None" />}
        </Field>
        {o.notEvaluatedCategories.length > 0 && (
          <Field label="Not evaluated">{o.notEvaluatedCategories.join(", ")}</Field>
        )}
        {duration && <Field label="Total evaluation time">{duration}</Field>}
        {o.unscoredRounds > 0 && <Field label="Rounds without a verdict">{o.unscoredRounds}</Field>}
      </dl>
    </section>
  );
}

// ==========================================================================
// 4. AI / Session Details
// ==========================================================================
export function SessionDetailsCard({ report }: { report: FinalReport }) {
  const rows = deriveSessionDetails(report);

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>AI / Session Details</h2>
      <dl className="mt-3 flex flex-col gap-3">
        {rows.map((row) => (
          <Field key={row.label} label={row.label}>
            {row.label === "Session ID" ? <span className="font-mono text-xs">{row.value}</span> : row.value}
          </Field>
        ))}
      </dl>
      {!report.session_meta && (
        <p className="mt-3 text-xs text-slate-500 print:text-slate-600">
          This session was recorded before run settings were saved, so only the session ID is available.
        </p>
      )}
    </section>
  );
}

// ==========================================================================
// 5. Token Usage
// ==========================================================================
export function TokenUsageCard({ report }: { report: FinalReport }) {
  const usage = deriveTokenUsage(report.performance_and_cost);
  const perf = report.performance_and_cost;

  const tiles: { label: string; value: ReactNode; note?: string }[] = [
    // The backend records a single total per round and no input/output split.
    { label: "Input tokens", value: <NotAvailable /> },
    { label: "Output tokens", value: <NotAvailable /> },
    {
      label: "Total tokens",
      value: usage.totalTokens !== null ? usage.totalTokens.toLocaleString() : <NotAvailable />,
      note: usage.tokensPartial
        ? `${perf.rounds_missing_token_data}/${perf.total_rounds} rounds reported none`
        : undefined,
    },
    {
      label: "Estimated cost",
      value: usage.estimatedCost !== null ? formatCost(usage.estimatedCost) : <NotAvailable />,
      note: usage.costPartial ? `${perf.rounds_missing_cost_data}/${perf.total_rounds} rounds reported none` : undefined,
    },
  ];

  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>Token Usage</h2>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-md border border-slate-800 bg-slate-950/40 p-3 print:border-slate-200 print:bg-white">
            <div className={EYEBROW}>{t.label}</div>
            <div className="mt-1 font-mono text-sm text-slate-100 print:text-slate-900">{t.value}</div>
            {t.note && <div className="mt-1 text-[11px] text-slate-500 print:text-slate-600">{t.note}</div>}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500 print:text-slate-600">
        Figures are whatever the agent under test reported for its own replies. Nothing is estimated, and
        EvalMind&apos;s own evaluator usage is not tracked.
      </p>
    </section>
  );
}

// ==========================================================================
// 6. How the Agent Was Evaluated
// ==========================================================================
const EVALUATION_STEPS: { icon: string; label: string; text: string }[] = [
  { icon: "🧪", label: "Generate Scenario", text: "A test task is written for the category and difficulty." },
  { icon: "📤", label: "Send Request", text: "The task is sent to the agent over its connection." },
  { icon: "📥", label: "Capture Response", text: "The agent's reply and response time are recorded." },
  { icon: "⚖️", label: "Evaluate Response", text: "A judge model reviews the task and the reply." },
  { icon: "📊", label: "Score", text: "Seven 0–10 scores; pass/fail is computed from the primary ones." },
  { icon: "🔁", label: "Repeat", text: "The process repeats round by round in each category." },
  { icon: "📄", label: "Generate Report", text: "All rounds are aggregated into this report." },
];

export function HowEvaluatedSection() {
  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>How the Agent Was Evaluated</h2>
      <ol className="mt-3 flex flex-wrap items-stretch gap-x-1 gap-y-2">
        {EVALUATION_STEPS.map((step, i) => (
          <li key={step.label} className="flex min-w-[10rem] flex-1 items-center gap-1">
            <div className="flex flex-1 flex-col gap-1 rounded-md border border-slate-800 bg-slate-950/40 p-2.5 print:border-slate-200 print:bg-white">
              <div className="flex items-center gap-2">
                <span aria-hidden>{step.icon}</span>
                <span className="text-xs font-medium text-slate-200 print:text-slate-900">{step.label}</span>
              </div>
              <p className="text-[11px] leading-snug text-slate-500 print:text-slate-600">{step.text}</p>
            </div>
            {i < EVALUATION_STEPS.length - 1 && (
              <span aria-hidden className="text-slate-600 print:text-slate-400">
                →
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

// ==========================================================================
// 7. Performance Summary — one sentence per category, built from the rounds
// ==========================================================================
export function PerformanceSummarySection({ stats }: { stats: CategoryStat[] }) {
  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>Performance Summary</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        {stats.map((s) => (
          <div key={s.key} className={`rounded-md border p-3 ${TONE_BOX[s.tone]}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-100 print:text-slate-900">{s.label}</span>
              <span className={`font-mono text-xs ${TONE_TEXT[s.tone]}`}>
                {STATE_LABELS[s.state]}
                {s.state !== "not_evaluated" && ` · ${s.headline}`}
              </span>
            </div>
            <p className="mt-1 text-sm leading-relaxed text-slate-300 print:text-slate-800">{s.summary}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
