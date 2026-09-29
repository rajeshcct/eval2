/**
 * src/lib/projectConfig.ts
 *
 * "Continue with an existing project" pre-fills the New Evaluation form with
 * whatever the project's last session used: connection type (HTTP / Socket.IO /
 * Swagger / Playwright), every field of that connection, the evaluation
 * settings and the chatbot description.
 *
 * Two sources, in order:
 *   1. The full form snapshot saved in this browser when the last evaluation of
 *      the project was started (localStorage, one entry per project id).
 *   2. Fallback for projects whose sessions predate this feature: the
 *      secret-free `session_meta` the backend already stores with each session
 *      (connection type, endpoint, rounds, categories, difficulty, threshold).
 *
 * Secrets (passwords, bearer / JWT tokens) are NOT saved by default — the backend
 * deliberately never stores them either. Flip PERSIST_SECRETS to true if you want
 * them remembered in this browser too.
 */
import { fetchSessionReport, fetchSessions } from "./ws";
import type {
  AUTConnectionRequest,
  BrowserConnectionRequest,
  SocketIOConnectionRequest,
  SwaggerConnectionRequest,
} from "./types";

export const PERSIST_SECRETS = false;

export type ConnectionMode = "http" | "socketio" | "swagger" | "browser";

export interface SavedFormConfig {
  connectionMode?: ConnectionMode;
  http?: Partial<AUTConnectionRequest>;
  socketio?: Partial<SocketIOConnectionRequest>;
  swagger?: Partial<SwaggerConnectionRequest>;
  browser?: Partial<BrowserConnectionRequest>;
  maxRounds?: number;
  capabilityOverride?: string;
  categories?: string[];
  startDifficulty?: number;
  maxDifficulty?: number;
  passThreshold?: number;
  userDescription?: string;
}

const storageKey = (projectId: string) => `evalmind.lastConfig.v1:${projectId}`;

function withoutSecrets(cfg: SavedFormConfig): SavedFormConfig {
  if (PERSIST_SECRETS) return cfg;
  return {
    ...cfg,
    http: cfg.http && { ...cfg.http, password: null },
    socketio: cfg.socketio && { ...cfg.socketio, bearer_token: "" },
    swagger: cfg.swagger && { ...cfg.swagger, bearer_token: null },
    browser: cfg.browser && { ...cfg.browser, password: null },
  };
}

/** Remember the settings a project's evaluation was just started with. */
export function saveProjectConfig(projectId: string, cfg: SavedFormConfig): void {
  try {
    window.localStorage.setItem(storageKey(projectId), JSON.stringify(withoutSecrets(cfg)));
  } catch {
    // Storage full / blocked (private mode): pre-fill is a convenience, never fatal.
  }
}

function loadSavedProjectConfig(projectId: string): SavedFormConfig | null {
  try {
    const raw = window.localStorage.getItem(storageKey(projectId));
    return raw ? (JSON.parse(raw) as SavedFormConfig) : null;
  } catch {
    return null;
  }
}

// Human-readable labels the backend writes into session_meta.connection_mode
// (backend/app/main.py::_MODE_LABELS) mapped back to the form's modes.
const MODE_BY_LABEL: Record<string, ConnectionMode> = {
  "HTTP / REST": "http",
  "Socket.IO (JWT)": "socketio",
  "Swagger / OpenAPI": "swagger",
  "Browser (Playwright)": "browser",
};

/** Best-effort settings taken from the project's most recent completed session. */
async function configFromHistory(projectId: string): Promise<SavedFormConfig | null> {
  const sessions = await fetchSessions(50, projectId); // this project's sessions, newest first
  const latest = sessions.find((s) => s.has_report);
  if (!latest) return null;

  const report = await fetchSessionReport(latest.id);
  const meta = report.session_meta;
  if (!meta) return null;

  const cfg: SavedFormConfig = {};
  const mode = meta.connection_mode ? MODE_BY_LABEL[meta.connection_mode] : undefined;
  if (mode) {
    cfg.connectionMode = mode;
    if (meta.endpoint) {
      if (mode === "http") cfg.http = { chat_endpoint_url: meta.endpoint };
      else if (mode === "socketio") cfg.socketio = { chat_endpoint_url: meta.endpoint };
      else if (mode === "swagger") cfg.swagger = { chat_endpoint_url: meta.endpoint };
      else cfg.browser = { chatbot_url: meta.endpoint };
    }
  }
  if (typeof meta.max_rounds === "number") cfg.maxRounds = meta.max_rounds;
  if (Array.isArray(meta.categories_requested) && meta.categories_requested.length > 0) {
    cfg.categories = meta.categories_requested;
  }
  if (typeof meta.start_difficulty === "number") cfg.startDifficulty = meta.start_difficulty;
  if (typeof meta.max_difficulty === "number") cfg.maxDifficulty = meta.max_difficulty;
  if (typeof meta.pass_threshold === "number") cfg.passThreshold = meta.pass_threshold;
  if (report.agent_brief) cfg.userDescription = report.agent_brief;

  return Object.keys(cfg).length > 0 ? cfg : null;
}

/** What to pre-fill the form with when a project is opened (null = start blank). */
export async function resolveProjectConfig(projectId: string): Promise<SavedFormConfig | null> {
  const saved = loadSavedProjectConfig(projectId);
  if (saved) return saved;
  try {
    return await configFromHistory(projectId);
  } catch {
    return null;
  }
}
