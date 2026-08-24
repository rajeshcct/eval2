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
}

// ==========================================================================
// ProgressEvent — discriminated union on `type`, mirroring progress.py's
// EVENT_TYPES and each event's documented `data` payload exactly.
// ==========================================================================
export type ProgressEvent =
  | { type: "describer_started"; data: Record<string, never> }
  | { type: "describer_completed"; data: DescriberResult }
  | { type: "category_started"; data: { category: string } }
  | { type: "round_started"; data: { category: string; round_number: number; difficulty: number } }
  | { type: "round_completed"; data: RoundResult }
  | { type: "category_completed"; data: CategoryLoopResult }
  | { type: "session_completed"; data: FinalReport }
  | { type: "error"; data: { stage: string; message: string } };

export const PROGRESS_EVENT_TYPES = [
  "describer_started",
  "describer_completed",
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

/** GET /api/sessions/{session_id}/report — used by Phase V's reload path;
 * defined here now since the base URL constant lives in this module. */
export async function fetchSessionReport(sessionId: string): Promise<FinalReport> {
  const res = await fetch(`${BACKEND_HTTP_URL}/api/sessions/${encodeURIComponent(sessionId)}/report`);
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
