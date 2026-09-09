import { useState } from "react";
import SessionHistoryPanel from "./SessionHistoryPanel";
import type {
  AUTConnectionRequest,
  BrowserConnectionRequest,
  ConnectionRequest,
  CustomEndpointConnectionRequest,
  PublicAPIConnectionRequest,
  SessionStartRequest,
  SocketIOConnectionRequest,
  SwaggerConnectionRequest,
} from "../lib/types";
import {
  defaultAUTConnectionRequest,
  defaultBrowserConnectionRequest,
  defaultCustomEndpointConnectionRequest,
  defaultPublicAPIConnectionRequest,
  defaultSocketIOConnectionRequest,
  defaultSwaggerConnectionRequest,
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
  const [connectionMode, setConnectionMode] = useState<"http" | "socketio" | "direct_http" | "public_api" | "swagger" | "browser">(
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
  const [swaggerConnection, setSwaggerConnection] = useState<SwaggerConnectionRequest>(
    defaultSwaggerConnectionRequest(),
  );
  const [swaggerShowToken, setSwaggerShowToken] = useState(false);
  const [browserConnection, setBrowserConnection] = useState<BrowserConnectionRequest>(
    defaultBrowserConnectionRequest(),
  );
  const [browserShowPassword, setBrowserShowPassword] = useState(false);
  const [maxRounds, setMaxRounds] = useState<number>(5);
  const [capabilityOverride, setCapabilityOverride] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showSocketioAdvanced, setShowSocketioAdvanced] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadSessionId, setReloadSessionId] = useState("");

  // Evaluation control
  const ALL_CATEGORIES = ["functionality", "security", "compliance"] as const;
  const [selectedCategories, setSelectedCategories] = useState<string[]>([...ALL_CATEGORIES]);
  const [startDifficulty, setStartDifficulty] = useState<number>(1);
  const [maxDifficulty, setMaxDifficulty] = useState<number>(5);
  const [passThreshold, setPassThreshold] = useState<number>(6);

  function toggleCategory(cat: string) {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  }

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

  function updateSwaggerConnection<K extends keyof SwaggerConnectionRequest>(
    key: K,
    value: SwaggerConnectionRequest[K],
  ) {
    setSwaggerConnection((prev) => ({ ...prev, [key]: value }));
  }

  function updateBrowserConnection<K extends keyof BrowserConnectionRequest>(
    key: K,
    value: BrowserConnectionRequest[K],
  ) {
    setBrowserConnection((prev) => ({ ...prev, [key]: value }));
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
    } else if (connectionMode === "swagger") {
      if (!swaggerConnection.chat_endpoint_url.trim()) {
        setFormError("Chat endpoint URL is required.");
        return;
      }
      if (!swaggerConnection.spec_url.trim()) {
        setFormError("OpenAPI spec URL is required.");
        return;
      }
      activeConnection = swaggerConnection;
    } else if (connectionMode === "browser") {
      if (!browserConnection.chatbot_url.trim()) {
        setFormError("Chatbot page URL is required.");
        return;
      }
      // Selectors are optional — blank = auto-detect at runtime
      if (browserConnection.requires_login) {
        if (!browserConnection.login_url?.trim()) {
          setFormError("Login URL is required when login is enabled.");
          return;
        }
        if (!browserConnection.username?.trim() || !browserConnection.password) {
          setFormError("Username and password are required when login is enabled.");
          return;
        }
      }
      activeConnection = browserConnection;
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
    if (selectedCategories.length === 0) {
      setFormError("Select at least one category to evaluate.");
      return;
    }
    if (startDifficulty > maxDifficulty) {
      setFormError("Start difficulty cannot exceed max difficulty.");
      return;
    }

    const request: SessionStartRequest = {
      connection: activeConnection,
      max_rounds: maxRounds,
      capability_description_override: capabilityOverride.trim() ? capabilityOverride.trim() : null,
      categories: selectedCategories.length < 3 ? selectedCategories : null,
      start_difficulty: startDifficulty !== 1 ? startDifficulty : null,
      max_difficulty: maxDifficulty !== 5 ? maxDifficulty : null,
      pass_threshold: passThreshold !== 6 ? passThreshold : null,
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
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
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
            <button
              type="button"
              onClick={() => setConnectionMode("swagger")}
              aria-pressed={connectionMode === "swagger"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "swagger"
                  ? "border-violet-500 bg-violet-600/20 text-violet-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              Swagger / OpenAPI
            </button>
            <button
              type="button"
              onClick={() => setConnectionMode("browser")}
              aria-pressed={connectionMode === "browser"}
              className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                connectionMode === "browser"
                  ? "border-emerald-500 bg-emerald-600/20 text-emerald-200"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
              }`}
            >
              Browser (Playwright)
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

        {connectionMode === "swagger" && (
          <>
            {/* Info callout */}
            <div className="rounded-md border border-violet-800 bg-violet-950/40 px-4 py-3 text-sm text-violet-300">
              <p className="font-medium text-violet-200 mb-1">🔍 Swagger / OpenAPI Auto-Discovery</p>
              <p>
                EvalMind will fetch your spec, find the matching endpoint, read its request body
                schema, and automatically identify which field carries the chat message.
                No manual payload mapping needed.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="swagger_endpoint_url" className="text-sm font-medium text-slate-200">
                Chat endpoint URL
              </label>
              <input
                id="swagger_endpoint_url"
                type="text"
                required
                placeholder="https://api.example.com/v1/chat"
                value={swaggerConnection.chat_endpoint_url}
                onChange={(e) => updateSwaggerConnection("chat_endpoint_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <p className="text-xs text-slate-500">
                The actual endpoint EvalMind will POST to on every evaluation call.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="swagger_spec_url" className="text-sm font-medium text-slate-200">
                OpenAPI / Swagger spec URL
              </label>
              <input
                id="swagger_spec_url"
                type="text"
                required
                placeholder="https://api.example.com/openapi.json"
                value={swaggerConnection.spec_url}
                onChange={(e) => updateSwaggerConnection("spec_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <p className="text-xs text-slate-500">
                URL of the spec document (JSON or YAML). Try{" "}
                <code className="text-slate-400">/openapi.json</code>,{" "}
                <code className="text-slate-400">/swagger.json</code>, or{" "}
                <code className="text-slate-400">/api-docs</code>.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <label htmlFor="swagger_bearer_token" className="text-sm font-medium text-slate-200">
                  Bearer token <span className="text-slate-500">(optional)</span>
                </label>
                <button
                  type="button"
                  onClick={() => setSwaggerShowToken((v) => !v)}
                  className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {swaggerShowToken ? "Hide" : "Show"}
                </button>
              </div>
              <input
                id="swagger_bearer_token"
                type={swaggerShowToken ? "text" : "password"}
                placeholder="eyJ… (optional — used for spec fetch + every AUT call)"
                value={swaggerConnection.bearer_token ?? ""}
                onChange={(e) =>
                  updateSwaggerConnection(
                    "bearer_token",
                    e.target.value.trim() ? e.target.value.trim() : null,
                  )
                }
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <p className="text-xs text-slate-500">
                Sent as <code className="text-slate-400">Authorization: Bearer …</code> when
                fetching the spec and on every evaluation call. Leave blank for public APIs.
              </p>
            </div>
          </>
        )}

        {connectionMode === "browser" && (
          <>
            {/* Info callout */}
            <div className="rounded-md border border-emerald-800 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-300">
              <p className="font-medium text-emerald-200 mb-1">🌐 Browser (Playwright) Mode</p>
              <p>
                EvalMind opens a real Chromium browser, types the task into the chat input,
                clicks Send, waits for the reply, and scrapes the response — no API needed.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="browser_chatbot_url" className="text-sm font-medium text-slate-200">
                Chatbot page URL
              </label>
              <input
                id="browser_chatbot_url"
                type="text"
                required
                placeholder="https://answers.reddit.com"
                value={browserConnection.chatbot_url}
                onChange={(e) => updateBrowserConnection("chatbot_url", e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="flex flex-col gap-2">
                <label htmlFor="browser_input_selector" className="text-sm font-medium text-slate-200">
                  Input selector <span className="text-slate-500">(optional)</span>
                </label>
                <input
                  id="browser_input_selector"
                  type="text"
                  placeholder="Auto-detect or: textarea"
                  value={browserConnection.input_selector}
                  onChange={(e) => updateBrowserConnection("input_selector", e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
              </div>

              <div className="flex flex-col gap-2">
                <label htmlFor="browser_send_selector" className="text-sm font-medium text-slate-200">
                  Send button selector <span className="text-slate-500">(optional)</span>
                </label>
                <input
                  id="browser_send_selector"
                  type="text"
                  placeholder="Auto-detect or: button[type=submit]"
                  value={browserConnection.send_selector}
                  onChange={(e) => updateBrowserConnection("send_selector", e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
              </div>

              <div className="flex flex-col gap-2">
                <label htmlFor="browser_response_selector" className="text-sm font-medium text-slate-200">
                  Response selector <span className="text-slate-500">(optional)</span>
                </label>
                <input
                  id="browser_response_selector"
                  type="text"
                  placeholder="Auto-detect or: .message:last-child"
                  value={browserConnection.response_selector}
                  onChange={(e) => updateBrowserConnection("response_selector", e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
                <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <label htmlFor="browser_chat_launcher_selector" className="text-sm font-medium text-slate-200">
                Chat launcher button selector <span className="text-slate-500">(optional)</span>
              </label>
              <input
                id="browser_chat_launcher_selector"
                type="text"
                placeholder="e.g. button[aria-label='Open AI Assistant'] or .ai-assistant-btn"
                value={browserConnection.chat_launcher_selector ?? ""}
                onChange={(e) =>
                  updateBrowserConnection("chat_launcher_selector", e.target.value.trim() || null)
                }
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
              <p className="text-xs text-slate-500">
                If the chat opens in a popup/modal triggered by a floating button (not already visible
                on page load), give its selector here — EvalMind clicks it once before looking for the
                input box. Leave blank if the chat is already open by default.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <label htmlFor="browser_wait_strategy" className="text-sm font-medium text-slate-200">
                  Wait strategy
                </label>
                <select
                  id="browser_wait_strategy"
                  value={browserConnection.wait_strategy}
                  onChange={(e) =>
                    updateBrowserConnection(
                      "wait_strategy",
                      e.target.value as "new_element" | "text_change" | "fixed_delay",
                    )
                  }
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  <option value="text_change">text_change — poll until text changes</option>
                  <option value="new_element">new_element — wait for element to appear</option>
                  <option value="fixed_delay">fixed_delay — wait N seconds then read</option>
                </select>
              </div>

              <div className="flex flex-col gap-2">
                <label htmlFor="browser_wait_timeout" className="text-sm font-medium text-slate-200">
                  Response timeout (s)
                </label>
                <input
                  id="browser_wait_timeout"
                  type="number"
                  min={5}
                  max={300}
                  value={browserConnection.wait_timeout_seconds}
                  onChange={(e) =>
                    updateBrowserConnection("wait_timeout_seconds", Number(e.target.value))
                  }
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2">
              <label htmlFor="browser_headless" className="text-sm font-medium text-slate-200">
                Run browser in headless mode
              </label>
              <input
                id="browser_headless"
                type="checkbox"
                checked={browserConnection.headless}
                onChange={(e) => updateBrowserConnection("headless", e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
              />
            </div>

            {/* Login toggle */}
            <div className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2">
              <label htmlFor="browser_requires_login" className="text-sm font-medium text-slate-200">
                This chatbot requires login
              </label>
              <input
                id="browser_requires_login"
                type="checkbox"
                checked={browserConnection.requires_login}
                onChange={(e) => updateBrowserConnection("requires_login", e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
              />
            </div>

            {browserConnection.requires_login && (
              <div className="flex flex-col gap-4 rounded-md border border-emerald-900 bg-emerald-950/20 p-4">
                <div className="flex flex-col gap-2">
                  <label htmlFor="browser_login_url" className="text-sm font-medium text-slate-200">
                    Login page URL
                  </label>
                  <input
                    id="browser_login_url"
                    type="text"
                    placeholder="https://reddit.com/login"
                    value={browserConnection.login_url ?? ""}
                    onChange={(e) =>
                      updateBrowserConnection("login_url", e.target.value.trim() || null)
                    }
                    className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="browser_username_sel" className="text-sm font-medium text-slate-200">
                      Username selector <span className="text-slate-500">(optional)</span>
                    </label>
                    <input
                      id="browser_username_sel"
                      type="text"
                      placeholder="Auto-detect or: input[name='username']"
                      value={browserConnection.username_selector ?? ""}
                      onChange={(e) =>
                        updateBrowserConnection("username_selector", e.target.value.trim() || null)
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                    <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor="browser_password_sel" className="text-sm font-medium text-slate-200">
                      Password selector <span className="text-slate-500">(optional)</span>
                    </label>
                    <input
                      id="browser_password_sel"
                      type="text"
                      placeholder="Auto-detect or: input[type='password']"
                      value={browserConnection.password_selector ?? ""}
                      onChange={(e) =>
                        updateBrowserConnection("password_selector", e.target.value.trim() || null)
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                    <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <label htmlFor="browser_submit_sel" className="text-sm font-medium text-slate-200">
                      Submit selector <span className="text-slate-500">(optional)</span>
                    </label>
                    <input
                      id="browser_submit_sel"
                      type="text"
                      placeholder="Auto-detect or: button[type='submit']"
                      value={browserConnection.submit_selector ?? ""}
                      onChange={(e) =>
                        updateBrowserConnection("submit_selector", e.target.value.trim() || null)
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-100 placeholder:text-slate-500 placeholder:font-sans focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                    <p className="text-xs text-slate-500">Leave blank to auto-detect</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="browser_username" className="text-sm font-medium text-slate-200">
                      Username
                    </label>
                    <input
                      id="browser_username"
                      type="text"
                      autoComplete="off"
                      value={browserConnection.username ?? ""}
                      onChange={(e) =>
                        updateBrowserConnection("username", e.target.value || null)
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <label htmlFor="browser_password" className="text-sm font-medium text-slate-200">
                        Password
                      </label>
                      <button
                        type="button"
                        onClick={() => setBrowserShowPassword((v) => !v)}
                        className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                      >
                        {browserShowPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                    <input
                      id="browser_password"
                      type={browserShowPassword ? "text" : "password"}
                      autoComplete="new-password"
                      value={browserConnection.password ?? ""}
                      onChange={(e) =>
                        updateBrowserConnection("password", e.target.value || null)
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label htmlFor="browser_login_success" className="text-sm font-medium text-slate-200">
                    Wait for URL to contain <span className="text-slate-500">(after login)</span>
                  </label>
                  <input
                    id="browser_login_success"
                    type="text"
                    placeholder="/dashboard  or  /home  (leave blank to wait 2s)"
                    value={browserConnection.login_success_url_contains ?? ""}
                    onChange={(e) =>
                      updateBrowserConnection(
                        "login_success_url_contains",
                        e.target.value.trim() || null,
                      )
                    }
                    className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>
              </div>
            )}
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

            {/* Category selection */}
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-slate-200">Categories to evaluate</span>
              <div className="flex flex-wrap gap-3">
                {ALL_CATEGORIES.map((cat) => (
                  <label key={cat} className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={selectedCategories.includes(cat)}
                      onChange={() => toggleCategory(cat)}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500"
                    />
                    <span className="capitalize">{cat}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-slate-500">Uncheck categories to skip them entirely in this run.</p>
            </div>

            {/* Difficulty range */}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <label htmlFor="start_difficulty" className="text-sm font-medium text-slate-200">
                  Start difficulty <span className="text-slate-500">(1–5)</span>
                </label>
                <input
                  id="start_difficulty"
                  type="number"
                  min={1}
                  max={5}
                  value={startDifficulty}
                  onChange={(e) => setStartDifficulty(Number(e.target.value))}
                  className="w-24 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor="max_difficulty" className="text-sm font-medium text-slate-200">
                  Max difficulty <span className="text-slate-500">(1–5)</span>
                </label>
                <input
                  id="max_difficulty"
                  type="number"
                  min={1}
                  max={5}
                  value={maxDifficulty}
                  onChange={(e) => setMaxDifficulty(Number(e.target.value))}
                  className="w-24 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            </div>
            <p className="-mt-2 text-xs text-slate-500">
              Default: 1→5. Raise start difficulty to skip easy rounds for AUTs you know perform
              well at low difficulties.
            </p>

            {/* Pass threshold */}
            <div className="flex flex-col gap-2">
              <label htmlFor="pass_threshold" className="text-sm font-medium text-slate-200">
                Pass threshold <span className="text-slate-500">(1–10, default 6)</span>
              </label>
              <input
                id="pass_threshold"
                type="number"
                min={1}
                max={10}
                value={passThreshold}
                onChange={(e) => setPassThreshold(Number(e.target.value))}
                className="w-24 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-500">
                Minimum primary-metric score (task completion / security / compliance) for a round to
                count as PASS. Raise for stricter evaluation, lower for more lenient.
              </p>
            </div>

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

      {/* Session history */}
      <div className="flex flex-col gap-3 border-t border-slate-800 pt-6">
        <h2 className="text-sm font-medium text-slate-200">Past Sessions</h2>
        <SessionHistoryPanel onViewReport={onLoadReport} />
      </div>
    </div>
  );
}

function defaultSocketioConnectionRequest_safe(): SocketIOConnectionRequest {
  return defaultSocketIOConnectionRequest();
}
