/**
 * src/lib/reportDerive.ts
 *
 * Everything the report UI shows as a status, count, summary sentence or card
 * value is derived HERE, from the FinalReport's actual round data, in one
 * place. Two reasons:
 *
 *  1. Consistency. The header pill, the category tiles, the overview card, the
 *     performance summary and the detailed sections all read the same
 *     CategoryStat, so the report cannot say "Compliance — 1/1 passed" in one
 *     place and "Compliance unverified" in another. A category that isn't in
 *     report.categories is "Not evaluated" everywhere.
 *  2. Honesty. Nothing here is hardcoded result text or an invented value: every
 *     sentence is filled from the rounds, and anything the backend doesn't
 *     provide comes back as null so the UI can say "Not available" (or omit the
 *     row) instead of guessing.
 */
import type { FinalReport, PerformanceAndCost, RoundHistoryEntry, SessionMeta } from "./ws";

export const CATEGORY_ORDER = ["functionality", "security", "compliance"] as const;
export type CategoryKey = (typeof CATEGORY_ORDER)[number];

export const CATEGORY_LABELS: Record<string, string> = {
  functionality: "Functionality",
  security: "Security",
  compliance: "Compliance",
};

export type Tone = "success" | "danger" | "warning" | "neutral";
export type CategoryState = "passed" | "failed" | "incomplete" | "not_evaluated";

export interface CategoryStat {
  key: CategoryKey;
  label: string;
  state: CategoryState;
  tone: Tone;
  /** Rounds recorded for the category (scored or not). */
  rounds: number;
  /** Rounds that produced a pass/fail verdict — the denominator of "x/y passed". */
  scored: number;
  passed: number;
  failed: number;
  /** Rounds that ran but have no verdict. */
  unscored: number;
  /** "5/5 passed", or "Not evaluated" — the one string every tile shows. */
  headline: string;
  /** Extra qualifier shown next to the headline, e.g. a partial run. */
  note: string | null;
  /** One human-readable sentence explaining the result, built from the rounds. */
  summary: string;
}

// ==========================================================================
// Small helpers
// ==========================================================================
type ScoreKey = "task_completion" | "security" | "compliance";

/** Which metrics gate pass/fail per category — mirrors aggregator.GATING_METRICS. */
const GATING: Record<CategoryKey, ScoreKey[]> = {
  functionality: ["task_completion", "security", "compliance"],
  security: ["security", "compliance"],
  compliance: ["security", "compliance"],
};

const SCORE_LABELS: Record<ScoreKey, string> = {
  task_completion: "task completion",
  security: "security",
  compliance: "compliance",
};

/** The single metric whose average best represents each category. */
const HEADLINE_METRIC: Record<CategoryKey, ScoreKey> = {
  functionality: "task_completion",
  security: "security",
  compliance: "compliance",
};

const TONE_FOR_STATE: Record<CategoryState, Tone> = {
  passed: "success",
  failed: "danger",
  incomplete: "warning",
  not_evaluated: "neutral",
};

export const STATE_LABELS: Record<CategoryState, string> = {
  passed: "Passed",
  failed: "Failed",
  incomplete: "Incomplete",
  not_evaluated: "Not evaluated",
};

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** First sentence(s) of a judge note, capped so one long note can't swamp a card. */
function shorten(text: string, max = 220): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
  return stop > 60 ? cut.slice(0, stop + 1) : `${cut.trimEnd()}…`;
}

function average(rounds: RoundHistoryEntry[], key: ScoreKey): number | null {
  const values = rounds.map((r) => r[key]).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  return Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10;
}

function difficultyRange(rounds: RoundHistoryEntry[]): string | null {
  const values = rounds.map((r) => r.difficulty).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return min === max ? `difficulty ${min}` : `difficulty ${min}–${max}`;
}

function lowestGatingScore(key: CategoryKey, round: RoundHistoryEntry): { label: string; score: number } | null {
  let best: { label: string; score: number } | null = null;
  for (const metric of GATING[key]) {
    const score = round[metric];
    if (score !== null && (best === null || score < best.score)) {
      best = { label: SCORE_LABELS[metric], score };
    }
  }
  return best;
}

// ==========================================================================
// Per-category stats + the sentence explaining each result
// ==========================================================================
export function deriveCategoryStat(key: CategoryKey, report: FinalReport): CategoryStat {
  const label = CATEGORY_LABELS[key];
  const cat = report.categories[key];
  const history = cat ? cat.round_history : [];

  // Absent from report.categories (or present but with no rounds at all) means
  // it never ran — say so plainly instead of implying a result either way.
  if (!cat || history.length === 0) {
    return {
      key,
      label,
      state: "not_evaluated",
      tone: TONE_FOR_STATE.not_evaluated,
      rounds: 0,
      scored: 0,
      passed: 0,
      failed: 0,
      unscored: 0,
      headline: "Not evaluated",
      note: null,
      summary: `${label} was not evaluated in this session, so nothing can be concluded about it.`,
    };
  }

  const scoredRounds = history.filter((r) => r.passed !== null);
  const scored = scoredRounds.length;
  const passed = scoredRounds.filter((r) => r.passed === true).length;
  const failed = scored - passed;
  const unscored = history.length - scored;
  const incomplete = Boolean(cat.incomplete);

  let state: CategoryState;
  if (scored === 0) state = "incomplete";
  else if (failed > 0) state = "failed";
  else if (incomplete) state = "incomplete";
  else state = "passed";

  let summary: string;
  if (state === "failed") {
    const first = scoredRounds.find((r) => r.passed === false) as RoundHistoryEntry;
    const low = lowestGatingScore(key, first);
    summary = `${failed} of ${plural(scored, "evaluated round")} failed. The first failure was round ${first.round_number}`;
    if (first.difficulty !== null) summary += ` (difficulty ${first.difficulty})`;
    summary += low ? `, where the lowest gating score was ${low.label} (${low.score}/10).` : ".";
    if (first.reasoning) summary += ` Judge's note: ${shorten(first.reasoning)}`;
    if (incomplete) summary += " The run was also cut short by an error.";
  } else if (state === "incomplete") {
    summary =
      scored === 0
        ? `${plural(history.length, "round")} ran but none produced a pass/fail verdict.`
        : `${passed} of ${plural(scored, "evaluated round")} passed, but the run was cut short by an error, so this is not a full pass.`;
  } else {
    const range = difficultyRange(scoredRounds);
    const metric = HEADLINE_METRIC[key];
    const avg = average(scoredRounds, metric);
    summary = `${scored === 1 ? "The 1 evaluated round" : `All ${scored} evaluated rounds`} passed${
      range ? ` (${range})` : ""
    }, with no breaking point found within the tested range.`;
    if (avg !== null) summary += ` Average ${SCORE_LABELS[metric]} score: ${avg}/10.`;
  }

  return {
    key,
    label,
    state,
    tone: TONE_FOR_STATE[state],
    rounds: history.length,
    scored,
    passed,
    failed,
    unscored,
    headline: scored === 0 ? "No scored rounds" : `${passed}/${scored} passed`,
    note: incomplete ? "Run cut short by an error" : null,
    summary,
  };
}

export function deriveAllStats(report: FinalReport): CategoryStat[] {
  return CATEGORY_ORDER.map((key) => deriveCategoryStat(key, report));
}

// ==========================================================================
// Overall status + the short summary under "Evaluation Summary"
// ==========================================================================
export interface OverallSummary {
  /** Pill text: REVIEW REQUIRED, CERTIFIED ROBUST, ... */
  label: string;
  tone: Tone;
  /** Short plain-language explanation of the major result. */
  text: string;
}

function plainResult(s: CategoryStat): string {
  switch (s.state) {
    case "not_evaluated":
      return `${s.label} was not evaluated.`;
    case "failed":
      return `${s.label} did not pass (${s.passed} of ${plural(s.scored, "round")} passed).`;
    case "incomplete":
      return s.scored === 0
        ? `${s.label} has no scored rounds.`
        : `${s.label} is incomplete: ${s.passed} of ${plural(s.scored, "round")} passed before the run was cut short.`;
    case "passed":
      return s.scored === 1 ? `${s.label} passed its only round.` : `${s.label} passed all ${s.scored} rounds.`;
  }
}

export function deriveOverall(stats: CategoryStat[]): OverallSummary {
  const evaluated = stats.filter((s) => s.state !== "not_evaluated");
  const needsReview = evaluated.filter((s) => s.state === "failed" || s.state === "incomplete");
  const notEvaluated = stats.filter((s) => s.state === "not_evaluated");

  let label: string;
  let tone: Tone;
  if (evaluated.length === 0) {
    label = "NO RESULTS";
    tone = "neutral";
  } else if (needsReview.length > 0) {
    label = "REVIEW REQUIRED";
    tone = "warning";
  } else if (notEvaluated.length > 0) {
    label = "PASSED — PARTIAL RUN";
    tone = "success";
  } else {
    label = "CERTIFIED ROBUST";
    tone = "success";
  }

  let closing: string;
  if (evaluated.length === 0) {
    closing = "No rounds were recorded for this session.";
  } else if (needsReview.length > 0) {
    closing = `${needsReview.length} of ${evaluated.length} evaluated ${
      evaluated.length === 1 ? "category" : "categories"
    } ${needsReview.length === 1 ? "needs" : "need"} review.`;
  } else {
    closing = "No issues were found in the evaluated categories within the tested range.";
  }

  const text = evaluated.length === 0 ? closing : `${stats.map(plainResult).join(" ")} ${closing}`;
  return { label, tone, text };
}

// ==========================================================================
// Evaluation Overview card
// ==========================================================================
export interface OverviewData {
  evaluatedCategories: string[];
  notEvaluatedCategories: string[];
  roundsPerCategory: { label: string; rounds: number }[];
  totalRounds: number;
  passedRounds: number;
  failedRounds: number;
  /** Rounds that ran but have no verdict (only shown when > 0). */
  unscoredRounds: number;
  /** Categories that failed or were cut short — what "Review required" counts. */
  categoriesNeedingReview: number;
  durationSeconds: number | null;
}

export function deriveOverview(report: FinalReport, stats: CategoryStat[]): OverviewData {
  const evaluated = stats.filter((s) => s.state !== "not_evaluated");
  return {
    evaluatedCategories: evaluated.map((s) => s.label),
    notEvaluatedCategories: stats.filter((s) => s.state === "not_evaluated").map((s) => s.label),
    roundsPerCategory: evaluated.map((s) => ({ label: s.label, rounds: s.rounds })),
    totalRounds: report.performance_and_cost.total_rounds,
    passedRounds: evaluated.reduce((sum, s) => sum + s.passed, 0),
    failedRounds: evaluated.reduce((sum, s) => sum + s.failed, 0),
    unscoredRounds: evaluated.reduce((sum, s) => sum + s.unscored, 0),
    categoriesNeedingReview: evaluated.filter((s) => s.state === "failed" || s.state === "incomplete").length,
    durationSeconds: report.duration_seconds ?? null,
  };
}

// ==========================================================================
// Token usage card
//
// The backend only records ONE token figure per round — `tokens_used`, whatever
// the agent under test itself reports — and no input/output split, so input and
// output tokens are always "Not available". EvalMind's own judge/generator LLM
// usage is not tracked at all. Nothing is estimated.
// ==========================================================================
export interface TokenUsage {
  totalTokens: number | null;
  estimatedCost: number | null;
  /** Some (not all) rounds had no figure, so the total undercounts. */
  tokensPartial: boolean;
  costPartial: boolean;
}

export function deriveTokenUsage(perf: PerformanceAndCost): TokenUsage {
  const rounds = perf.total_rounds;
  // total_tokens_used / total_estimated_cost are 0 when NO round reported
  // anything — that 0 means "no data", not "zero tokens", so it must not be shown.
  const hasTokens = rounds > 0 && perf.rounds_missing_token_data < rounds;
  const hasCost = rounds > 0 && perf.rounds_missing_cost_data < rounds;
  return {
    totalTokens: hasTokens ? perf.total_tokens_used : null,
    estimatedCost: hasCost ? perf.total_estimated_cost : null,
    tokensPartial: hasTokens && perf.rounds_missing_token_data > 0,
    costPartial: hasCost && perf.rounds_missing_cost_data > 0,
  };
}

// ==========================================================================
// AI / Session Details + Agent Profile — only rows the backend really has
// ==========================================================================
export interface DetailRow {
  label: string;
  value: string;
}

function describeModels(meta: SessionMeta): string | null {
  const models = meta.evaluation_models;
  if (!models || Object.keys(models).length === 0) return null;
  const provider = meta.evaluation_provider ? ` (${meta.evaluation_provider})` : "";
  const unique = Array.from(new Set(Object.values(models)));
  if (unique.length === 1) return `${unique[0]}${provider}`;
  return `${Object.entries(models)
    .map(([role, model]) => `${capitalize(role)}: ${model}`)
    .join(" · ")}${provider}`;
}

function describeTemperatures(meta: SessionMeta): string | null {
  const temps = meta.temperatures;
  if (!temps || Object.keys(temps).length === 0) return null;
  return Object.entries(temps)
    .map(([role, value]) => `${capitalize(role)} ${value === null ? "default" : value}`)
    .join(" · ");
}

export function deriveSessionDetails(report: FinalReport): DetailRow[] {
  const meta: SessionMeta = report.session_meta ?? {};
  const rows: DetailRow[] = [];

  const models = describeModels(meta);
  if (models) rows.push({ label: "Evaluation model", value: models });
  if (meta.framework) rows.push({ label: "Evaluation framework", value: meta.framework });
  const temps = describeTemperatures(meta);
  if (temps) rows.push({ label: "Temperature", value: temps });
  if (typeof meta.max_rounds === "number") {
    rows.push({ label: "Max rounds per category", value: String(meta.max_rounds) });
  }
  if (typeof meta.start_difficulty === "number" && typeof meta.max_difficulty === "number") {
    rows.push({ label: "Difficulty range", value: `${meta.start_difficulty}–${meta.max_difficulty}` });
  }
  if (typeof meta.pass_threshold === "number") {
    rows.push({ label: "Pass threshold", value: `${meta.pass_threshold}/10` });
  }
  rows.push({ label: "Session ID", value: report.session_id });
  return rows;
}

export interface AgentProfile {
  name: string | null;
  type: string | null;
  purpose: string | null;
  /** The user's "Agent / Chatbot Brief"; null when they didn't provide one. */
  description: string | null;
  endpoint: string | null;
  connection: string | null;
  authentication: string | null;
}

export function deriveAgentProfile(report: FinalReport): AgentProfile {
  const meta: SessionMeta = report.session_meta ?? {};
  return {
    name: meta.agent_name ?? null,
    type: meta.agent_type ?? null,
    // What EvalMind determined the agent does (auto-discovery, or the override).
    purpose: report.aut_description?.trim() || null,
    description: report.agent_brief?.trim() || null,
    endpoint: meta.endpoint ?? null,
    connection: meta.connection_mode ?? null,
    authentication: meta.auth ?? null,
  };
}

// ==========================================================================
// Formatting
// ==========================================================================
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** null when the backend had nothing to measure from — callers show "Not available". */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** estimated_cost values can be very small (rounded to 6dp server-side, see
 * aggregator.py::_aggregate_performance_and_cost) — show more precision for
 * sub-cent amounts so a real cost doesn't just read as "$0.00". */
export function formatCost(cost: number): string {
  return `$${cost.toFixed(cost > 0 && cost < 0.01 ? 6 : 2)}`;
}
