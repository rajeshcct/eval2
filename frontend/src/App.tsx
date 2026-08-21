import { useCallback, useEffect, useRef, useState } from "react";
import NewSessionForm from "./components/NewSessionForm";
import LiveRunView from "./components/LiveRunView";
import ReportView from "./components/ReportView";
import { fetchSessionReport, startRun } from "./lib/ws";
import type { FinalReport, ProgressEvent } from "./lib/ws";
import type { SessionStartRequest } from "./lib/types";

/**
 * App shell with three states (form -> live -> report), held in React
 * state. Phase III built the form + WS client (with every event logged to
 * the console). Phase IV replaced the "live" placeholder with the real
 * round-by-round LiveRunView. Phase V replaces the "report" placeholder
 * with the real ReportView, and adds the independent reload path: a
 * `?session_id=...` query param (read once on mount, and written back
 * whenever a report is on screen) lets a finished report be reopened later
 * via nothing but its URL — fetched straight from GET
 * /api/sessions/{id}/report, no WebSocket or live run involved.
 */
type AppState = "form" | "live" | "report";
/** Only meaningful while state === "report". "loaded" covers both a report
 * that just arrived via a live run's session_completed payload AND one
 * that finished fetching via the reload path — ReportView itself doesn't
 * distinguish the two. "loading"/"error" cover the reload path while the
 * GET /api/sessions/{id}/report call is in flight or fails (e.g. an
 * unknown/mistyped session_id). */
type ReportStatus = "loading" | "loaded" | "error";

const SESSION_ID_PARAM = "session_id";

function readSessionIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get(SESSION_ID_PARAM);
}

/** Writes/clears `?session_id=...` without a navigation or reload, so the
 * address bar always reflects a reloadable link to whatever report is
 * currently on screen (Phase V requirements 2 and 3). */
function setSessionIdInUrl(sessionId: string | null) {
  const url = new URL(window.location.href);
  if (sessionId) {
    url.searchParams.set(SESSION_ID_PARAM, sessionId);
  } else {
    url.searchParams.delete(SESSION_ID_PARAM);
  }
  window.history.replaceState(null, "", url.toString());
}

export default function App() {
  const [state, setState] = useState<AppState>("form");
  const [starting, setStarting] = useState(false);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [finalReport, setFinalReport] = useState<FinalReport | null>(null);
  const [reportStatus, setReportStatus] = useState<ReportStatus>("loaded");
  const [reportError, setReportError] = useState<string | null>(null);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  // Raw WS-level failure (e.g. connection refused) — distinct from a
  // well-formed `error` ProgressEvent, which LiveRunView renders itself by
  // deriving from `events`.
  const [socketError, setSocketError] = useState<string | null>(null);
  // Phase VI: true when the WS closed unexpectedly mid-run — i.e. AFTER it
  // connected, but BEFORE a terminal session_completed/error event arrived.
  // Distinct from socketError (which covers a connection that never opened
  // at all) so the UI can offer a specific, actionable "Retry" affordance.
  const [disconnected, setDisconnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  // Bookkeeping refs read inside WS event-handler closures (so they must
  // always reflect the latest value, hence refs rather than state) to
  // classify a close event correctly in handleStart's onClose below:
  // - lastRequestRef: the request to reuse if the person clicks "Retry".
  // - hasOpenedRef: did this socket ever successfully open?
  // - intentionalCloseRef: did WE close it (Cancel / Start another), as
  //   opposed to the network or the server closing it on us?
  // - terminalEventReceivedRef: did a well-formed session_completed/error
  //   ProgressEvent already arrive? (the server closes right after either,
  //   deliberately — that's a clean close, not a drop.)
  const lastRequestRef = useRef<SessionStartRequest | null>(null);
  const hasOpenedRef = useRef(false);
  const intentionalCloseRef = useRef(false);
  const terminalEventReceivedRef = useRef(false);

  // Phase V's reload path: fetch a finished report by session_id alone,
  // independent of any live run. Used both by the `?session_id=...` URL
  // check on mount below and by NewSessionForm's "View report" affordance.
  const loadReportById = useCallback(async (sessionId: string) => {
    setState("report");
    setReportStatus("loading");
    setReportError(null);
    setPendingSessionId(sessionId);
    setSessionIdInUrl(sessionId);

    try {
      const report = await fetchSessionReport(sessionId);
      setFinalReport(report);
      setReportStatus("loaded");
    } catch (e) {
      setReportStatus("error");
      setReportError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // On first load, a `?session_id=...` in the URL means someone opened a
  // link to a previously-finished report rather than landing on the form
  // — go straight to fetching it, proving the report is reachable via
  // nothing but the URL.
  useEffect(() => {
    const existing = readSessionIdFromUrl();
    if (existing) {
      loadReportById(existing);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEvent = useCallback((event: ProgressEvent) => {
    // Phase III checkpoint: every incoming event lands in the console,
    // raw, in the order it arrived. Kept even now that LiveRunView renders
    // events properly — still the fastest way to inspect the raw feed.
    // eslint-disable-next-line no-console
    console.log("[ws:/ws/run]", event.type, event.data);

    if (event.type === "session_completed" || event.type === "error") {
      // A well-formed terminal event — the server is about to close the
      // socket deliberately (see backend/app/main.py). Marks this as an
      // expected, clean close so onClose (in handleStart) doesn't also
      // report it as a dropped connection.
      terminalEventReceivedRef.current = true;
    }

    setEvents((prev) => [...prev, event]);

    if (event.type === "session_completed") {
      // The just-finished run's FinalReport arrives here already, in
      // full — no extra fetch needed to show it (Phase IV requirement 5).
      // Writing it into the URL is what makes this same report reachable
      // again later purely via link/reload (Phase V requirement 2).
      setFinalReport(event.data);
      setReportStatus("loaded");
      setSessionIdInUrl(event.data.session_id);
      setState("report");
    }
  }, []);

  function handleStart(request: SessionStartRequest) {
    setSocketError(null);
    setDisconnected(false);
    setEvents([]);
    setFinalReport(null);
    setReportStatus("loaded");
    setReportError(null);
    setPendingSessionId(null);
    setStarting(true);

    lastRequestRef.current = request;
    hasOpenedRef.current = false;
    intentionalCloseRef.current = false;
    terminalEventReceivedRef.current = false;

    const socket = startRun(request, {
      onEvent: handleEvent,
      onOpen: () => {
        hasOpenedRef.current = true;
        setStarting(false);
        setState("live");
      },
      onSocketError: () => {
        setStarting(false);
        // Only surface the "can't reach the backend" message for a failure
        // BEFORE the socket ever opened. A mid-run drop is instead handled
        // by onClose below (a retryable "connection lost" banner) once the
        // browser's matching close event fires — showing both here would
        // be redundant and less actionable.
        if (!hasOpenedRef.current) {
          setSocketError("Could not reach the backend — is it running at the configured URL?");
        }
      },
      onClose: () => {
        socketRef.current = null;
        if (hasOpenedRef.current && !intentionalCloseRef.current && !terminalEventReceivedRef.current) {
          // It opened, we didn't close it, and no session_completed/error
          // ever arrived — the connection dropped mid-run.
          setDisconnected(true);
        }
      },
    });
    socketRef.current = socket;
  }

  /** Phase VI: retry after a mid-run disconnect. There is no resume/reconnect
   * endpoint on the backend (an orphaned run keeps executing server-side and
   * persists its report normally, but nobody is left to stream events to —
   * see backend/app/main.py's WebSocketDisconnect handling), so "retry"
   * means starting a brand-new run with the same connection settings, not
   * resuming the dropped one. */
  function handleRetry() {
    if (lastRequestRef.current) {
      handleStart(lastRequestRef.current);
    }
  }

  function handleReset() {
    intentionalCloseRef.current = true;
    socketRef.current?.close();
    socketRef.current = null;
    setState("form");
    setEvents([]);
    setFinalReport(null);
    setSocketError(null);
    setDisconnected(false);
    setReportStatus("loaded");
    setReportError(null);
    setPendingSessionId(null);
    setSessionIdInUrl(null);
  }

  return (
    <div className="min-h-screen px-4 py-12">
      {state === "form" && (
        <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
          {socketError && (
            <div
              role="alert"
              className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300"
            >
              {socketError}
            </div>
          )}
          <NewSessionForm onStart={handleStart} onLoadReport={loadReportById} disabled={starting} />
        </div>
      )}

      {state === "live" && (
        <LiveRunView
          events={events}
          socketError={socketError}
          disconnected={disconnected}
          onRetry={handleRetry}
          onCancel={handleReset}
        />
      )}

      {state === "report" && reportStatus === "loading" && (
        <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3 py-16 text-center">
          <div
            className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400"
            aria-hidden
          />
          <p className="text-sm text-slate-400">
            Loading report{pendingSessionId ? ` for session ${pendingSessionId}` : ""}…
          </p>
        </div>
      )}

      {state === "report" && reportStatus === "error" && (
        <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
          <div
            role="alert"
            className="rounded-md border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300"
          >
            Could not load report{pendingSessionId ? ` for session_id "${pendingSessionId}"` : ""}.
            {reportError ? ` ${reportError}` : ""}
          </div>
          <button
            onClick={handleReset}
            className="self-start rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
          >
            Back to start
          </button>
        </div>
      )}

      {state === "report" && reportStatus === "loaded" && finalReport && (
        <ReportView report={finalReport} onReset={handleReset} />
      )}
    </div>
  );
}
