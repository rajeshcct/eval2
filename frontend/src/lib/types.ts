/**
 * src/lib/types.ts
 *
 * Phase III — request types mirroring the backend's Pydantic models
 * field-for-field, so a form submission serializes into exactly what
 * `backend/app/main.py`'s `SessionStartRequest` (and its nested
 * `aut/auth.py::AUTConnectionRequest`) expects. Keep this in lockstep with
 * those two Python models by hand — there is no shared schema generation
 * step in this project (see EvalMind_Frontend_Implementation_Plan.md,
 * Phase III item 2).
 */

/** Mirrors aut/auth.py::AUTConnectionRequest exactly (field names, order,
 * optionality, and defaults). Submitted once per session from the New
 * Session form when "HTTP / REST" connection type is selected. */
export interface AUTConnectionRequest {
  mode: "http";
  chat_endpoint_url: string;
  requires_login: boolean;

  login_endpoint_url: string | null;
  username: string | null;
  password: string | null;

  /** The JSON key the AUT's login response returns the token under.
   * Confirmed as "auth_token" for the current AUT, but kept configurable —
   * matches the Python default exactly. */
  token_field: string;
  /** Kept configurable rather than hardcoded — matches the Python default
   * exactly. `{token}` is substituted server-side. */
  auth_header_format: string;

  timeout_seconds: number;
}

export function defaultAUTConnectionRequest(): AUTConnectionRequest {
  return {
    mode: "http",
    chat_endpoint_url: "",
    requires_login: false,
    login_endpoint_url: null,
    username: null,
    password: null,
    token_field: "auth_token",
    auth_header_format: "Bearer {token}",
    timeout_seconds: 30.0,
  };
}

/** Mirrors aut/auth.py::SocketIOConnectionRequest exactly (field names,
 * order, optionality, and defaults). Submitted once per session from the
 * New Session form when "Socket.IO (JWT)" connection type is selected. */
export interface SocketIOConnectionRequest {
  mode: "socketio";
  chat_endpoint_url: string;
  bearer_token: string;
  origin_header: string | null;
  response_timeout_seconds: number;

  // Advanced/optional — mirrors the Python Optional[str] = None fields.
  // Only sent (non-undefined) when the user has actually filled them in;
  // JSON.stringify drops undefined keys, matching "only included in the
  // submitted object if non-empty".
  socketio_path?: string;
  chat_message_event?: string;
}

export function defaultSocketIOConnectionRequest(): SocketIOConnectionRequest {
  return {
    mode: "socketio",
    chat_endpoint_url: "",
    bearer_token: "",
    origin_header: null,
    response_timeout_seconds: 120.0,
  };
}

/** Mirrors aut/auth.py::CustomEndpointConnectionRequest exactly. Simple
 * direct HTTP POST — no login, no JWT. For APIs like NotchZero that just
 * accept a POST with a JSON body containing the user message. */
export interface CustomEndpointConnectionRequest {
  mode: "direct_http";
  chat_endpoint_url: string;
  /** JSON key for the message body — defaults to "task", set to "user_input"
   * for APIs that expect that field name instead. */
  task_field: string;
  timeout_seconds: number;
}

export function defaultCustomEndpointConnectionRequest(): CustomEndpointConnectionRequest {
  return {
    mode: "direct_http",
    chat_endpoint_url: "",
    task_field: "task",
    timeout_seconds: 30.0,
  };
}

/** Mirrors aut/auth.py::PublicAPIConnectionRequest exactly. The AUT IS an
 * LLM, called directly (no endpoint URL, no login) — just a system prompt
 * and a CrewAI model string. Submitted once per session from the New
 * Session form when "Public API (LLM)" connection type is selected. The
 * provider's API key lives in the backend's own .env, never submitted from
 * this form. */
export interface PublicAPIConnectionRequest {
  mode: "public_api";
  system_prompt: string;
  model: string;
  temperature?: number;
}

export function defaultPublicAPIConnectionRequest(): PublicAPIConnectionRequest {
  return {
    mode: "public_api",
    system_prompt: "",
    model: "",
  };
}

/** Mirrors aut/auth.py::ConnectionRequest — a discriminated union (on
 * `mode`) of all four connection types. */
export type ConnectionRequest =
  | AUTConnectionRequest
  | SocketIOConnectionRequest
  | CustomEndpointConnectionRequest
  | PublicAPIConnectionRequest;

/** Mirrors backend/app/main.py::SessionStartRequest exactly — the one JSON
 * message a /ws/run client sends immediately after the WebSocket connects. */
export interface SessionStartRequest {
  connection: ConnectionRequest;
  max_rounds: number;
  capability_description_override: string | null;
}
