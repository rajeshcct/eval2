# EvalMind Backend (Phase II)

A thin FastAPI service that is the *only* thing the frontend talks to. It never
re-implements pipeline logic — it just wires HTTP/WebSocket around the
functions that already exist (`session.run_full_session()`, `aut.auth.
build_authenticated_endpoint_config()`, `db.store.get_final_report()`).

## Install

From the **project root** (not inside `backend/`):

```
pip install -r requirements.txt          # if not already installed
pip install -r backend/requirements.txt
```

## Run

Run from the **project root**, using `python -m uvicorn` (not the bare `uvicorn`
command):

```
python -m uvicorn backend.app.main:app --reload --port 8000
```

**Why `python -m uvicorn` from the project root, specifically:** `backend/app/main.py`
imports the project's existing top-level modules directly (`session`, `aut.auth`,
`db.store`, `aggregator`, `config.llm_config`) — no `sys.path` hacking inside the
backend package itself. `python -m uvicorn ...` runs uvicorn the same way `python -m`
runs any module: it adds the **current working directory** to `sys.path[0]`. Since
you're running it from the project root, the project root ends up importable, and
those imports resolve correctly. The bare `uvicorn ...` console-script entry point
does *not* do this (its `sys.path[0]` is the script's own install directory), so it
will fail with `ModuleNotFoundError: No module named 'session'` if used instead —
use `python -m uvicorn`, not `uvicorn`, from the project root.

The API is then live at `http://localhost:8000`, with interactive docs at
`http://localhost:8000/docs`.

Reuses the project root's own `.env` — no separate backend `.env` is needed;
`config/llm_config.py`, `aut/connector.py`, etc. all already call `load_dotenv()`
themselves.

## Endpoints

### `WS /ws/run`

The live-run endpoint. On connect, send exactly one JSON message:

```json
{
  "connection": {
    "chat_endpoint_url": "https://your-aut.example.com/chat",
    "requires_login": false,
    "login_endpoint_url": null,
    "username": null,
    "password": null,
    "token_field": "auth_token",
    "auth_header_format": "Bearer {token}"
  },
  "max_rounds": 5,
  "capability_description_override": null
}
```

`connection` is Phase I's `AUTConnectionRequest` (`aut/auth.py`) verbatim — set
`requires_login: true` and fill in `login_endpoint_url` / `username` / `password`
for an AUT whose chat endpoint needs a bearer token first. `capability_description_override`
is optional — if omitted (or `null`), the Describer auto-discovers the AUT first
(fires its own `describer_started` / `describer_completed` events); if given a
non-empty string, the Describer is skipped entirely and that string is used as the
AUT's capability description.

The server then streams every `ProgressEvent` (`progress.py`) back as JSON,
`{"type": ..., "data": ...}`, in real time, ending in either:
- `session_completed` — `data` is the complete `FinalReport`, then the socket closes, or
- `error` — `data` is `{"stage": ..., "message": ...}`, then the socket closes.

### `GET /api/sessions/{session_id}/report`

Reloads a finished session's `FinalReport` purely from its `session_id`, no
re-running anything. `404` if that session has no persisted report yet (still
running, or never existed).

### `GET /api/health`

`{"status": "ok", "llm_configured": true|false}` — wraps `config.llm_config.is_configured()`,
so the frontend can show a clear "no LLM key configured" state instead of a
run just silently failing partway through.

## Testing

```
python backend/tests/test_ws_flow.py
```

Uses FastAPI's `TestClient` against `manual` AUT mode + a stubbed Generator/Judge
(no real network/LLM calls for the pipeline itself), so it runs fast and
deterministically — but `aggregator.build_final_report()`'s closing
`overall_verdict` is always a real LLM call (see `aggregator.py`'s own module
docstring for why), so this script is **skipped** (not failed) if no LLM key is
configured in `.env` — same convention as `tests/test_aggregator.py`.
