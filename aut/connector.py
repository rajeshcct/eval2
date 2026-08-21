"""
aut/connector.py

The AUT (Agent Under Test) connection layer — EvalMind's single point of
contact with whatever system is actually being evaluated.

Exposes exactly ONE public function, call_aut(task, config) -> AUTResponse,
that behaves identically no matter which of four backends is behind it. The
rest of the pipeline (main.py, agents/generator.py, agents/judge.py,
db.store) should only ever import call_aut(), AUTConfig, and AUTResponse
from this module — nothing downstream should branch on which mode is active.

The five modes:

  - "public_api"       — the AUT IS an LLM. Called directly via crewai's
                        LLM() class, given a system prompt and a CrewAI
                        model string (e.g. "groq/llama-3.1-8b-instant").
                        This is deliberately separate from
                        config.llm_config.get_llm(), which is reserved for
                        EvalMind's OWN Describer/Generator/Judge agents —
                        the AUT's model is a property of the AUT, not of
                        the evaluator, and is swapped by editing AUTConfig,
                        never by editing .env.
  - "custom_endpoint"   — the AUT is a deployed HTTP service. EvalMind POSTs
                        {"task": task} as JSON and reads the output back out
                        of the response body.
  - "socketio_endpoint" — the AUT is a Socket.IO backend (e.g. a streaming
                        chat service authenticated by a bearer JWT).
                        EvalMind connects, emits a chat message event, and
                        reassembles the streamed tokens into one output
                        string. See SocketIOEndpointConfig's own docstring.
  - "function_import"   — the AUT is a local Python callable, either passed
                        in already-imported or referenced by
                        (module_path, function_name) and imported lazily.
  - "manual"            — the guaranteed fallback for the live demo. Looks up
                        a pre-recorded response for `task` (task text OR a
                        short task id — both are just JSON object keys) from
                        a JSON file. No network call, no timer: whatever
                        latency/tokens/cost were recorded are returned
                        exactly as-is.

All provider- and transport-specific logic (the crewai LLM() call, the
requests.post(), the dynamic import, the JSON file lookup) is intentionally
confined to this one file, per the project's "don't hardcode provider logic
outside the connection layer" rule.

Fields AUTResponse cannot honestly populate for a given mode are left as
None rather than guessed at — e.g. tokens_used/estimated_cost for
custom_endpoint and function_import (unless the AUT itself reports them),
or estimated_cost for public_api (crewai's LLM() doesn't surface a per-call
cost). None is used to mean "unknown", never a stand-in 0 or 0.0.
"""
from __future__ import annotations

import importlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from typing_extensions import Annotated

# So GROQ_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / etc. are available
# for "public_api" mode even if this module is imported before anything else
# in the project has triggered dotenv loading. No-op if .env doesn't exist,
# same as config/llm_config.py's own load_dotenv() call.
load_dotenv()


# ==========================================================================
# Response shape — identical no matter which backend produced it.
# ==========================================================================
class AUTResponse(BaseModel):
    """What call_aut() always returns, regardless of mode.

    tokens_used / estimated_cost are None whenever the active mode genuinely
    cannot supply them — never a stand-in value like 0 or 0.0.
    """

    output: str
    latency_ms: float
    tokens_used: Optional[int] = None
    estimated_cost: Optional[float] = None


# ==========================================================================
# Config — one Pydantic model per mode, joined into a discriminated union
# keyed on `mode`. Each mode's `mode` field defaults to its own literal, so
# e.g. ManualConfig(json_path="...") works without spelling out mode="manual".
# ==========================================================================
class PublicAPIConfig(BaseModel):
    """Mode 'public_api' — the AUT is itself an LLM, called directly via
    crewai's LLM() class (never through config.llm_config.get_llm(), which
    is reserved for EvalMind's own Describer/Generator/Judge agents)."""

    mode: Literal["public_api"] = "public_api"
    system_prompt: str
    model: str  # a CrewAI LLM model string, e.g. "groq/llama-3.1-8b-instant"
    temperature: Optional[float] = None


class CustomEndpointConfig(BaseModel):
    """Mode 'custom_endpoint' — the AUT is a deployed HTTP service. EvalMind
    POSTs {task_field: task} and reads the output back out of the JSON body
    (accepts an "output"/"response"/"result"/"text" key, or a bare string
    body — see _extract_output_text).

    `task_field` controls the JSON key used in the request body. Defaults to
    "task" (i.e. {"task": "..."}) but can be overridden to match any API
    that expects a different field name (e.g. "user_input", "message", etc.).
    """

    mode: Literal["custom_endpoint"] = "custom_endpoint"
    url: str
    headers: Optional[dict[str, str]] = None
    timeout_seconds: float = 30.0
    task_field: str = "task"  # JSON key to use in the request body; override if the API expects e.g. "user_input"
    allow_plain_text_response: bool = False  # if True, fall back to raw response text when body is not valid JSON (for direct_http mode)


class SocketIOEndpointConfig(BaseModel):
    """Mode 'socketio_endpoint' — the AUT is a Socket.IO backend (e.g. a
    streaming chat service) rather than a plain request/response HTTP
    endpoint. EvalMind connects over Socket.IO, authenticates via
    `auth: {token: bearer_token}` (the JWT-only pattern several such
    backends use), emits `chat_message_event` with `{message: task,
    thread_id: ...}`, and reassembles the AUT's answer as the concatenation
    of every `content` field off streaming `chat:token` events, stopping at
    whichever terminal event arrives first: `chat:done` (success) or
    `chat:error` (failure -> raises AUTConnectorError with that message).

    `bearer_token` must already be a valid token for this AUT -- obtaining
    one (e.g. by logging into the CUSTOMER's own site, not the AUT itself)
    is a one-time pre-step out of scope for this file, exactly like
    custom_endpoint expects `headers` to already carry a valid Authorization
    value. See aut/navigatto_auth.py for a worked example of that login
    step.

    Set `persist_thread=True` to keep using the same conversation thread
    across multiple call_aut() calls with this same config instance (the
    `thread_id` field is updated in place from each `chat:start` event,
    mirroring how a real frontend tracks `currentThreadId`). Leave it False
    (the default) to start a fresh thread on every call -- usually what an
    evaluator wants, since probes shouldn't leak context between rounds
    unless a test is deliberately checking multi-turn behavior.
    """

    mode: Literal["socketio_endpoint"] = "socketio_endpoint"
    url: str
    bearer_token: str
    socketio_path: str = "/socket.io/"
    chat_message_event: str = "chat_message"
    thread_id: Optional[str] = None
    persist_thread: bool = False
    connect_timeout_seconds: float = 15.0
    response_timeout_seconds: float = 120.0
    http_session_timeout_seconds: float = 30.0  # low-level HTTP read timeout for polling handshake
    token_silence_timeout_seconds: float = 35.0  # if tokens stop arriving for this long, treat stream as done
    origin_header: Optional[str] = None  # e.g. "https://assetcct.navigatto.ai" — sent as
    # the HTTP Origin header on the polling upgrade request so servers that
    # enforce CORS/origin checks accept the connection.


class FunctionImportConfig(BaseModel):
    """Mode 'function_import' — the AUT is a local Python callable. Provide
    EITHER an already-imported `function`, OR a (module_path, function_name)
    pair to import lazily inside call_aut() — exactly one, not both, not
    neither."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mode: Literal["function_import"] = "function_import"
    function: Optional[Callable[[str], Any]] = None
    module_path: Optional[str] = None
    function_name: Optional[str] = None

    @model_validator(mode="after")
    def _check_exactly_one_reference(self) -> "FunctionImportConfig":
        has_direct = self.function is not None
        has_dotted = bool(self.module_path) and bool(self.function_name)
        if has_direct == has_dotted:  # True/True or False/False — both invalid
            raise ValueError(
                "FunctionImportConfig needs EITHER `function` (an already-imported "
                "callable) OR both `module_path` and `function_name` — not both, "
                "and not neither."
            )
        return self


class ManualConfig(BaseModel):
    """Mode 'manual' — the guaranteed demo fallback. Looks up `task` verbatim
    as a top-level key in a JSON file of pre-recorded responses (task text
    or a short task id both work — it's just a dict key). No network call,
    no timer."""

    mode: Literal["manual"] = "manual"
    json_path: str


AUTConfig = Annotated[
    Union[
        PublicAPIConfig,
        CustomEndpointConfig,
        SocketIOEndpointConfig,
        FunctionImportConfig,
        ManualConfig,
    ],
    Field(discriminator="mode"),
]

# Convenience for constructing an AUTConfig from a raw dict (e.g. loaded from
# a JSON/YAML settings file) with the right subtype picked automatically off
# `mode`. call_aut() itself doesn't require configs to go through this —
# passing an already-built PublicAPIConfig/CustomEndpointConfig/
# FunctionImportConfig/ManualConfig instance directly works too.
AUTConfigAdapter: TypeAdapter[AUTConfig] = TypeAdapter(AUTConfig)


# ==========================================================================
# Errors
# ==========================================================================
class AUTConnectorError(RuntimeError):
    """Base class for all aut/connector.py errors."""


class ManualLookupError(AUTConnectorError):
    """Raised when 'manual' mode can't find `task` in its JSON file.

    Raised loudly and specifically rather than falling back to an empty or
    default response — manual mode is the guaranteed fallback for the live
    demo, so a silent miss here would be the worst possible failure mode.
    """


# ==========================================================================
# Backend implementations — each takes (task, config) and returns an
# AUTResponse. These are internal; only call_aut() below is public, and
# nothing outside this file should call these directly or switch on
# config.mode itself.
# ==========================================================================
def _call_public_api(task: str, config: PublicAPIConfig) -> AUTResponse:
    from crewai import LLM  # local import: keeps crewai optional for the other 3 modes

    llm_kwargs: dict[str, Any] = {"model": config.model}
    if config.temperature is not None:
        llm_kwargs["temperature"] = config.temperature
    llm = LLM(**llm_kwargs)

    messages = [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": task},
    ]

    start = time.perf_counter()
    output = llm.call(messages=messages)
    latency_ms = (time.perf_counter() - start) * 1000

    if not isinstance(output, str):
        # A tool-call result or other non-text return; stringify rather than crash.
        output = str(output)

    # This LLM instance was just created above and used exactly once, so its
    # lifetime usage totals (crewai tracks usage per-instance, cumulative)
    # ARE this call's totals.
    usage = llm.get_token_usage_summary()
    tokens_used = usage.total_tokens if usage.total_tokens > 0 else None

    return AUTResponse(
        output=output,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        # crewai's LLM() doesn't surface a reliable per-call cost figure —
        # left as None rather than computed from a hardcoded pricing table.
        estimated_cost=None,
    )


def _extract_output_text(body: Any) -> str:
    """A custom_endpoint's JSON body might be a bare string or an object with
    an 'output'/'response'/'result'/'text' key — accept any of these rather
    than forcing every real-world AUT to match one exact schema."""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        for key in ("output", "response", "result", "text"):
            value = body.get(key)
            if isinstance(value, str):
                return value
    raise AUTConnectorError(
        "custom_endpoint response body did not contain a recognizable output "
        f"field (expected a bare string, or a JSON object with an "
        f"'output'/'response'/'result'/'text' string key). Got: {body!r}"
    )


def _call_custom_endpoint(task: str, config: CustomEndpointConfig) -> AUTResponse:
    start = time.perf_counter()
    try:
        http_response = requests.post(
            config.url,
            json={config.task_field: task},
            headers=config.headers,
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as e:
        raise AUTConnectorError(f"custom_endpoint request to '{config.url}' failed: {e}") from e
    latency_ms = (time.perf_counter() - start) * 1000

    if not http_response.ok:
        raise AUTConnectorError(
            f"custom_endpoint '{config.url}' returned HTTP {http_response.status_code}: "
            f"{http_response.text[:500]!r}"
        )

    try:
        body = http_response.json()
    except ValueError as e:
        if config.allow_plain_text_response and http_response.text.strip():
            # Plain-text response (e.g. direct_http APIs that return raw text
            # rather than JSON) — use it directly as the output.
            return AUTResponse(
                output=http_response.text.strip(),
                latency_ms=latency_ms,
                tokens_used=None,
                estimated_cost=None,
            )
        raise AUTConnectorError(
            f"custom_endpoint '{config.url}' response body was not valid JSON: {e}"
        ) from e

    output = _extract_output_text(body)

    # Tokens/cost usually aren't available from a bare test endpoint, but if
    # the real AUT happens to report them, pass them through rather than
    # discarding them.
    tokens_used = body.get("tokens_used") if isinstance(body, dict) else None
    estimated_cost = body.get("estimated_cost") if isinstance(body, dict) else None

    return AUTResponse(
        output=output,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        estimated_cost=estimated_cost,
    )


def _call_socketio_endpoint(task: str, config: SocketIOEndpointConfig) -> AUTResponse:
    import socketio  # local import: keeps python-socketio optional for the other 4 modes

    tokens: list[str] = []
    start_payload: dict[str, Any] = {}
    error_message: dict[str, str] = {}
    finished = threading.Event()
    silence_triggered = threading.Event()  # set if we finished via token-silence fallback

    import requests as _requests
    _http_session = _requests.Session()
    _http_session.request = lambda *a, **kw: type(_http_session).request(  # type: ignore[method-assign]
        _http_session, *a, **{"timeout": config.http_session_timeout_seconds, **kw}
    )
    client = socketio.Client(reconnection=False, http_session=_http_session)

    # Track when we last received a token so the silence watcher can fire.
    _last_token_time: list[float] = []

    @client.on("chat:start")
    def _on_start(data=None):
        if isinstance(data, dict):
            start_payload.update(data)

    @client.on("chat:token")
    def _on_token(data=None):
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, str):
            tokens.append(content)
            _last_token_time.append(time.perf_counter())

    @client.on("chat:error")
    def _on_error(data=None):
        error_message["message"] = (
            data.get("message", "Unknown chat:error") if isinstance(data, dict) else "Unknown chat:error"
        )
        finished.set()

    @client.on("chat:done")
    def _on_done(data=None):
        finished.set()

    @client.on("connect_error")
    def _on_connect_error(data=None):
        error_message.setdefault("connect", str(data))

    def _silence_watcher():
        """Fires finished if tokens stop arriving for token_silence_timeout_seconds.
        Only activates after the first token has been received."""
        silence = config.token_silence_timeout_seconds
        deadline = time.perf_counter() + config.response_timeout_seconds
        while not finished.is_set() and time.perf_counter() < deadline:
            time.sleep(1.0)
            if _last_token_time and not finished.is_set():
                idle = time.perf_counter() - _last_token_time[-1]
                if idle >= silence:
                    silence_triggered.set()
                    finished.set()
                    return

    watcher = threading.Thread(target=_silence_watcher, daemon=True)

    start = time.perf_counter()
    try:
        extra_headers = {"Origin": config.origin_header} if config.origin_header else {}
        client.connect(
            config.url,
            socketio_path=config.socketio_path,
            auth={"token": config.bearer_token},
            transports=["polling", "websocket"],
            headers=extra_headers,
            wait_timeout=config.connect_timeout_seconds,
        )
    except Exception as e:  # noqa: BLE001 - surfaced as one uniform connector error
        raise AUTConnectorError(
            f"socketio_endpoint: failed to connect to '{config.url}{config.socketio_path}': {e}"
        ) from e

    try:
        client.emit(
            config.chat_message_event,
            {"message": task, "thread_id": config.thread_id},
        )
        watcher.start()
        got_terminal_event = finished.wait(timeout=config.response_timeout_seconds)
    finally:
        client.disconnect()
    latency_ms = (time.perf_counter() - start) * 1000

    # Silence fallback counts as success if we actually got tokens
    if silence_triggered.is_set() and tokens:
        got_terminal_event = True

    if not got_terminal_event:
        raise AUTConnectorError(
            f"socketio_endpoint: no 'chat:done' or 'chat:error' event received from "
            f"'{config.url}' within {config.response_timeout_seconds}s of sending the task "
            f"(received {len(tokens)} chat:token event(s) before timing out)."
        )

    if "message" in error_message:
        raise AUTConnectorError(f"socketio_endpoint: AUT returned chat:error: {error_message['message']}")

    if config.persist_thread:
        new_thread_id = start_payload.get("thread_id")
        if isinstance(new_thread_id, str) and new_thread_id:
            config.thread_id = new_thread_id

    return AUTResponse(
        output="".join(tokens),
        latency_ms=latency_ms,
        # Streaming chat backends built like this one generally don't report
        # token/cost accounting over the socket -- left as None rather than
        # guessed at, same rule as every other mode in this file.
        tokens_used=None,
        estimated_cost=None,
    )


def _resolve_function(config: FunctionImportConfig) -> Callable[[str], Any]:
    if config.function is not None:
        return config.function

    assert config.module_path is not None and config.function_name is not None  # enforced by validator
    try:
        module = importlib.import_module(config.module_path)
    except ImportError as e:
        raise AUTConnectorError(f"Could not import module '{config.module_path}': {e}") from e

    try:
        fn = getattr(module, config.function_name)
    except AttributeError as e:
        raise AUTConnectorError(
            f"Module '{config.module_path}' has no attribute '{config.function_name}'."
        ) from e

    if not callable(fn):
        raise AUTConnectorError(
            f"'{config.module_path}.{config.function_name}' is not callable."
        )
    return fn


def _call_function_import(task: str, config: FunctionImportConfig) -> AUTResponse:
    fn = _resolve_function(config)

    start = time.perf_counter()
    try:
        output = fn(task)
    except Exception as e:
        raise AUTConnectorError(f"function_import target raised an exception: {e}") from e
    latency_ms = (time.perf_counter() - start) * 1000

    if not isinstance(output, str):
        output = str(output)

    # Typically None unless the function itself is wired up to report usage
    # (not supported generically here — a plain str-in/str-out function has
    # no standard way to surface tokens/cost).
    return AUTResponse(output=output, latency_ms=latency_ms, tokens_used=None, estimated_cost=None)


def _load_manual_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AUTConnectorError(
            f"manual mode: JSON file not found at '{path}'. This mode is the "
            f"guaranteed demo fallback, so a missing file is treated as a hard error."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AUTConnectorError(f"manual mode: '{path}' is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise AUTConnectorError(
            f"manual mode: '{path}' must contain a JSON object mapping task text/id "
            f"to a recorded response, got a top-level {type(data).__name__} instead."
        )
    return data


def _call_manual(task: str, config: ManualConfig) -> AUTResponse:
    path = Path(config.json_path)
    data = _load_manual_data(path)

    if task not in data:
        raise ManualLookupError(
            f"manual mode: no recorded response for task {task!r} in '{path}'. "
            f"Known keys ({len(data)}): {list(data.keys())}"
        )

    entry = data[task]
    if not isinstance(entry, dict):
        raise AUTConnectorError(
            f"manual mode: entry for task {task!r} in '{path}' must be a JSON "
            f"object with at least 'output' and 'latency_ms' keys, got {entry!r}"
        )

    missing = [key for key in ("output", "latency_ms") if key not in entry]
    if missing:
        raise AUTConnectorError(
            f"manual mode: entry for task {task!r} in '{path}' is missing required "
            f"field(s) {missing}: {entry!r}"
        )

    # No timer here on purpose — manual mode returns the recorded
    # latency/tokens/cost exactly as they were saved, never a live/simulated
    # measurement.
    return AUTResponse(
        output=entry["output"],
        latency_ms=float(entry["latency_ms"]),
        tokens_used=entry.get("tokens_used"),
        estimated_cost=entry.get("estimated_cost"),
    )


# ==========================================================================
# Public entry point
# ==========================================================================
_DISPATCH: dict[str, Callable[[str, Any], AUTResponse]] = {
    "public_api": _call_public_api,
    "custom_endpoint": _call_custom_endpoint,
    "socketio_endpoint": _call_socketio_endpoint,
    "function_import": _call_function_import,
    "manual": _call_manual,
}


def call_aut(task: str, config: AUTConfig) -> AUTResponse:
    """
    Call the Agent Under Test, whatever it actually is, and return a
    uniform AUTResponse. This is the ONLY function the rest of EvalMind
    (Generator -> AUT -> Judge -> db.store) should ever call — nothing
    downstream needs to know or branch on which of the four modes is active.

    Args:
        task: the test task text (or, for "manual" mode, a task id) to send
              to the AUT.
        config: a PublicAPIConfig, CustomEndpointConfig, FunctionImportConfig,
                or ManualConfig instance — see each class's docstring.

    Returns:
        AUTResponse with the AUT's output, latency, and (where the active
        mode can actually provide them) token/cost accounting.

    Raises:
        ValueError: if `task` is empty.
        ManualLookupError: ("manual" mode only) if `task` has no recorded
                            response in the JSON file — raised loudly
                            rather than failing silently, since this mode
                            is the guaranteed live-demo fallback.
        AUTConnectorError: for any other mode-specific failure (a bad HTTP
                            response, an unresolvable function reference, a
                            malformed manual JSON file, etc).
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")

    handler = _DISPATCH[config.mode]
    return handler(task, config)
