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
  /** Max seconds of no chat:token/chat:data activity before the response
   * is treated as finished. Leave unset to use the connector's fixed
   * 150.0s default. Raise this for AUTs with slow-but-alive backend pauses
   * (e.g. a cold container/DB connection on the first call of a session)
   * that would otherwise get mistaken for "done" and truncated mid-
   * response. Must stay below response_timeout_seconds above, or the hard
   * timeout wins first — see aut/connector.py::_call_socketio_endpoint's
   * _silence_watcher. */
  token_silence_timeout_seconds?: number;
}

export function defaultSocketIOConnectionRequest(): SocketIOConnectionRequest {
  return {
    mode: "socketio",
    chat_endpoint_url: "",
    bearer_token: "",
    origin_header: null,
    // Must stay above token_silence_timeout_seconds below (whether left at
    // the connector's fixed 150s default or overridden) or the hard
    // timeout always wins first, even on a stream that's still alive but
    // has gone quiet. See aut/connector.py::_call_socketio_endpoint's
    // _silence_watcher.
    response_timeout_seconds: 200.0,
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

/** Mirrors aut/auth.py::SwaggerConnectionRequest exactly. The AUT is an
 * HTTP endpoint whose request payload format is described by an OpenAPI /
 * Swagger spec. EvalMind fetches the spec, matches the endpoint, reads the
 * requestBody schema, and identifies the message field automatically.
 *
 * Use this mode when the API has a /openapi.json or /swagger.yaml and its
 * request body is NOT just {"task": "..."} — e.g. {"message":"...","session_id":"abc"}. */
export interface SwaggerConnectionRequest {
  mode: "swagger";
  /** The actual API endpoint EvalMind POSTs to on every call. */
  chat_endpoint_url: string;
  /** URL of the OpenAPI/Swagger spec document (JSON or YAML). */
  spec_url: string;
  /** Optional bearer token — sent when fetching the spec AND as the
   *  Authorization header on every AUT call. */
  bearer_token: string | null;
  timeout_seconds: number;
}

export function defaultSwaggerConnectionRequest(): SwaggerConnectionRequest {
  return {
    mode: "swagger",
    chat_endpoint_url: "",
    spec_url: "",
    bearer_token: null,
    timeout_seconds: 30.0,
  };
}

/** Mirrors aut/auth.py::BrowserConnectionRequest exactly. The AUT is a
 * web chatbot UI driven by a real Playwright-controlled Chromium browser.
 * EvalMind types the task into the chat input, clicks Send, waits for the
 * reply, and scrapes the text — no API key or endpoint needed.
 *
 * requires_login=false → just the chatbot URL + 3 selectors.
 * requires_login=true  → also fill in the login URL, selectors, credentials. */
export interface BrowserConnectionRequest {
  mode: "browser";
  /** URL of the chatbot page EvalMind opens in the browser. */
  chatbot_url: string;
  /** CSS selector for the text input / textarea. */
  input_selector: string;
  /** CSS selector for the Send / Submit button. */
  send_selector: string;
  /** CSS selector for the response message element. */
  response_selector: string;
  /** How EvalMind knows the response is ready:
   *  'new_element' — waits for response_selector to appear in DOM,
   *  'text_change' — polls until response_selector's text changes,
   *  'fixed_delay'  — waits fixed_delay_seconds then reads. */
  wait_strategy: "new_element" | "text_change" | "fixed_delay";
  wait_timeout_seconds: number;
  fixed_delay_seconds: number;
  /** Run browser in headless mode (faster, no visible window). */
  headless: boolean;
  /** Set true to automate the login sequence before evaluation starts. */
  requires_login: boolean;
  login_url: string | null;
  username_selector: string | null;
  password_selector: string | null;
  submit_selector: string | null;
  username: string | null;
  password: string | null;
  /** After clicking submit, wait for the URL to contain this string. */
  login_success_url_contains: string | null;
  /** After clicking submit, wait for this CSS selector to appear. */
  login_success_selector: string | null;
  /** Selector for a floating/launcher button that must be clicked to open
   * the chat widget before typing (e.g. a floating "Open Assistant" icon
   * that mounts the real chat modal only once clicked). Leave null if the
   * chat input is already visible on page load. */
  chat_launcher_selector: string | null;
}

export function defaultBrowserConnectionRequest(): BrowserConnectionRequest {
  return {
    mode: "browser",
    chatbot_url: "",
    input_selector: "",    // blank = auto-detect
    send_selector: "",     // blank = auto-detect
    response_selector: "", // blank = auto-detect
    wait_strategy: "text_change",
    wait_timeout_seconds: 60.0,
    fixed_delay_seconds: 5.0,
    headless: true,
    requires_login: false,
    login_url: null,
    username_selector: null,
    password_selector: null,
    submit_selector: null,
    username: null,
    password: null,
    login_success_url_contains: null,
    login_success_selector: null,
    chat_launcher_selector: null,
  };
}

/** Mirrors aut/auth.py::ConnectionRequest — a discriminated union (on
 * `mode`) of all six connection types. */
export type ConnectionRequest =
  | AUTConnectionRequest
  | SocketIOConnectionRequest
  | CustomEndpointConnectionRequest
  | PublicAPIConnectionRequest
  | SwaggerConnectionRequest
  | BrowserConnectionRequest;


/** Mirrors backend/app/main.py::SessionStartRequest exactly — the one JSON
 * message a /ws/run client sends immediately after the WebSocket connects.
 *
 * New evaluation-control fields added alongside capability_description_override:
 * - categories: subset of the three categories to run (default: all three)
 * - start_difficulty: difficulty level to begin each loop at (default: 1)
 * - max_difficulty: highest difficulty the loop will reach (default: 5)
 * - pass_threshold: minimum primary-metric score to count as PASS (default: 6)
 */
export interface SessionStartRequest {
  connection: ConnectionRequest;
  max_rounds: number;
  capability_description_override: string | null;
  /** Subset of categories to evaluate — omit or set null to run all three. */
  categories?: string[] | null;
  /** Starting difficulty for each category loop (1–5). */
  start_difficulty?: number | null;
  /** Maximum difficulty the escalating loop will reach (1–5). */
  max_difficulty?: number | null;
  /** Pass/fail threshold for primary metrics (1–10, default 6). */
  pass_threshold?: number | null;
}
