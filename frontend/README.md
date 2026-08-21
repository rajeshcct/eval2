# EvalMind Frontend (Phase VI)

React + TypeScript + Vite + Tailwind. Talks to `backend/` (Phase II) over a
WebSocket (`/ws/run`, the live-run endpoint) and plain REST (`/api/...`) —
never touches the Python pipeline directly.

## Install

From **this** directory (`frontend/`):

```
npm install
```

## Configure

Copy the example env file and adjust if your backend isn't on the default
port:

```
cp .env.example .env
```

```
VITE_BACKEND_HTTP_URL=http://localhost:8000
VITE_BACKEND_WS_URL=ws://localhost:8000
```

These must point at the same running `backend/` instance — see
`backend/README.md` for how to start it
(`python -m uvicorn backend.app.main:app --reload --port 8000`, run from the
project root).

## Run

```
npm run dev
```

Opens at `http://localhost:5173` (pinned in `vite.config.ts` — this is
also the exact origin `backend/app/main.py`'s CORS config allows, so don't
change the port on one side without the other).

Two terminals for a full local run (see [`../FRONTEND.md`](../FRONTEND.md)
for the full write-up, including how to demo the "requires login" toggle
and a documented end-to-end smoke test):

```
# terminal 1, from the project root
python -m uvicorn backend.app.main:app --reload --port 8000

# terminal 2, from frontend/
npm run dev
```

## What's here

### Phase III — foundation + New Session form

- `src/lib/types.ts` — `AUTConnectionRequest` / `SessionStartRequest`,
  mirroring `aut/auth.py` and `backend/app/main.py`'s Pydantic models
  field-for-field.
- `src/lib/ws.ts` — the `ProgressEvent` discriminated union mirroring
  `progress.py`'s contract exactly (same `type` literals, same `data` shape
  per type, sourced from `pipeline.RoundResult` /
  `loop_runner.CategoryLoopResult` / `agents.schemas.DescriberResult` /
  `aggregator.FinalReport`), plus `startRun()` (opens `/ws/run`, sends the
  start message, forwards every message as a typed `ProgressEvent`) and
  `fetchSessionReport()` / `fetchHealth()` for the REST endpoints.
- `src/components/NewSessionForm.tsx` — the landing page: chat endpoint
  URL, a "requires login?" toggle that reveals login endpoint/username/
  password, max rounds (default 5), and an advanced section for the
  remaining `AUTConnectionRequest` fields plus an optional capability
  description override.
- `src/App.tsx` — the app shell, three states held in React state
  (`form -> live -> report`). Submitting the form opens the WS connection
  and immediately sends the `SessionStartRequest`; every incoming event is
  logged to the browser console.

### Phase IV — Live Run view

- `src/lib/liveState.ts` — a pure `deriveLiveState(events)` function that
  reduces the flat `ProgressEvent[]` list into the shape the live view
  renders (per-category status/rounds/breaking point, the Describer
  result, accumulated errors). Called via `useMemo` in `LiveRunView`
  rather than kept as an incremental reducer, since the event list stays
  small for a run this size.
- `src/components/DescriberSection.tsx` — renders once `describer_completed`
  arrives (self-reported summary, observed summary, mismatch notes);
  never renders at all on the `capability_description_override` path,
  since no `describer_*` events fire there.
- `src/components/CategoryCard.tsx` — one live card per category
  (functionality/security/compliance): starts on `category_started`,
  appends a row per `round_completed` (round number, difficulty, the three
  primary scores + pass/fail badge as the headline; secondary scores on
  click-to-expand), locks in final status + breaking point on
  `category_completed`.
- `src/components/OverallProgress.tsx` — at-a-glance status across all
  three categories.
- `src/components/ErrorBanner.tsx` — inline, non-crashing banner for
  `error` ProgressEvents.
- `src/components/LiveRunView.tsx` — composes the above from the raw
  `events` list; `session_completed` itself is handled one level up in
  `App.tsx`, which owns the transition to the Report view.

### Phase V — Final Report view + reload by session_id

- `src/components/ReportView.tsx` — the real report, replacing Phase III's
  raw-JSON placeholder: `overall_verdict` as the headline; the
  `session_id` with a copy-to-clipboard control; per category — status,
  breaking point (or "robust"), `breaking_point_summary`, and the full
  `round_history` table (primary scores + pass/fail per round as the
  headline, secondary scores/task/output/latency/tokens/cost on
  click-to-expand, same interaction pattern as Phase IV's live
  `CategoryCard`); and a `performance_and_cost` section (totals +
  averages, with `rounds_missing_token_data` / `rounds_missing_cost_data`
  surfaced explicitly whenever nonzero, per Block G's spec — never folded
  silently into the average). Renders identically no matter how the
  `FinalReport` arrived — straight off `session_completed`, or fetched
  independently.
- `src/App.tsx` — adds the reload path: a `?session_id=...` query param is
  read once on mount (no router dependency; this project stays a
  single-page state machine, so a plain `URLSearchParams` check is enough)
  and, when present, fetches the report via `GET
  /api/sessions/{id}/report` instead of expecting a WS-delivered payload.
  The same query param is written back into the address bar (via
  `history.replaceState`, no navigation) whenever a report — live-finished
  or reloaded — is on screen, so the current report's URL is always a
  valid link back to it. Loading/error states cover the reload path while
  the REST call is in flight or 404s (e.g. an unknown/mistyped
  `session_id`).
- `src/components/NewSessionForm.tsx` — a second, independent affordance
  below the form itself: a plain `session_id` input + "View report"
  button, calling the same reload path as the URL param, for reopening a
  finished report without hand-editing a URL.

## Phase III checkpoint

Submitting the form against the real backend (manual mode) streams raw
events into the console in the right order. Open the browser devtools
console, start a manual-mode session against a running `backend/`, and
confirm you see, in order: `describer_started`/`describer_completed` (unless
a `capability_description_override` was given), then per category
`category_started`, one `round_started`/`round_completed` pair per round,
`category_completed` × 3, then `session_completed`.

## Phase IV checkpoint

A full manual-mode run is watchable live end-to-end: the Describer section
(unless an override was used), all three category cards filling in round by
round with clear pass/fail scoring, the overall progress indicator, and any
`error` events surfaced inline — with no page refresh, and an automatic
transition to the Report view the moment `session_completed` arrives.

## Phase V checkpoint

A finished report is viewable both ways:

1. **Immediately after a live run** — finish a session in the UI and it
   auto-transitions from the live view into the full `ReportView` using
   the `FinalReport` payload `session_completed` already delivered.
2. **Independently, later, via nothing but its `session_id`** — copy the
   `session_id` shown on that report (or just copy the address bar's URL,
   which already has `?session_id=...` in it), open it in a fresh tab or
   paste it into the "Already ran a session?" box on the landing page, and
   confirm the exact same report loads via `GET
   /api/sessions/{id}/report` alone — no WebSocket, no re-run. Also try an
   unknown `session_id` and confirm the 404 surfaces as a clear inline
   error with a way back to the form, rather than a crash or a blank
   screen.

### Phase VI — Polish & demo readiness

No new pipeline/agent logic, and no new checkpoint of its own — this phase
tightens up what Phases III–V already built:

- **Mid-run disconnect handling** — `src/App.tsx` now distinguishes three
  WS failure shapes: (a) the socket never opens at all (shown as a red
  banner on the New Session form itself, not just logged), (b) a
  well-formed `error` `ProgressEvent` the server sent deliberately before
  closing (already handled by `ErrorBanner`, unchanged), and (c) the
  socket opening, then closing unexpectedly before any terminal event
  arrived (new — an amber "Connection to the server was lost" banner with
  a **Retry** button in `LiveRunView`, which starts a fresh run with the
  same connection settings; there is no resume/reconnect endpoint on the
  backend, so this is always a new run, not a continuation).
- **Start Evaluation stays disabled** while a run is starting or in
  progress (`disabled={starting}` on the form's submit button) — already
  in place since Phase III, confirmed still correct here.
- **Score badges / pass-fail contrast** — reviewed across `CategoryCard`,
  `ReportView`, and `OverallProgress`: consistent emerald/amber/red score
  coloring, solid-contrast PASS/FAIL badges, and a pulsing indicator for
  in-progress rounds/categories. No changes needed here beyond what
  Phases III–V already built to this standard.
- **[`../FRONTEND.md`](../FRONTEND.md)** (new) — exact two-terminal run
  instructions, how to demo the "requires login" toggle against a real
  local login server with real (test) credentials, and a documented,
  step-by-step end-to-end smoke test (start a session against the dummy
  AUT, watch it live, reload the finished report by `session_id` alone,
  and exercise the disconnect/retry path) — the same role
  `scripts/preflight_check.py` plays for the Python-only demo in
  `DEMO.md`.
