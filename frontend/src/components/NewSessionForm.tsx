import { useState } from "react";
import type {
  AUTConnectionRequest,
  ConnectionRequest,
  CustomEndpointConnectionRequest,
  PublicAPIConnectionRequest,
  SessionStartRequest,
  SocketIOConnectionRequest,
} from "../lib/types";
import {
  defaultAUTConnectionRequest,
  defaultCustomEndpointConnectionRequest,
  defaultPublicAPIConnectionRequest,
  defaultSocketIOConnectionRequest,
} from "../lib/types";

interface NewSessionFormProps {
  onStart: (request: SessionStartRequest) => void;
  /** Phase V's independent reload path, also reachable straight from the
   * landing page: fetches a finished report via GET
   * /api/sessions/{id}/report without starting anything. */
  onLoadReport: (sessionId: string) => void;
  disabled?: boolean;
}

/**
 * Phase III — the app's landing page. Per the plan: a chat_endpoint_url
 * field; a "requires login?" toggle that conditionally reveals
 * login_endpoint_url / username / password; a max_rounds number input
 * (default 5); a "Start Evaluation" button that opens the /ws/run
 * connection and immediately sends the SessionStartRequest.
 *
 * token_field / auth_header_format / timeout_seconds and
 * capability_description_override are exposed too (they're real,
 * non-optional-to-the-backend or genuinely useful fields on the request
 * schema — see aut/auth.py and backend/app/main.py) but tucked behind an
 * "Advanced" disclosure so the common path stays a two-field form.
 *
 * A "Connection type" selector at the top switches between HTTP/REST (the
 * above) and Socket.IO (JWT) — chat_endpoint_url / bearer_token /
 * origin_header, with socketio_path / chat_message_event /
 * token_silence_timeout_seconds behind their own "Advanced" disclosure,
 * mirroring aut/auth.py::SocketIOConnectionRequest. Whichever type is
 * active is what gets submitted as `connection`.
 *
 * Phase V adds a second, independent affordance below the form itself: a
 * plain session_id input + "View report" button that calls onLoadReport,
 * the same reload-by-session_id path a `?session_id=...` URL triggers on
 * load (see App.tsx) — lets a finished report be reopened from the
 * landing page without needing to hand-edit a URL.
 */
export default function NewSessionForm({ onStart, onLoadReport, disabled }: NewSessionFormProps) {
  const [connectionMode, setConnectionMode] = useState<"http" | "socketio" | "direct_http" | "public_api">(
    "http",
  );
  const [connection, setConnection] = useState<AUTConnectionRequest>(defaultAUTConnectionRequest());
  const [socketioConnection, setSocketioConnection] = useState<SocketIOConnectionRequest>(
    defaultSocketioConnectionRequest_safe(),
  );
  const [directHttpConnection, setDirectHttpConnection] = useState<CustomEndpointConnectionRequest>(
    defaultCustomEndpointConnectionRequest(),
  );
  const [publicApiConnection, setPublicApiConnection] = useState<PublicAPIConnectionRequest>(
    defaultPublicAPIConnectionRequest(),
  );
  const [maxRounds, setMaxRounds] = useState<number>(5);
  const [capabilityOverride, setCapabilityOverride] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showSocketioAdvanced, setShowSocketioAdvanced] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadSessionId, setReloadSessionId] = useState("");

  function updateConnection<K extends keyof AUTConnectionRequest>(key: K, value: AUTConnectionRequest[K]) {
    setConnection((prev) => ({ ...prev, [key]: value }));
  }

  function updateSocketioConnection<K extends keyof SocketIOConnectionRequest>(
    key: K,
    value: SocketIOConnectionRequest[K],
  ) {
    setSocketioConnection((prev) => ({ ...prev, [key]: value }));
  }

  function updateDirectHttpConnection<K extends keyof CustomEndpointConnectionRequest>(
    key: K,
    value: CustomEndpointConnectionRequest[K],
  ) {
    setDirectHttpConnection((prev) => ({ ...prev, [key]: value }));
  }

  function updatePublicApiConnection<K extends keyof PublicAPIConnectionRequest>(
    key: K,
    value: PublicAPIConnectionRequest[K],
  ) {
    setPublicApiConnection((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    let activeConnection: ConnectionRequest;

    if (connectionMode === "http") {
      if (!connection.chat_endpoint_url.trim()) {
        setFormError("Chat endpoint URL is required.");
        return;
      }
      if (connection.requires_login) {
        if (!connection.login_endpoint_url?.trim()) {
          setFormError("Login endpoint URL is required when “requires login” is on.");
          return;
        }
        if (!connection.username?.trim() || !connection.password) {
          setFormError("Username and password are required when “requires login” is on.");
          return;
        }
      }
      activeConnection = connection;
    } else if (connectionMode === "direct_http") {
      if (!directHttpConnection.chat_endpoint_url.trim()) {
        setFormError("Chat endpoint URL is required.");
        return;
      }
      if (!directHttpConnection.task_field.trim()) {
        setFormError("Task field name is required.");
        return;
      }
      activeConnection = directHttpConnection;
    } else if (connectionMode === "public_api") {
      if (!publicApiConnection.system_prompt.trim()) {
        setFormError("System prompt is required.");
        return;
      }
      if (!publicApiConnection.model.trim()) {
        setFormError("Model is required.");
        return;
      }
      activeConnection = publicApiConnection;
    } else {
      if (!socketioConnection.chat_endpoint_url.trim()) {
        setFormError("Chat endpoint URL is required.");
        return;
      }
      if (!socketioConnection.bearer_token.trim()) {
        setFormError("JWT token is required.");
        return;
      }
      activeConnection = socketioConnection;
    }

    if (!Number.isInteger(maxRounds) || maxRounds < 1) {
      setFormError("Max rounds must be a whole number ≥ 1.");
      return;
    }

    const request: SessionStartRequest = {
      connection: activeConnection,
      max_rounds: maxRounds,
      capability_description_override: capabilityOverride.trim() ? capabilityOverride.trim() : null,
    };
    onStart(request);
  }

  function handleLoadReport() {
    const trimmed = reloadSessionId.trim();
    if (trimmed) onLoadReport(trimmed);
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-10">
      <form onSubmit={handleSubmit} className="flex w-full flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">New Evaluation Session</h1>
          <p className="mt-1 text-sm text-slate-400">
            Point EvalMind at an Agent Under Test and start a live evaluation.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-slate-200">Connection type</span>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <button
              type="button"
              onClick={() => setConnectionMode("http")}
              aria-pressed={connectionMode === "http"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "http"
                  ? "border-indigo-500 bg-indigo-600/20 text-indigo-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              HTTP / REST
            </button>
            <button
              type="button"
              onClick={() => setConnectionMode("direct_http")}
              aria-pressed={connectionMode === "direct_http"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "direct_http"
                  ? "border-indigo-500 bg-indigo-600/20 text-indigo-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              HTTP (No Login)
            </button>
            <button
              type="button"
              onClick={() => setConnectionMode("socketio")}
              aria-pressed={connectionMode === "socketio"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "socketio"
                  ? "border-indigo-500 bg-indigo-600/20 text-indigo-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              Socket.IO (JWT)
            </button>
            <button
              type="button"
              onClick={() => setConnectionMode("public_api")}
              aria-pressed={connectionMode === "public_api"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "public_api"
                  ? "border-indigo-500 bg-indigo-600/20 text-indigo-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              Public API (LLM)
            </button>
          </div>
        </div>

        {connectionMode === "http" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="chat_endpoint_url" className="text-sm font-medium text-slate-200">
                Chat endpoint URL
              </label>
              <input
                id="chat_endpoint_url"
                type="text"
                required
                placeholder="https://your-aut.example.com/chat"
                value={connection.chat_endpoint_url}
                onChange={(e) => updateConnection("chat_endpoint_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2">
              <label htmlFor="requires_login" className="text-sm font-medium text-slate-200">
                This AUT requires login
              </label>
              <input
                id="requires_login"
                type="checkbox"
                checked={connection.requires_login}
                onChange={(e) => updateConnection("requires_login", e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500"
              />
            </div>

            {connection.requires_login && (
              <div className="flex flex-col gap-4 rounded-md border border-slate-800 bg-slate-900/30 p-4">
                <div className="flex flex-col gap-2">
                  <label htmlFor="login_endpoint_url" className="text-sm font-medium text-slate-200">
                    Login endpoint URL
                  </label>
                  <input
                    id="login_endpoint_url"
                    type="text"
                    placeholder="https://your-aut.example.com/login"
                    value={connection.login_endpoint_url ?? ""}
                    onChange={(e) => updateConnection("login_endpoint_url", e.target.value)}
                    className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="username" className="text-sm font-medium text-slate-200">
                      Username
                    </label>
                    <input
                      id="username"
                      type="text"
                      value={connection.username ?? ""}
                      onChange={(e) => updateConnection("username", e.target.value)}
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor="password" className="text-sm font-medium text-slate-200">
                      Password
                    </label>
                    <input
                      id="password"
                      type="password"
                      value={connection.password ?? ""}
                      onChange={(e) => updateConnection("password", e.target.value)}
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {connectionMode === "direct_http" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="direct_chat_endpoint_url" className="text-sm font-medium text-slate-200">
                Chat endpoint URL
              </label>
              <input
                id="direct_chat_endpoint_url"
                type="text"
                required
                placeholder="https://demo-ai-api.notchzero.com/generate_response"
                value={directHttpConnection.chat_endpoint_url}
                onChange={(e) => updateDirectHttpConnection("chat_endpoint_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="task_field" className="text-sm font-medium text-slate-200">
                Request body field name
              </label>
              <input
                id="task_field"
                type="text"
                placeholder="task"
                value={directHttpConnection.task_field}
                onChange={(e) => updateDirectHttpConnection("task_field", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-500">
                The JSON key sent to the API (e.g. <code className="text-slate-400">task</code> or{" "}
                <code className="text-slate-400">user_input</code>). Check the API docs.
              </p>
            </div>
          </>
        )}

        {connectionMode === "public_api" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="public_api_system_prompt" className="text-sm font-medium text-slate-200">
                System prompt
              </label>
              <textarea
                id="public_api_system_prompt"
                required
                rows={4}
                placeholder="You are a helpful customer support assistant for Acme Co..."
                value={publicApiConnection.system_prompt}
                onChange={(e) => updatePublicApiConnection("system_prompt", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-500">
                The AUT isn't a deployed endpoint here — it's this system prompt plus the model below,
                called directly.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="public_api_model" className="text-sm font-medium text-slate-200">
                Model
              </label>
              <input
                id="public_api_model"
                type="text"
                required
                placeholder="groq/llama-3.1-8b-instant"
                value={publicApiConnection.model}
                onChange={(e) => updatePublicApiConnection("model", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-500">
                A CrewAI model string, e.g. <code className="text-slate-400">groq/llama-3.1-8b-instant</code>,{" "}
                <code className="text-slate-400">openai/gpt-4o-mini</code>, or{" "}
                <code className="text-slate-400">anthropic/claude-3-5-sonnet-20241022</code>. The provider's API
                key comes from the backend's own <code className="text-slate-400">.env</code> — nothing to
                enter here.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="public_api_temperature" className="text-sm font-medium text-slate-200">
                Temperature <span className="text-slate-500">(optional)</span>
              </label>
              <input
                id="public_api_temperature"
                type="number"
                min={0}
                max={2}
                step={0.1}
                placeholder="Provider default"
                value={publicApiConnection.temperature ?? ""}
                onChange={(e) =>
                  updatePublicApiConnection(
                    "temperature",
                    e.target.value.trim() ? Number(e.target.value) : undefined,
                  )
                }
                className="w-32 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </>
        )}

        {connectionMode === "socketio" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="socketio_chat_endpoint_url" className="text-sm font-medium text-slate-200">
                Chat endpoint URL
              </label>
              <input
                id="socketio_chat_endpoint_url"
                type="text"
                required
                placeholder="https://your-aut.example.com"
                value={socketioConnection.chat_endpoint_url}
                onChange={(e) => updateSocketioConnection("chat_endpoint_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="bearer_token" className="text-sm font-medium text-slate-200">
                JWT token
              </label>
              <input
                id="bearer_token"
                type="password"
                required
                autoComplete="off"
                placeholder="Bearer token for this AUT"
                value={socketioConnection.bearer_token}
                onChange={(e) => updateSocketioConnection("bearer_token", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="origin_header" className="text-sm font-medium text-slate-200">
                Origin URL <span className="text-slate-500">(optional)</span>
              </label>
              <input
                id="origin_header"
                type="text"
                placeholder="https://your-aut-frontend.example.com"
                value={socketioConnection.origin_header ?? ""}
                onChange={(e) =>
                  updateSocketioConnection("origin_header", e.target.value.trim() ? e.target.value : null)
                }
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-500">For CORS — must match the AUT's real frontend origin.</p>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowSocketioAdvanced((v) => !v)}
                className="text-sm text-indigo-400 hover:text-indigo-300"
              >
                {showSocketioAdvanced ? "Hide advanced options" : "Show advanced options"}
              </button>
            </div>

            {showSocketioAdvanced && (
              <div className="flex flex-col gap-4 rounded-md border border-slate-800 bg-slate-900/30 p-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="socketio_path" className="text-sm font-medium text-slate-200">
                      Socket.IO path
                    </label>
                    <input
                      id="socketio_path"
                      type="text"
                      placeholder="/socket.io/"
                      value={socketioConnection.socketio_path ?? ""}
                      onChange={(e) =>
                        updateSocketioConnection(
                          "socketio_path",
                          e.target.value.trim() ? e.target.value : undefined,
                        )
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor="chat_message_event" className="text-sm font-medium text-slate-200">
                      Chat message event
                    </label>
                    <input
                      id="chat_message_event"
                      type="text"
                      placeholder="chat_message"
                      value={socketioConnection.chat_message_event ?? ""}
                      onChange={(e) =>
                        updateSocketioConnection(
                          "chat_message_event",
                          e.target.value.trim() ? e.target.value : undefined,
                        )
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="socketio_response_timeout_seconds"
                    className="text-sm font-medium text-slate-200"
                  >
                    Response timeout (seconds)
                  </label>
                  <input
                    id="socketio_response_timeout_seconds"
                    type="number"
                    min={1}
                    step={1}
                    value={socketioConnection.response_timeout_seconds}
                    onChange={(e) =>
                      updateSocketioConnection("response_timeout_seconds", Number(e.target.value))
                    }
                    className="w-32 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <p className="text-xs text-slate-500">
                    Keep this above the token silence timeout below (150s by default) — the hard
                    timeout can't fire after the silence fallback already has, only before.
                  </p>
                </div>

                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="socketio_token_silence_timeout_seconds"
                    className="text-sm font-medium text-slate-200"
                  >
                    Token silence timeout (seconds){" "}
                    <span className="text-slate-500">(optional)</span>
                  </label>
                  <input
                    id="socketio_token_silence_timeout_seconds"
                    type="number"
                    min={1}
                    step={1}
                    placeholder="150 (connector default)"
                    value={socketioConnection.token_silence_timeout_seconds ?? ""}
                    onChange={(e) =>
                      updateSocketioConnection(
                        "token_silence_timeout_seconds",
                        e.target.value.trim() ? Number(e.target.value) : undefined,
                      )
                    }
                    className="w-40 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <p className="text-xs text-slate-500">
                    How long the AUT can go quiet (no streamed tokens/data) before its response is
                    treated as finished. Raise this if an AUT has a slow-but-alive pause — e.g. a
                    cold container or slow query on the first call of a session — that's getting
                    mistaken for "done" and truncating the response. Must stay below the response
                    timeout above.
                  </p>
                </div>
              </div>
            )}
          </>
        )}

        <div className="flex flex-col gap-2">
          <label htmlFor="max_rounds" className="text-sm font-medium text-slate-200">
            Max rounds per category
          </label>
          <input
            id="max_rounds"
            type="number"
            min={1}
            max={5}
            value={maxRounds}
            onChange={(e) => setMaxRounds(Number(e.target.value))}
            className="w-32 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-sm text-indigo-400 hover:text-indigo-300"
          >
            {showAdvanced ? "Hide advanced options" : "Show advanced options"}
          </button>
        </div>

        {showAdvanced && (
          <div className="flex flex-col gap-4 rounded-md border border-slate-800 bg-slate-900/30 p-4">
            {connectionMode === "http" && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="token_field" className="text-sm font-medium text-slate-200">
                      Login response token field
                    </label>
                    <input
                      id="token_field"
                      type="text"
                      value={connection.token_field}
                      onChange={(e) => updateConnection("token_field", e.target.value)}
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor="auth_header_format" className="text-sm font-medium text-slate-200">
                      Auth header format
                    </label>
                    <input
                      id="auth_header_format"
                      type="text"
                      value={connection.auth_header_format}
                      onChange={(e) => updateConnection("auth_header_format", e.target.value)}
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label htmlFor="timeout_seconds" className="text-sm font-medium text-slate-200">
                    Request timeout (seconds)
                  </label>
                  <input
                    id="timeout_seconds"
                    type="number"
                    min={1}
                    step={1}
                    value={connection.timeout_seconds}
                    onChange={(e) => updateConnection("timeout_seconds", Number(e.target.value))}
                    className="w-32 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </>
            )}

            <div className="flex flex-col gap-2">
              <label htmlFor="capability_override" className="text-sm font-medium text-slate-200">
                Capability description override <span className="text-slate-500">(optional)</span>
              </label>
              <textarea
                id="capability_override"
                rows={3}
                placeholder="Leave blank to auto-discover the AUT's capabilities via the Describer."
                value={capabilityOverride}
                onChange={(e) => setCapabilityOverride(e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>
        )}

        {formError && (
          <div className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {formError}
          </div>
        )}

        <button
          type="submit"
          disabled={disabled}
          className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {disabled ? "Starting…" : "Start Evaluation"}
        </button>
      </form>

      <div className="flex flex-col gap-2 border-t border-slate-800 pt-6">
        <label htmlFor="reload_session_id" className="text-sm font-medium text-slate-200">
          Already ran a session? View its report
        </label>
        <div className="flex gap-2">
          <input
            id="reload_session_id"
            type="text"
            placeholder="session_id"
            value={reloadSessionId}
            onChange={(e) => setReloadSessionId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleLoadReport();
              }
            }}
            className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <button
            type="button"
            onClick={handleLoadReport}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
          >
            View report
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Or open a link with <code className="text-slate-400">?session_id=...</code> in the URL directly.
        </p>
      </div>
    </div>
  );
}

function defaultSocketioConnectionRequest_safe(): SocketIOConnectionRequest {
  return defaultSocketIOConnectionRequest();
}
