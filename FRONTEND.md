# EvalMind Frontend — Local Run & Smoke Test (Phase VI)

This file is the frontend counterpart to [DEMO.md](DEMO.md): **exact** local
run instructions for `backend/` + `frontend/` together, how the "requires
login" toggle maps onto real credentials you can actually type into the
form, and one documented end-to-end smoke test to run before trusting a
live demo. It doesn't replace `frontend/README.md` (which documents what
each phase built) or `backend/README.md` (endpoint reference) — start
there for "what is this", come here for "how do I actually run it and
prove it works."

---

## 1. Two-terminal local run

**Terminal 1 — backend, from the project root:**

```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

(Must be `python -m uvicorn`, not the bare `uvicorn` command, and must be
run from the project root — see `backend/README.md` for exactly why.)

**Terminal 2 — frontend, from `frontend/`:**

```bash
cd frontend
npm install   # first time only
npm run dev
```

Open the URL Vite prints — `http://localhost:5173` (pinned in
`vite.config.ts` to match `backend/app/main.py`'s CORS allow-list; don't
change the port on one side without the other).

Both terminals need to stay running for the whole session. The backend
needs the project root's own `.env` (an `LLM_PROVIDER` + matching
`*_API_KEY`) configured — the Describer/Generator/Judge/Aggregator calls
are always real, no matter what AUT you point the form at (see §3).

---

## 2. The "requires login" toggle → real credentials

The New Session form's "This AUT requires login" toggle exercises Phase
I's `aut/auth.py::build_authenticated_endpoint_config()` — a real login
POST, not a UI-only mock. To click through it in the browser you need a
login endpoint that actually accepts a username/password and returns a
token. The project already has one, built for
`tests/test_auth_wrapper.py`: a tiny stdlib HTTP server with a hardcoded
valid login.

Start it standalone, in its own terminal, from the project root:

```bash
python -c "
from tests.test_auth_wrapper import _start_server
server, thread = _start_server()
input('Login test server on http://127.0.0.1:8757 — press Enter to stop...')
server.shutdown()
"
```

Then fill in the form:

| Field | Value |
|---|---|
| Chat endpoint URL | `http://127.0.0.1:8756/` (see §3 — the dummy echo AUT) |
| This AUT requires login | ✅ on |
| Login endpoint URL | `http://127.0.0.1:8757/login` |
| Username | `demo_user` |
| Password | `demo_pass` |
| Token field *(Advanced)* | `auth_token` — the default, leave as-is |
| Auth header format *(Advanced)* | `Bearer {token}` — the default, leave as-is |

That's `tests/test_auth_wrapper.py`'s `VALID_USERNAME` /
`VALID_PASSWORD` / default `token_field` / default `auth_header_format`
verbatim — the same combination that script already asserts produces an
`Authorization: Bearer test-token-xyz789` header server-side. Submitting
the form with a wrong password is a quick way to see the auth failure
path too: `build_authenticated_endpoint_config()` raises `AUTAuthError`,
which `backend/app/main.py` turns into a `stage: "auth"` `error`
`ProgressEvent` — you should see `ErrorBanner` render it inline in the
Live Run view.

(The dummy echo server on port 8756 doesn't itself check the
`Authorization` header — it isn't a real login-gated AUT — so this
combination proves the *login handshake* end to end, not that a
real AUT would accept the resulting header. That part is
`build_authenticated_endpoint_config()`'s job, already covered by
`tests/test_auth_wrapper.py` in isolation.)

---

## 3. What to point the form at

The form's `chat_endpoint_url` always becomes a real `custom_endpoint`
AUT — the backend has no "manual mode" switch exposed to the browser (that
exists only inside the Python test suite, for deterministic testing
without a live AUT). Two practical options:

- **Fast/cheap/deterministic on the AUT side** — the dummy echo server
  (`tests/dummy_endpoint.py`), the same one `tests/test_connector.py` uses
  to exercise `custom_endpoint` mode:
  ```bash
  python tests/dummy_endpoint.py
  ```
  Listens at `http://127.0.0.1:8756/`, echoes back `Echo: <task>` for
  anything it's sent. Use this for the smoke test in §4 — it removes the
  AUT itself as a source of flakiness so you're only checking the
  frontend/backend/pipeline wiring. EvalMind's own Describer/Generator/
  Judge/Aggregator calls are still real LLM calls either way — there is no
  way to avoid needing an `.env` key configured, even against this dummy
  target.
- **A real target** — any of `demo/scenarios.py`'s AUTs, or your own
  endpoint. `LIVE_CUSTOMER_SUPPORT` is a `PublicAPIConfig` — as of the
  "Public API (LLM)" connection type, this IS directly form-fillable (no
  URL, no login): select it, then fill in

  | Field | Value |
  |---|---|
  | System prompt | `You are a customer support agent for an online store, you only handle orders, returns, and sizing questions.` |
  | Model | `groq/openai/gpt-oss-120b` |

  matching `demo/scenarios.py::LIVE_CUSTOMER_SUPPORT` verbatim. The
  provider's API key still comes from the backend's own `.env`
  (`GROQ_API_KEY`) — never typed into the form. Or point the form at your
  own deployed `custom_endpoint`-shaped AUT instead if you want to demo
  against a URL.

---

## 4. Documented end-to-end smoke test

Run this once before trusting the frontend for a live demo — same role as
`scripts/preflight_check.py` plays for the Python-only demo in
[DEMO.md](DEMO.md#1-before-the-demo).

**Setup:** both terminals from §1 running, a real LLM key configured in
`.env`, and `python tests/dummy_endpoint.py` running in a third terminal.

1. Open `http://localhost:5173`. You land on the New Session form, no
   `?session_id=` in the URL.
2. Fill in `chat_endpoint_url = http://127.0.0.1:8756/`, leave "requires
   login" off, leave `max_rounds` at its default. Click **Start
   Evaluation**.
   - ✅ The button immediately shows "Starting…" and disables — you can't
     double-submit.
3. The view switches to Live Run.
   - ✅ The Describer section appears, shows a loading state, then fills
     in with self-reported / observed summaries once
     `describer_completed` arrives.
   - ✅ The overall progress indicator and all three category cards
     (Functionality / Security / Compliance) update round by round —
     each round row shows difficulty, the three headline scores, and a
     PASS/FAIL badge; click a row to expand secondary scores + reasoning.
   - ✅ No `error` banner appears (the dummy AUT always responds 200, so a
     clean run here isolates frontend/backend/pipeline issues from AUT
     issues).
4. When the last category finishes, the view auto-transitions to the
   Report view with no manual action needed.
   - ✅ `overall_verdict`, all three category sections, and the
     Performance & Cost summary are populated.
   - ✅ The address bar now has `?session_id=...` appended
     (`history.replaceState`, no reload).
5. **Copy the `session_id`** shown on the report (there's a copy button
   next to it), then click **Start another session** to go back to the
   form.
6. Paste that `session_id` into the "Already ran a session? View its
   report" box on the landing page and click **View report** — or just
   open the URL you copied in step 4 in a fresh tab.
   - ✅ The exact same report loads via `GET
     /api/sessions/{id}/report` alone — no WebSocket, no re-run. This is
     the proof that a finished report survives independently of the run
     that produced it.
7. As a negative check, edit the `session_id` in the URL to something
   nonsensical and reload.
   - ✅ A clear inline "Could not load report" error appears, with a
     button back to the form — not a crash or a blank screen.

**Optional — disconnect/retry check (Phase VI):** start another run, and
partway through, stop the backend process (Ctrl+C in Terminal 1).
   - ✅ An amber "Connection to the server was lost before this run
     finished" banner appears in the Live Run view with a **Retry** button.
   - Restart the backend, click **Retry** — it starts a fresh run with the
     same connection settings (there's no resume; the dropped run's
     server-side work, if any was in flight, isn't recoverable from the
     browser).

If every checkbox above holds, the frontend is demo-ready.

---

## 5. Troubleshooting

- **Nothing happens when you click "Start Evaluation" / a red banner
  appears on the form itself** — the WebSocket never opened. Confirm
  Terminal 1 is actually running and `VITE_BACKEND_WS_URL` in
  `frontend/.env` matches its port (`ws://localhost:8000` by default).
- **"Connection to the server was lost" banner mid-run** — see the
  disconnect/retry check in §4. Most often the backend process died or
  was restarted (`--reload` picking up a file change counts) mid-run.
- **A run never finishes / stalls in the Live Run view with no error** —
  check Terminal 1's logs; a hung LLM call there will hang the WS since
  `run_full_session()` runs in a background thread per connection but the
  browser has nothing new to render until the next event.
