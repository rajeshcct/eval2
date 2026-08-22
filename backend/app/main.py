"""
backend/app/main.py

Phase II — the FastAPI backend. A thin service that is the ONLY thing the
frontend (Phase III onward) ever talks to. It never re-implements pipeline
logic; it only wires HTTP/WebSocket around functions that already exist:
session.run_full_session() (Phase I's on_event plumbing forwards live over
the WebSocket) and db.store.get_final_report() (the Aggregator's Block G
"reconstruct from session_id alone" reload path).

Run from the project root (see backend/README.md for exactly why "from the
project root" matters):
    python -m uvicorn backend.app.main:app --reload --port 8000
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator

from aggregator import FinalReport
from aut.auth import (
    ConnectionRequest,
    build_authenticated_endpoint_config,
    build_custom_endpoint_config,
    build_public_api_config,
    build_socketio_endpoint_config,
)
from aut.connector import call_aut
from config.llm_config import is_configured
from db.store import get_final_report, init_db
from session import run_full_session

# A throwaway prompt sent once, before the real session, whenever a
# socketio_endpoint AUT is used — see _warm_up_socketio_aut()'s docstring
# for why this exists.
_WARMUP_TASK = "Hello"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Same init_db() every existing entry point (main.py, every tests/*
    # script) calls — idempotent (creates tables only if missing), safe to
    # call unconditionally on every server startup.
    init_db()
    yield


app = FastAPI(title="EvalMind Backend", lifespan=lifespan)

# Local Vite dev server origins (Phase III's `npm run dev` default and its
# 127.0.0.1 equivalent). Note this covers HTTP requests only — Starlette's
# CORSMiddleware does not gate the WebSocket handshake itself; /ws/run is
# reachable from any origin, same as a plain WS server normally is.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================================
# Request schema
# ==========================================================================
class SessionStartRequest(BaseModel):
    """The one JSON message a /ws/run client sends immediately after the
    WebSocket connects. `connection` is aut/auth.py's ConnectionRequest — a
    discriminated union (on `mode`) of either an AUTConnectionRequest
    ("http", Phase I's original login-gated/plain HTTP mode) or a
    SocketIOConnectionRequest ("socketio", an already-obtained bearer
    token). max_rounds and capability_description_override map straight
    onto session.run_full_session()'s own parameters of the same name.
    """

    connection: ConnectionRequest
    max_rounds: int = 5
    capability_description_override: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _default_connection_mode(cls, data: Any) -> Any:
        # Back-compat shim: a raw `connection` payload with no `mode` key
        # predates this field entirely (e.g. backend/tests/test_ws_flow.py's
        # fixed WS payload) and always meant HTTP mode. Pydantic's
        # discriminated union requires the `mode` tag to be PRESENT on the
        # wire -- it does NOT fall back to AUTConnectionRequest.mode's own
        # default -- so that has to be patched in here, before union
        # validation runs, to actually deliver on "default preserves
        # current behavior." Any `connection` that already has a `mode`
        # key (explicit "http" or "socketio") passes through untouched.
        if isinstance(data, dict):
            connection = data.get("connection")
            if isinstance(connection, dict) and "mode" not in connection:
                data = {**data, "connection": {**connection, "mode": "http"}}
        return data


# ==========================================================================
# WS /ws/run — the live-run endpoint.
# ==========================================================================
_DONE = object()  # internal sentinel; never actually sent over the wire


def _warm_up_socketio_aut(aut_config: Any) -> None:
    """Best-effort throwaway call before a socketio_endpoint session starts.

    Some socketio_endpoint AUTs (observed with Navigatto) take a long,
    genuinely-alive pause on the FIRST call of a session — a cold
    container, a cold DB connection, an unwarmed cache — that can exceed
    the connector's token-silence fallback (SocketIOEndpointConfig's
    token_silence_timeout_seconds, fixed at 150.0s unless overridden) and
    get the response truncated mid-stream, even though the AUT was never
    actually broken. Sending one disposable "Hello" and discarding the
    result before the real Describer/round calls begin means that cold
    start is paid for here instead of during round 1 of the real
    evaluation, where it would otherwise corrupt a real scored round.

    Deliberately swallows every exception — a failed warm-up should never
    block or fail the real run; if the AUT is genuinely unreachable, that
    will surface again immediately, correctly, on the real first call
    inside run_full_session().
    """
    try:
        call_aut(_WARMUP_TASK, aut_config)
    except Exception:  # noqa: BLE001 - best-effort only, never propagate
        pass


@app.websocket("/ws/run")
async def ws_run(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        raw = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    except Exception as e:  # noqa: BLE001 - frame wasn't valid JSON, etc.
        await _send_error_and_close(websocket, "request", f"Could not read start message: {e}")
        return

    try:
        start_request = SessionStartRequest.model_validate(raw)
    except Exception as e:  # noqa: BLE001 - pydantic ValidationError: wrong shape
        await _send_error_and_close(websocket, "request_validation", str(e))
        return

    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[Any]" = asyncio.Queue()

    def on_event(event: Dict[str, Any]) -> None:
        # Called from the WORKER THREAD for every real progress event fired
        # deep inside run_full_session() (describer_started ... round_
        # completed ... session_completed), and also directly from this
        # coroutine's own except blocks below for a request-level failure.
        # call_soon_threadsafe is required for the former and harmless (if
        # marginally redundant) for the latter, so one helper covers both.
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def worker() -> None:
        try:
            if start_request.connection.mode == "socketio":
                # build_socketio_endpoint_config() is pure field-mapping and
                # never raises (see its docstring in aut/auth.py) — a bad or
                # expired token is NOT caught here. It only surfaces later,
                # during the actual Socket.IO connect attempt inside
                # run_full_session(), as a `stage: "session"` error below —
                # not `stage: "auth"`. That's intentional: it accurately
                # reflects that no auth step ran for this mode, so don't
                # special-case it into a fake auth-stage failure.
                aut_config = await asyncio.to_thread(
                    build_socketio_endpoint_config, start_request.connection
                )
                # See _warm_up_socketio_aut()'s docstring — pays for a slow
                # first-call cold start here, once, before it can corrupt a
                # real scored round.
                await asyncio.to_thread(_warm_up_socketio_aut, aut_config)
            elif start_request.connection.mode == "direct_http":
                # build_custom_endpoint_config() is pure field-mapping too —
                # no network call, cannot raise AUTAuthError.
                aut_config = await asyncio.to_thread(
                    build_custom_endpoint_config, start_request.connection
                )
            elif start_request.connection.mode == "public_api":
                # build_public_api_config() is pure field-mapping too — no
                # network call, cannot raise AUTAuthError. A bad model
                # string or missing provider API key only surfaces later,
                # during the actual call_aut() invocation inside
                # run_full_session(), as a `stage: "session"` error below.
                aut_config = await asyncio.to_thread(
                    build_public_api_config, start_request.connection
                )
            else:
                aut_config = await asyncio.to_thread(
                    build_authenticated_endpoint_config, start_request.connection
                )
        except Exception as e:  # noqa: BLE001 - AUTAuthError or any login failure ("http" mode only)
            on_event({"type": "error", "data": {"stage": "auth", "message": str(e)}})
            await queue.put(_DONE)
            return

        try:
            # run_full_session() is synchronous and makes real blocking
            # network/LLM calls — MUST run off the event loop, or the
            # WebSocket (and every other connection this server is
            # handling) stops servicing messages for the whole run.
            await asyncio.to_thread(
                run_full_session,
                aut_config=aut_config,
                max_rounds=start_request.max_rounds,
                capability_description_override=start_request.capability_description_override,
                on_event=on_event,
            )
        except Exception as e:  # noqa: BLE001 - never let a real failure crash the socket silently
            on_event({"type": "error", "data": {"stage": "session", "message": str(e)}})
        finally:
            await queue.put(_DONE)

    worker_task = asyncio.create_task(worker())

    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            await websocket.send_json(item)
    except WebSocketDisconnect:
        # Client went away mid-run. run_full_session() is already executing
        # on its own background thread, mid real network/LLM calls — it
        # can't be safely interrupted, so it's left to finish and persist
        # to the DB normally; there's just no one left to stream events to.
        pass
    finally:
        if not worker_task.done():
            await worker_task
        await _safe_close(websocket)


async def _send_error_and_close(websocket: WebSocket, stage: str, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "data": {"stage": stage, "message": message}})
    except Exception:  # noqa: BLE001 - socket may already be half-closed
        pass
    await _safe_close(websocket)


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except Exception:  # noqa: BLE001 - already closed / client disconnected first
        pass


# ==========================================================================
# GET /api/sessions/{session_id}/report — reload a finished report by id.
# ==========================================================================
@app.get("/api/sessions/{session_id}/report", response_model=FinalReport)
async def get_session_report(session_id: str) -> FinalReport:
    """Independently queryable reload path (Block G): reads the persisted
    row db.store.get_final_report() wrote the moment aggregator.
    build_final_report() finished, inside the SAME run_full_session() call
    /ws/run above just triggered. Never re-runs the Aggregator (and its LLM
    call) here — that only happens once, live, during the run itself.
    """
    row = await asyncio.to_thread(get_final_report, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No final report found for session_id={session_id!r}")
    return FinalReport.model_validate_json(row["report_json"])


# ==========================================================================
# GET /api/health
# ==========================================================================
@app.get("/api/health")
async def health() -> Dict[str, Any]:
    configured = await asyncio.to_thread(is_configured)
    return {"status": "ok", "llm_configured": configured}
