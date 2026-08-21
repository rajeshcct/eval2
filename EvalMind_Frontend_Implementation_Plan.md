# EvalMind — Frontend & Live-Run API — Phase-wise Implementation Plan

Continuation of `EvalMind_POC_Implementation_Plan` (Blocks A–H). Blocks A–H already exist and are
fully working: `agents/` (Describer, Generator, Judge), `aut/connector.py` (4 modes), `db/`,
`pipeline.py`, `loop_runner.py`, `session.py`, `aggregator.py`, `demo/`, `scripts/`, `DEMO.md`.

This document adds a **FastAPI backend** and a **React frontend** on top of that pipeline, so a
session can be triggered from a browser, watched live round-by-round over a WebSocket, and the
final report reviewed afterward. Each phase is written to be pasted into a coding agent as its own
prompt, same as Blocks A–H were — feed them one at a time, in order.

**Ground rule for every phase below:** never modify the *behavior* of `agents/judge.py`,
`agents/generator.py`, `agents/describer.py`, or `aut/connector.py`'s four dispatch functions.
Every phase only *adds* optional, backward-compatible hooks (default `None` / off) so that
`main.py`, `scripts/rehearsal.py`, and every existing file under `tests/` keep passing unmodified.

## Schedule Overview

| Phase | Focus | Ends in |
|---|---|---|
| I | Progress events + AUT login/auth wrapper | Pipeline is observable + can reach a login-gated AUT |
| II | FastAPI backend — WebSocket + REST | A WS client can run a full session live and reload its report |
| III | Frontend foundation + New Session form | Form opens a WS connection, raw events land in console |
| IV | Live Run view | A session is watchable live, round by round, in the browser |
| V | Final Report view + reload by session_id | Finished report viewable live AND independently via URL |
| VI | Polish & demo readiness | Two-terminal local run documented, smoke-tested end to end |

---

## Phase I — Progress Events + AUT Auth Wrapper

Continuing the EvalMind POC. `session.py`'s `run_full_session()`, `loop_runner.py`'s
`run_category_loop()`, `pipeline.py`'s `run_single_round()`, and `agents/describer.py`'s
`describe_aut()` (Blocks A–H, fully working and tested) already exist.

This phase adds **no UI and no server** — it only prepares the Python side to (a) emit progress
events as a session runs, and (b) reach an AUT whose chat endpoint requires a prior login call to
obtain a bearer token.

### Requirements

1. Define a `ProgressEvent` shape (e.g. a small `TypedDict`/Pydantic model in a new
   `progress.py`): `{"type": str, "data": dict}`. Event types and their `data` payload:
   - `describer_started` — `{}`
   - `describer_completed` — `DescriberResult.model_dump()`
   - `category_started` — `{"category": str}`
   - `round_started` — `{"category": str, "round_number": int, "difficulty": int}`
   - `round_completed` — `RoundResult.model_dump()`
   - `category_completed` — `CategoryLoopResult.model_dump()`
   - `session_completed` — `FinalReport.model_dump()`
   - `error` — `{"stage": str, "message": str}`

2. Thread an **optional** `on_event: Optional[Callable[[ProgressEvent], None]] = None` parameter
   through `describe_aut()`, `run_single_round()`, `run_category_loop()`, and
   `run_full_session()`. Each function calls `on_event(...)` at the appropriate points (and passes
   `on_event` down to whatever it calls internally) if — and only if — it was given one; when it's
   `None`, behavior is byte-for-byte identical to today. Wrap every `on_event(...)` call in a
   try/except that logs and swallows — a broken UI callback must never crash a real evaluation run.

3. Build `aut/auth.py` (new file) exposing
   `build_authenticated_endpoint_config(connection: AUTConnectionRequest) -> CustomEndpointConfig`.
   Define `AUTConnectionRequest` (Pydantic) with:
   - `chat_endpoint_url: str`
   - `requires_login: bool`
   - `login_endpoint_url: Optional[str] = None`
   - `username: Optional[str] = None`
   - `password: Optional[str] = None`
   - `token_field: str = "auth_token"` (the JSON key the login response returns the token under —
     confirmed for the current AUT, but kept configurable, not hardcoded, for a different AUT later)
   - `auth_header_format: str = "Bearer {token}"` (also kept configurable)

   Behavior: if `requires_login` is `False`, return `CustomEndpointConfig(url=chat_endpoint_url,
   headers=None)` directly — no network call. If `True`, POST `{"username": ..., "password": ...}`
   to `login_endpoint_url`, extract `token_field` from the JSON response, and return
   `CustomEndpointConfig(url=chat_endpoint_url, headers={"Authorization":
   auth_header_format.format(token=token)})`. Raise a clear, specific `AUTAuthError` (new exception
   class) if the login call fails, returns a non-2xx, isn't valid JSON, or is missing
   `token_field` — never fail silently or return a config with a `None`/empty token.

4. Write `tests/test_progress_events.py`: run `run_single_round()` (manual mode) with an `on_event`
   that appends every event to a list; assert the expected event types fired in order. Write
   `tests/test_auth_wrapper.py`: spin up the same kind of tiny local Flask/FastAPI test server used
   in Block C's `tests/dummy_endpoint.py`, add a `/login` route that checks a hardcoded
   username/password and returns `{"auth_token": "..."}`, and confirm
   `build_authenticated_endpoint_config()` produces a `CustomEndpointConfig` whose `headers`
   contain the exact right `Authorization` value; also test the `requires_login=False` path and the
   missing-field error path.

Do not build any FastAPI routes or WebSocket code yet — that's Phase II. This phase's only job is
making the pipeline observable and able to reach a login-gated AUT.

★ **Phase I checkpoint:** `tests/test_progress_events.py` and `tests/test_auth_wrapper.py` both
pass, and every pre-existing test file still passes unmodified.

---

## Phase II — FastAPI Backend: WebSocket + REST

Continuing the EvalMind POC. Phase I's `on_event` plumbing (`progress.py`) and `aut/auth.py`
already exist and are tested.

Now build `backend/` — a thin FastAPI service that is the *only* thing the frontend ever talks to.
It never re-implements pipeline logic; it only wires HTTP/WebSocket around the functions that
already exist.

### Requirements

1. `backend/app/main.py` — FastAPI app with CORS enabled for the local Vite dev server origin.

2. `WS /ws/run` — the live-run endpoint:
   - On connect, wait for one JSON message from the client: a `SessionStartRequest` containing
     `AUTConnectionRequest` (Phase I) plus `max_rounds: int` and an optional
     `capability_description_override: Optional[str]`.
   - Build the `AUTConfig` via `aut.auth.build_authenticated_endpoint_config()`.
   - Run `run_full_session(aut_config=..., max_rounds=..., capability_description_override=...,
     on_event=<forward each event over the WS as JSON>)` in a background thread (e.g.
     `asyncio.to_thread`) — `run_full_session()` is synchronous and makes real blocking network/LLM
     calls, so it must never run directly on the event loop, or the WebSocket stops servicing
     messages while it runs.
   - Forward every `ProgressEvent` to the client as `{"type": ..., "data": ...}` the moment it
     fires (use an `asyncio.Queue` bridged from the worker thread via
     `loop.call_soon_threadsafe`).
   - On any exception from `run_full_session()`, send one `error` event with a clear message, then
     close the socket cleanly — never leave it hanging.
   - On success, `session_completed`'s `data` is the full `FinalReport`; close the socket after
     sending it.

3. `GET /api/sessions/{session_id}/report` — returns the persisted `FinalReport` via
   `db.store.get_final_report()` / `aggregator.build_final_report()` reload path (already built in
   Block G) — 404 if not found. This is what lets a finished report be reloaded without re-running
   anything, from just its `session_id`.

4. `GET /api/health` — wraps `config.llm_config.is_configured()`.

5. `backend/requirements.txt` — `fastapi`, `uvicorn[standard]` (installs `websockets` too); backend
   imports the project root's existing modules directly (run uvicorn from the project root, or add
   the root to `PYTHONPATH` — document whichever you choose in a short `backend/README.md`).

6. Write `backend/tests/test_ws_flow.py` using **manual mode** AUT config + `capability_description_
   override` (skips the Describer and all real network calls, per the sample JSON from Block E/G) to
   assert: connecting, sending a start message, and reading messages until close yields the expected
   event sequence ending in `session_completed`; then `GET /api/sessions/{id}/report` returns a
   matching report afterward.

Do not build the React frontend yet.

★ **Phase II checkpoint:** a WebSocket client (a Python test, or a tool like `wscat`) can trigger a
full mocked (manual-mode) session end-to-end, see every event live, and reload the finished report
via REST.

---

## Phase III — Frontend Foundation + New Session Form

Continuing the EvalMind POC. `backend/` (WS + REST, tested against manual mode) already exists.

Now scaffold `frontend/` — React + TypeScript + Vite + Tailwind.

### Requirements

1. Init the project (Vite's `react-ts` template) with Tailwind configured.

2. A typed WS client (`src/lib/ws.ts`) mirroring Phase I's `ProgressEvent` union type exactly
   (same `type` string literals and `data` shapes), plus a typed `SessionStartRequest`
   (`src/lib/types.ts`) mirroring Phase II's request schema.

3. **New Session form** (the app's landing page): `chat_endpoint_url` field; a "requires login?"
   toggle that conditionally reveals `login_endpoint_url` / `username` / `password` fields; a
   `max_rounds` number input (default 5); a "Start Evaluation" button that opens the `/ws/run`
   connection and immediately sends the `SessionStartRequest`.

4. Basic app shell with three states (`form` → `live` → `report`) held in React state — no backend
   session-history browsing needed yet (out of scope per the current plan).

5. `.env`/Vite config for the backend base URL (`ws://localhost:8000`, `http://localhost:8000`),
   documented in `frontend/README.md`.

Do not build the live progress visualization yet — for this phase it's enough that submitting the
form opens a working WS connection and every incoming event is logged to the browser console.

★ **Phase III checkpoint:** submitting the form against the real backend (manual mode) streams raw
events into the console in the right order.

---

## Phase IV — Live Run View

Continuing the EvalMind POC. Phase III's form + WS client (events logging to console) already work.

### Requirements

1. **Describer section** — renders once `describer_completed` arrives: self-reported summary,
   observed summary, and mismatch notes (or "(none found)"). Skipped entirely if
   `capability_description_override` was used (no `describer_*` events will fire in that case).

2. **Per-category live cards** for functionality / security / compliance — each starts on
   `category_started`, appends a row per `round_completed` for that category (round number,
   difficulty, the three primary scores + pass/fail badge; secondary scores available on
   expand/hover, not the headline), and locks in its final status + breaking point on
   `category_completed`.

3. An overall progress indicator (e.g. which of the 3 categories are done / running / pending).

4. On an `error` event: show an inline, non-crashing error banner with the message and stage.

5. On `session_completed`: transition automatically to the Report view (Phase V), passing along the
   `FinalReport` payload already received (no extra fetch needed for the just-finished run).

★ **Phase IV checkpoint:** a full manual-mode run is watchable live end-to-end with clear,
round-by-round feedback and no page refresh.

---

## Phase V — Final Report View + Reload by session_id

Continuing the EvalMind POC. Phase IV's live view (ending in a received `FinalReport`) already
works.

### Requirements

1. **Report view**: `overall_verdict` as the headline; per category — status, breaking point (or
   "robust"), `breaking_point_summary`, and the full `round_history` table (scores + pass/fail per
   round); a `performance_and_cost` section (totals + averages, with the missing-data counts shown
   when tokens/cost are partially `None`, per Block G's spec).

2. **Reload path**: the report view also accepts a bare `session_id` (e.g. via a URL param /
   route) and, when reached that way (not right after a live run), calls `GET
   /api/sessions/{id}/report` directly instead of expecting a WS-delivered payload — proving the
   Aggregator's "reconstruct from session_id alone" property (Block G) holds all the way through
   the frontend too.

3. Show the `session_id` on the report view with a copy-to-clipboard control, so a finished report
   can be revisited later without re-running anything.

★ **Phase V checkpoint:** a finished report is viewable both immediately after a live run AND
independently, later, via nothing but its `session_id`/URL.

---

## Phase VI — Polish & Demo Readiness

Continuing the EvalMind POC. Phases I–V (backend + full frontend flow) already exist and work.

This is the buffer phase — same role as Block H. No new pipeline or agent logic here.

### Requirements

1. Loading/connecting states; a clear WS-disconnect/retry message if the connection drops
   mid-run; the "Start Evaluation" button disabled while a run is in progress.

2. A basic visual pass on score badges / pass-fail states / category cards — legibility and
   clear pass/fail contrast matter more than decoration for a live demo audience.

3. Update `DEMO.md` (or add a short `FRONTEND.md`) with exact local run instructions: two
   terminals — `uvicorn backend.app.main:app --reload` from the project root, and `npm run dev`
   inside `frontend/` — plus how the "requires login" toggle maps to the AUT credentials
   discovered earlier in this process.

4. One manual, documented end-to-end smoke test: start a manual-mode session from the UI, watch
   it live, then reload the same report from its `session_id` alone. Treat this as the final
   verification step, the same way Block H's `scripts/preflight_check.py` was the final gate
   before the original demo.

No test file with assertions is required for this phase — like Block H, the deliverable is a
working, rehearsed system, not new automated coverage.
