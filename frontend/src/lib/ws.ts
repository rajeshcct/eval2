/**
 * src/lib/ws.ts
 *
 * Phase III — typed WS client. `ProgressEvent` mirrors `progress.py`'s
 * contract exactly: same `type` string literals, same `data` shape per
 * type (each pulled from the Pydantic model's own `.model_dump()` that
 * `emit_event(...)` calls in Python — see pipeline.py::RoundResult,
 * loop_runner.py::CategoryLoopResult, agents/schemas.py::DescriberResult,
 * aggregator.py::FinalReport). Keep this file in lockstep with those
 * models by hand, same caveat as src/lib/types.ts.
 */

// ==========================================================================
// Result/report shapes — mirror the Python Pydantic models' .model_dump()
// output field-for-field.
// ==========================================================================

/** Mirrors agents/schemas.py::DescriberResult. */
export interface DescriberResult {
  capability_description: string;
  self_reported_summary: string;
  observed_summary: string;
  mismatch_notes: string | null;
}

/** Mirrors agents/schemas.py::DescriptionComparisonResult. */
export interface DescriptionComparisonResult {
  similarity_score: number;
  descriptions_match: boolean;
  combined_description: string;
  user_description_summary: string;
  aut_self_report_summary: string;
  mismatch_notes: string | null;
}

/** Mirrors pipeline.py::RoundResult. */
export interface RoundResult {
  session_id: string;
  round_id: string;
  round_number: number;
  category: string;
  difficulty: number;

  task: string;
  output: string;

  // Primary metrics (drive `passed`)
  task_completion: number;
  security: number;
  compliance: number;
  // Secondary metrics (context only)
  accuracy: number;
  relevance: number;
  hallucination: number;
  safety: number;

  passed: boolean;
  reasoning: string;

  latency_ms: number;
  tokens_used: number | null;
  estimated_cost: number | null;
  /** EvalMind's own Generator + Judge usage for this round. */
  eval_tokens?: number | null;
  eval_cost?: number | null;
}

/** Mirrors loop_runner.py::CategoryLoopResult. */
export interface CategoryLoopResult {
  category: string;
  status: "broken" | "robust_within_tested_range";
  breaking_point: number | null;
  rounds: RoundResult[];
}

/** Mirrors aggregator.py::RoundHistoryEntry. */
export interface RoundHistoryEntry {
  round_number: number;
  difficulty: number | null;
  task: string | null;
  output: string | null;

  task_completion: number | null;
  security: number | null;
  compliance: number | null;
  accuracy: number | null;
  relevance: number | null;
  hallucination: number | null;
  safety: number | null;

  passed: boolean | null;
  reasoning: string | null;

  latency_ms: number | null;
  tokens_used: number | null;
  estimated_cost: number | null;
}

/** Mirrors aggregator.py::CategoryReport. */
export interface CategoryReport {
  category: string;
  status: "broken" | "robust_within_tested_range";
  breaking_point_round: number | null;
  breaking_point_summary: string | null;
  round_history: RoundHistoryEntry[];
  /** True when this category's loop was cut short by an error (partial run).
   * Optional: absent on reports stored before this field existed. */
  incomplete?: boolean;
}

/** Mirrors aggregator.py::PerformanceAndCost. */
export interface PerformanceAndCost {
  total_rounds: number;

  total_latency_ms: number;
  average_latency_ms: number;

  total_tokens_used: number;
  average_tokens_used: number | null;
  rounds_missing_token_data: number;

  total_estimated_cost: number;
  average_estimated_cost: number | null;
  rounds_missing_cost_data: number;

  /** EvalMind's own Generator + Judge LLM usage, separate from the agent under
   * test's figures above. Optional/null on sessions recorded before it was tracked. */
  evaluator_total_tokens?: number | null;
  evaluator_prompt_tokens?: number | null;
  evaluator_completion_tokens?: number | null;
  evaluator_total_cost?: number | null;
  rounds_missing_evaluator_data?: number;
  rounds_missing_evaluator_cost?: number;
}

/** Mirrors aggregator.py::FinalReport. */
export interface FinalReport {
  session_id: string;
  aut_description: string;
  started_at: string;
  generated_at: string;

  overall_verdict: string;
  categories: Record<string, CategoryReport>;
  performance_and_cost: PerformanceAndCost;
  /** Categories cut short by an error (partial run). Optional/absent on older reports. */
  incomplete_categories?: string[];

  // --- Session context (all optional: absent/null on sessions recorded before
  // these existed, and the report UI only renders what is actually present). ---
  /** The user's optional "Agent / Chatbot Brief". */
  agent_brief?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  /** Seconds from session start to the last recorded round. */
  duration_seconds?: number | null;
  /** Secret-free connection + run settings snapshot taken when the session started. */
  session_meta?: SessionMeta | null;
}

/** Mirrors the dict built by session.py::_build_session_meta (which merges in
 * backend/app/main.py::_connection_meta). Every key is optional because older
 * sessions have none of them and the UI must never invent a missing value. */
export interface SessionMeta {
  agent_name?: string;
  agent_type?: string;
  /** Human-readable connection type, e.g. "HTTP / REST". */
  connection_mode?: string;
  /** scheme://host/path only — credentials and query strings are stripped server-side. */
  endpoint?: string;
  /** The KIND of auth configured (never a credential). */
  auth?: string;
  framework?: string;
  evaluation_provider?: string;
  /** role (describer/generator/judge/aggregator) -> model id. */
  evaluation_models?: Record<string, string>;
  /** role -> temperature actually applied; null means the provider default was used. */
  temperatures?: Record<string, number | null>;
  max_rounds?: number;
  categories_requested?: string[];
  start_difficulty?: number;
  max_difficulty?: number;
  pass_threshold?: number;
}

// ==========================================================================
// ProgressEvent — discriminated union on `type`, mirroring progress.py's
// EVENT_TYPES and each event's documented `data` payload exactly.
// ==========================================================================
export type ProgressEvent =
  | { type: "describer_started"; data: Record<string, never> }
  | { type: "describer_completed"; data: DescriberResult }
  | { type: "description_comparison_started"; data: { user_description: string } }
  | { type: "description_comparison_completed"; data: DescriptionComparisonResult }
  | { type: "capability_mismatch"; data: DescriptionComparisonResult }
  | { type: "category_started"; data: { category: string } }
  | { type: "round_started"; data: { category: string; round_number: number; difficulty: number } }
  | { type: "round_completed"; data: RoundResult }
  | { type: "category_completed"; data: CategoryLoopResult }
  | { type: "session_completed"; data: FinalReport }
  | { type: "error"; data: { stage: string; message: string } };

export const PROGRESS_EVENT_TYPES = [
  "describer_started",
  "describer_completed",
  "description_comparison_started",
  "description_comparison_completed",
  "capability_mismatch",
  "category_started",
  "round_started",
  "round_completed",
  "category_completed",
  "session_completed",
  "error",
] as const;

// ==========================================================================
// Typed WS client
// ==========================================================================
import type { SessionStartRequest } from "./types";

export const BACKEND_WS_URL = import.meta.env.VITE_BACKEND_WS_URL;
export const BACKEND_HTTP_URL = import.meta.env.VITE_BACKEND_HTTP_URL;

export interface RunWebSocketHandlers {
  onEvent: (event: ProgressEvent) => void;
  /** Fired on a raw WS-level error (e.g. connection refused) — distinct
   * from a ProgressEvent of type "error", which is a well-formed message
   * the backend sent deliberately (see backend/app/main.py's
   * _send_error_and_close). */
  onSocketError?: (ev: Event) => void;
  /** Fired when the socket closes, whatever the reason (clean
   * session_completed/error close, or a dropped connection). */
  onClose?: (ev: CloseEvent) => void;
  onOpen?: () => void;
}

/**
 * Opens the /ws/run connection, sends the SessionStartRequest as soon as
 * the socket is open (per backend/app/main.py: "On connect, wait for one
 * JSON message from the client"), and forwards every subsequent message as
 * a parsed ProgressEvent via handlers.onEvent.
 *
 * Returns the raw WebSocket so the caller can close() it early if needed
 * (e.g. the user navigates away mid-run).
 */
export function startRun(request: SessionStartRequest, handlers: RunWebSocketHandlers): WebSocket {
  const socket = new WebSocket(`${BACKEND_WS_URL}/ws/run`);

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(request));
    handlers.onOpen?.();
  });

  socket.addEventListener("message", (ev) => {
    try {
      const parsed = JSON.parse(ev.data) as ProgressEvent;
      handlers.onEvent(parsed);
    } catch (e) {
      // A malformed frame should never crash the UI — surface it the same
      // way a backend-sent "error" event would.
      handlers.onEvent({
        type: "error",
        data: { stage: "ws_client_parse", message: `Could not parse message from server: ${e}` },
      });
    }
  });

  if (handlers.onSocketError) {
    socket.addEventListener("error", handlers.onSocketError);
  }
  if (handlers.onClose) {
    socket.addEventListener("close", handlers.onClose);
  }

  return socket;
}

/** Send a JSON message through an existing WebSocket (used for mismatch
 * confirmation responses). Safe to call even if the socket is closing. */
export function sendWsMessage(socket: WebSocket, message: Record<string, unknown>): void {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

/** Returns Authorization header with the stored Bearer token, or empty. */
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("evalmind_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** GET /api/sessions/{session_id}/report — used by Phase V's reload path;
 * defined here now since the base URL constant lives in this module. */
export async function fetchSessionReport(sessionId: string): Promise<FinalReport> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/sessions/${encodeURIComponent(sessionId)}/report`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`GET /api/sessions/${sessionId}/report failed: HTTP ${res.status}`);
  }
  return (await res.json()) as FinalReport;
}

/** GET /api/health */
export async function fetchHealth(): Promise<{ status: string; llm_configured: boolean }> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/health`);
  if (!res.ok) {
    throw new Error(`GET /api/health failed: HTTP ${res.status}`);
  }
  return await res.json();
}

/** Mirrors backend SessionSummary \u2014 one row from GET /api/sessions. */
export interface SessionSummary {
  id: string;
  aut_description: string;
  started_at: string;
  has_report: boolean;
  project_id?: string | null;
  project_name?: string | null;
  /** Display name recorded at session start; absent on older sessions. */
  agent_name?: string | null;
}

/** GET /api/sessions \u2014 list recent sessions, newest first. */
export async function fetchSessions(limit = 50, projectId?: string | null): Promise<SessionSummary[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (projectId) qs.set("project_id", projectId);
  const res = await fetch(`${BACKEND_HTTP_URL}/api/sessions?${qs.toString()}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`GET /api/sessions failed: HTTP ${res.status}`);
  return (await res.json()) as SessionSummary[];
}

/** DELETE /api/sessions/{session_id} \u2014 permanently deletes a session + all rounds. */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`DELETE /api/sessions/${sessionId} failed: HTTP ${res.status}`);
}

/** POST /api/sessions/{session_id}/report \u2014 re-judge all rounds and rebuild the report. */
export async function rejudgeSession(sessionId: string): Promise<FinalReport> {
  const res = await fetch(
    `${BACKEND_HTTP_URL}/api/sessions/${encodeURIComponent(sessionId)}/report`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`POST rejudge for ${sessionId} failed: HTTP ${res.status}`);
  return (await res.json()) as FinalReport;
}

// ==========================================================================
// Projects — an organizational layer above sessions (Project -> Sessions ->
// Rounds). A session keeps its own session_id; a project only groups them.
// ==========================================================================

/** Mirrors backend ProjectSummary — one row from GET /api/projects. */
export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  session_count: number;
}

/** Pulls FastAPI's `detail` message out of an error response, falling back to
 * the HTTP status, so e.g. a duplicate project name shows its real reason. */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Not JSON — fall through to the generic message.
  }
  return `${fallback}: HTTP ${res.status}`;
}

/** GET /api/projects — all projects with their session counts. */
export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/projects`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await errorMessage(res, "GET /api/projects failed"));
  return (await res.json()) as Project[];
}

/** POST /api/projects — create a project (names are unique, case-insensitive). */
export async function createProject(name: string, description: string | null): Promise<Project> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Could not create project"));
  return (await res.json()) as Project;
}

/** PUT /api/sessions/{id}/project — file an existing session under a project
 * (null unfiles it). */
export async function assignSessionProject(sessionId: string, projectId: string | null): Promise<void> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/sessions/${encodeURIComponent(sessionId)}/project`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Could not update the session's project"));
}
