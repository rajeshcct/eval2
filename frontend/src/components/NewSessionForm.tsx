import { useState, useEffect } from "react";
import { resolveProjectConfig, saveProjectConfig } from "../lib/projectConfig";
import SessionHistoryPanel from "./SessionHistoryPanel";
import { themeFor } from "./categoryTheme";
import type { ProjectTarget } from "../lib/types";
import type {
  AUTConnectionRequest,
  BrowserConnectionRequest,
  ConnectionRequest,
  SessionStartRequest,
  SocketIOConnectionRequest,
  SwaggerConnectionRequest,
} from "../lib/types";
import {
  defaultAUTConnectionRequest,
  defaultBrowserConnectionRequest,
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
  /** Project to have pre-selected in "Organize this evaluation" (e.g. when
   * starting another session from a report that belongs to a project). */
  initialProject?: ProjectTarget | null;
  /** When true, suppress the built-in page header (used inside the new
   * sidebar layout where the shell provides its own heading). */
  hideHeader?: boolean;
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
export default function NewSessionForm({ onStart, onLoadReport, disabled, initialProject, hideHeader }: NewSessionFormProps) {
  const [connectionMode, setConnectionMode] = useState<"http" | "socketio" | "swagger" | "browser">(
    "http",
  );
  const [connection, setConnection] = useState<AUTConnectionRequest>(defaultAUTConnectionRequest());
  const [socketioConnection, setSocketioConnection] = useState<SocketIOConnectionRequest>(
    defaultSocketioConnectionRequest_safe(),
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
  const [userDescription, setUserDescription] = useState<string>("");
  const [showUserDescription, setShowUserDescription] = useState(false);
  // Project the next-started session is filed under (chosen in "Organize this
  // evaluation" at the bottom of the page). null = not filed.
  const projectTarget = initialProject ?? null;
  // Bumped whenever a project is created or a session is moved/deleted, so the
  // Projects list above Past Sessions reloads.
  const [listRefresh, setListRefresh] = useState(0);
  const bumpLists = () => setListRefresh((n) => n + 1);

  // Evaluation control
  const ALL_CATEGORIES = ["functionality", "security", "compliance"] as const;
  const [selectedCategories, setSelectedCategories] = useState<string[]>([...ALL_CATEGORIES]);
  const [startDifficulty, setStartDifficulty] = useState<number>(1);
  const [maxDifficulty, setMaxDifficulty] = useState<number>(5);
  const [passThreshold, setPassThreshold] = useState<number>(6);

  // Derived, read-only display values for the "Setup summary" sidebar card —
  // recomputed each render from whichever connection mode is active.
  const currentEndpoint =
    connectionMode === "http"
      ? connection.chat_endpoint_url.trim()
      : connectionMode === "socketio"
        ? socketioConnection.chat_endpoint_url.trim()
        : connectionMode === "swagger"
          ? swaggerConnection.chat_endpoint_url.trim()
          : browserConnection.chatbot_url.trim();

  const currentAuthLabel =
    connectionMode === "http"
      ? connection.requires_login
        ? "Login (username / password)"
        : "None configured"
      : connectionMode === "socketio"
        ? socketioConnection.bearer_token.trim()
          ? "Bearer token (JWT)"
          : "Token not set yet"
        : connectionMode === "swagger"
          ? swaggerConnection.bearer_token?.trim()
            ? "Bearer token"
            : "None configured"
          : browserConnection.requires_login
            ? "Browser login (username / password)"
            : "None configured";

  useEffect(() => {
    if (!initialProject) return;
    resolveProjectConfig(initialProject.id).then((cfg) => {
      if (!cfg) return;
      if (cfg.connectionMode) setConnectionMode(cfg.connectionMode);
      if (cfg.http) setConnection((prev) => ({ ...prev, ...cfg.http }));
      if (cfg.socketio) setSocketioConnection((prev) => ({ ...prev, ...cfg.socketio }));
      if (cfg.swagger) setSwaggerConnection((prev) => ({ ...prev, ...cfg.swagger }));
      if (cfg.browser) setBrowserConnection((prev) => ({ ...prev, ...cfg.browser }));
      
      if (typeof cfg.maxRounds === "number") setMaxRounds(cfg.maxRounds);
      if (typeof cfg.capabilityOverride === "string") setCapabilityOverride(cfg.capabilityOverride);
      if (Array.isArray(cfg.categories)) setSelectedCategories(cfg.categories);
      if (typeof cfg.startDifficulty === "number") setStartDifficulty(cfg.startDifficulty);
      if (typeof cfg.maxDifficulty === "number") setMaxDifficulty(cfg.maxDifficulty);
      if (typeof cfg.passThreshold === "number") setPassThreshold(cfg.passThreshold);
      if (typeof cfg.userDescription === "string") {
        setUserDescription(cfg.userDescription);
        if (cfg.userDescription) setShowUserDescription(true);
      }
    });
  }, [initialProject]);

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
      user_capability_description: userDescription.trim() ? userDescription.trim() : null,
      // The same "Describe your chatbot" text is also stored as the session's
      // description, so it shows up as the Description in the report's Agent Profile.
      agent_brief: userDescription.trim() ? userDescription.trim() : null,
      project_id: projectTarget ? projectTarget.id : null,
    };

    if (projectTarget) {
      saveProjectConfig(projectTarget.id, {
        connectionMode: connectionMode as "http" | "socketio" | "swagger" | "browser",
        http: connectionMode === "http" ? connection : undefined,
        socketio: connectionMode === "socketio" ? socketioConnection : undefined,
        swagger: connectionMode === "swagger" ? swaggerConnection : undefined,
        browser: connectionMode === "browser" ? browserConnection : undefined,
        maxRounds,
        capabilityOverride: capabilityOverride.trim() || undefined,
        categories: selectedCategories,
        startDifficulty,
        maxDifficulty,
        passThreshold,
        userDescription: userDescription.trim() || undefined,
      });
    }

    onStart(request);
  }

  // "Describe your chatbot": the one optional description field, shared by every
  // connection type. In HTTP / REST mode it sits between the chat endpoint URL and
  // the login toggle; in the other modes it follows that mode's own fields (see
  // the two places it is rendered below). It is also what the report shows as the
  // agent's Description.
  const describeChatbotField = (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      <p className={`${SECTION_LABEL} em-sec--ctx mb-3`}>Agent context</p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">💬</span>
          <span className="text-sm font-medium text-slate-200">Describe your chatbot</span>
          <span className="rounded-full bg-slate-700/60 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-400">Optional</span>
        </div>
        <button
          type="button"
          onClick={() => setShowUserDescription((v) => !v)}
          className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
            showUserDescription
              ? "border-cyan-500 bg-cyan-600/20 text-cyan-200"
              : "border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700"
          }`}
        >
          {showUserDescription ? "Hide" : "Enable"}
        </button>
      </div>
      {!showUserDescription && (
        <p className="mt-2 text-xs text-slate-500">
          Tell EvalMind what your chatbot does. It will also ask the chatbot itself
          and compare both answers — generating smarter evaluation questions.
        </p>
      )}
      {showUserDescription && (
        <div className="mt-3 flex flex-col gap-2">
          <textarea
            id="user_capability_description"
            rows={4}
            maxLength={DESCRIPTION_MAX}
            placeholder="e.g. A customer-support chatbot for a logistics company that helps users track shipments, answer delivery questions, and raise support tickets."
            value={userDescription}
            onChange={(e) => setUserDescription(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
          {userDescription.length > DESCRIPTION_MAX - 200 && (
            <p className="text-right font-mono text-[11px] text-slate-500">
              {userDescription.length}/{DESCRIPTION_MAX}
            </p>
          )}
          <div className="rounded-md border border-cyan-900/40 bg-cyan-950/20 px-3 py-2">
            <p className="text-xs text-cyan-400">
              <strong>How it works:</strong> EvalMind will ask your chatbot “What can you do?”
              and compare its answer with your description. If they differ significantly,
              you’ll see a warning before evaluation starts. Both descriptions are combined
              to generate more targeted test questions.
            </p>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="em-landing flex w-full flex-col gap-8">
      <form onSubmit={handleSubmit} className="flex w-full flex-col gap-6">
        {!hideHeader && (
          <header className="border-b border-slate-800 pb-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-indigo-400">
              EvalMind — AI Evaluation Workspace
            </p>
            <h1 className="mt-2 text-3xl font-semibold uppercase tracking-tight text-slate-50 sm:text-4xl">
              New Evaluation
            </h1>
            <p className="mt-2 text-base text-slate-400">Configure an AI agent and start an evaluation.</p>
          </header>
        )}

        {/* Dashboard grid: connection setup (left, grows with content) next
         * to a sticky settings/summary sidebar (right). Sticky is what keeps
         * the sidebar from stranding a big empty gap under it when the left
         * column gets much taller than it — login fields expanding, the
         * chatbot description opening, or switching to Browser mode's long
         * selector list all used to do exactly that. */}
        <div className="grid grid-cols-1 gap-6 lg:items-stretch lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
        <div className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
          <span className={`${SECTION_LABEL} em-sec--conn`}>Connection type</span>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 [&>button]:py-3 [&>button]:text-center">
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

        <div className="flex flex-1 flex-col gap-6 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
          <span className={`${SECTION_LABEL} ${connectionMode === "browser" ? "em-sec--browser" : "em-sec--cfg"}`}>
            {connectionMode === "browser" ? "Browser automation" : "Connection configuration"}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-800/60 px-2.5 py-0.5 font-mono text-[11px] text-slate-300">
            {connectionMode === "http"
              ? "HTTP / REST"
              : connectionMode === "socketio"
                ? "Socket.IO (JWT)"
                : connectionMode === "swagger"
                  ? "Swagger / OpenAPI"
                  : "Browser (Playwright)"}
          </span>
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

            {describeChatbotField}

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

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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

        {connectionMode !== "http" && describeChatbotField}
        </div>
        </div>

        {/* ── Right sidebar: evaluation dials + a live setup summary. Sticky
             at lg (this form's container caps out around 1152px, so xl
             rarely fires here) so it tracks alongside the left column on
             scroll instead of stranding empty space when that column grows
             taller ─────────────────────────────────────────────────── */}
        <aside className="flex min-w-0 flex-col gap-6">
        <div className="flex flex-col gap-5 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
          <div className="border-b border-slate-800 pb-3">
            <span className={`${SECTION_LABEL} em-sec--set`}>Evaluation settings</span>
          </div>

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
              className="w-24 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-slate-200">Categories to evaluate</span>
            <div className="flex flex-wrap gap-2">
              {ALL_CATEGORIES.map((cat) => {
                const theme = themeFor(cat);
                const on = selectedCategories.includes(cat);
                return (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => toggleCategory(cat)}
                    aria-pressed={on}
                    className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                      on
                        ? `${theme.border} ${theme.soft} ${theme.text}`
                        : "border-slate-700 bg-slate-900 text-slate-500 hover:bg-slate-800"
                    }`}
                  >
                    <span aria-hidden>{theme.icon}</span>
                    {cat}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-slate-500">Tap to include or skip a category for this run.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-2">
              <label htmlFor="start_difficulty" className="text-sm font-medium text-slate-200">
                Start difficulty
              </label>
              <input
                id="start_difficulty"
                type="number" min={1} max={5}
                value={startDifficulty}
                onChange={(e) => setStartDifficulty(Number(e.target.value))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="max_difficulty" className="text-sm font-medium text-slate-200">
                Max difficulty
              </label>
              <input
                id="max_difficulty"
                type="number" min={1} max={5}
                value={maxDifficulty}
                onChange={(e) => setMaxDifficulty(Number(e.target.value))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>
          <p className="-mt-3 text-xs text-slate-500">1–5 each. Raise start difficulty to skip easy rounds.</p>

          <div className="flex flex-col gap-2">
            <label htmlFor="pass_threshold" className="text-sm font-medium text-slate-200">
              Pass threshold <span className="text-slate-500">(1–10)</span>
            </label>
            <input
              id="pass_threshold"
              type="number" min={1} max={10}
              value={passThreshold}
              onChange={(e) => setPassThreshold(Number(e.target.value))}
              className="w-24 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="text-xs text-slate-500">Minimum primary-metric score for a round to count as PASS.</p>
          </div>

          <div className="border-t border-slate-800 pt-3">
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24" className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`}>
                <path d="M19 9l-7 7-7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {showAdvanced ? "Hide advanced options" : "Show advanced options"}
            </button>
          </div>

          {showAdvanced && (
            <div className="flex flex-col gap-4 rounded-lg border border-slate-700/60 bg-slate-900/30 p-4">
              {connectionMode === "http" && (
                <>
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
                      className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                  </div>
                </>
              )}

              <div className="flex flex-col gap-2">
                <label htmlFor="capability_override" className="text-sm font-medium text-slate-200">
                  Capability override <span className="text-slate-500">(optional)</span>
                </label>
                <textarea
                  id="capability_override"
                  rows={3}
                  placeholder="Leave blank to auto-discover."
                  value={capabilityOverride}
                  onChange={(e) => setCapabilityOverride(e.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            </div>
          )}
        </div>

        {/* Live setup summary — everything chosen above, at a glance. Also
             gives the sidebar substantial, steady content so it never reads
             as a half-empty column next to the connection card. */}
        <div className="flex flex-1 flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
          <div className="border-b border-slate-800 pb-3">
            <span className={`${SECTION_LABEL} em-sec--summary`}>Setup summary</span>
          </div>

          <div className="flex flex-col gap-2.5 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-400">Connection</span>
              <span className={`font-medium ${MODE_ACCENT[connectionMode]}`}>{MODE_LABEL[connectionMode]}</span>
            </div>
            <div className="flex items-start justify-between gap-3">
              <span className="shrink-0 text-slate-400">Endpoint</span>
              <span className="truncate text-right text-slate-200" title={currentEndpoint || undefined}>
                {currentEndpoint || <span className="text-slate-500">Not set yet</span>}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-400">Auth</span>
              <span className="text-right text-slate-200">{currentAuthLabel}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-400">Chatbot description</span>
              <span className={userDescription.trim() ? "font-medium text-cyan-300" : "text-slate-500"}>
                {userDescription.trim() ? "Added" : "Not set (optional)"}
              </span>
            </div>
          </div>

          <div className="h-px bg-slate-800" />

          <div className="flex flex-wrap gap-1.5">
            {ALL_CATEGORIES.map((cat) => {
              const theme = themeFor(cat);
              const on = selectedCategories.includes(cat);
              return (
                <span
                  key={cat}
                  className={`rounded-full border px-2.5 py-1 text-[11px] font-medium capitalize ${
                    on
                      ? `${theme.border} ${theme.soft} ${theme.text}`
                      : "border-slate-800 bg-slate-900/60 text-slate-600 line-through decoration-slate-700"
                  }`}
                >
                  {theme.icon} {cat}
                </span>
              );
            })}
          </div>

          <ul className="flex flex-col gap-1.5 text-xs">
            {([
              ["Endpoint set", !!currentEndpoint],
              ["Categories selected", selectedCategories.length > 0],
              ["Difficulty range valid", startDifficulty <= maxDifficulty],
            ] as [string, boolean][]).map(([label, ok]) => (
              <li key={label} className="flex items-center gap-2">
                <span className={ok ? "text-emerald-400" : "text-slate-600"}>{ok ? "●" : "○"}</span>
                <span className={ok ? "text-slate-200" : "text-slate-500"}>{label}</span>
              </li>
            ))}
          </ul>

          <div className="mt-auto grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2.5">
              <p className="text-lg font-semibold text-slate-100">{maxRounds}</p>
              <p className="text-[10px] uppercase tracking-wide text-slate-500">Rounds</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2.5">
              <p className="text-lg font-semibold text-slate-100">{startDifficulty}–{maxDifficulty}</p>
              <p className="text-[10px] uppercase tracking-wide text-slate-500">Difficulty</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2.5">
              <p className="text-lg font-semibold text-slate-100">{passThreshold}/10</p>
              <p className="text-[10px] uppercase tracking-wide text-slate-500">Pass bar</p>
            </div>
          </div>

          {projectTarget && (
            <div className="flex items-center justify-between rounded-md border border-emerald-900/60 bg-emerald-950/20 px-3 py-2 text-xs">
              <span className="text-slate-400">Project</span>
              <span className="font-medium text-emerald-300">{projectTarget.name}</span>
            </div>
          )}
        </div>
        </aside>
        {/* end dashboard grid */}
        </div>

        {formError && (
          <div className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {formError}
          </div>
        )}

        <button
          type="submit"
          disabled={disabled}
          className="em-cta rounded-xl bg-indigo-600 px-6 py-4 text-base font-semibold tracking-wide text-white shadow-lg shadow-indigo-950/50 transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 disabled:shadow-none"
        >
          {disabled ? "Starting…" : "Start Evaluation"}
        </button>

        {projectTarget && (
          <p className="-mt-3 text-xs text-slate-500">
            Will be saved to project <span className="text-slate-300">{projectTarget.name}</span>.
          </p>
        )}
      </form>

      {/* Past sessions only shown in standalone mode (no sidebar/project workspace) */}
      {!hideHeader && (
        <div className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
          <h2 className={`${SECTION_LABEL} em-sec--hist`}>Past Sessions in this Project</h2>
          <SessionHistoryPanel onViewReport={onLoadReport} onChanged={bumpLists} refreshKey={listRefresh} projectId={projectTarget?.id} />
        </div>
      )}
    </div>
  );
}

/** Shared eyebrow style for the dashboard section headings (presentation only). */
const SECTION_LABEL = "em-sec font-mono text-[11px] uppercase tracking-[0.2em] text-slate-400";

/** Display label + accent colour per connection mode, used by the "Setup
 * summary" sidebar card. */
const MODE_LABEL: Record<"http" | "socketio" | "swagger" | "browser", string> = {
  http: "HTTP / REST",
  socketio: "Socket.IO (JWT)",
  swagger: "Swagger / OpenAPI",
  browser: "Browser (Playwright)",
};
const MODE_ACCENT: Record<"http" | "socketio" | "swagger" | "browser", string> = {
  http: "text-indigo-300",
  socketio: "text-indigo-300",
  swagger: "text-violet-300",
  browser: "text-emerald-300",
};

/** Mirrors the backend's max_length on SessionStartRequest.agent_brief. */
const DESCRIPTION_MAX = 2000;

function defaultSocketioConnectionRequest_safe(): SocketIOConnectionRequest {
  return defaultSocketIOConnectionRequest();
}
