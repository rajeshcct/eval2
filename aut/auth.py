"""
aut/auth.py

Login/auth wrapper for the "custom_endpoint" AUTConfig mode. Not every AUT's
chat endpoint accepts requests directly -- some require a prior login call
(username/password) that returns a bearer token, which must then be
attached to every subsequent call. This module is the ONLY place login
logic lives; aut/connector.py's call_aut() still only ever sees a plain
CustomEndpointConfig and has no idea whether a login happened.

Kept as a separate, one-time pre-step (build the config once, before a
session starts) rather than folded into aut/connector.py itself, since
call_aut() is invoked many times per session (every Describer probe, every
round) and re-logging-in on every single call would be wasteful and, for
some AUTs, could invalidate a previous token.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

import requests
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from aut.connector import BrowserConfig, CustomEndpointConfig, PublicAPIConfig, SocketIOEndpointConfig, SwaggerEndpointConfig


class AUTAuthError(RuntimeError):
    """Raised when a login call to an AUT's login_endpoint_url fails
    outright, returns a non-2xx response, isn't valid JSON, or is missing
    the expected token field. Raised loudly and specifically -- a config
    silently built with a missing/empty token would otherwise fail every
    later call_aut() instead, which is a much harder failure to diagnose.
    """


class AUTConnectionRequest(BaseModel):
    """Everything needed to reach a 'custom_endpoint' AUT, however it's
    protected. Submitted once per session (e.g. from the New Session form)
    and turned into a single CustomEndpointConfig via
    build_authenticated_endpoint_config(), reused unchanged for every
    Describer probe and every round's AUT call in that session.
    """

    mode: Literal["http"] = "http"
    chat_endpoint_url: str
    requires_login: bool = False

    login_endpoint_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    # Kept configurable rather than hardcoded -- confirmed for one specific
    # AUT during discovery, but a different AUT later could easily use a
    # different token field name or header format.
    token_field: str = "auth_token"
    auth_header_format: str = "Bearer {token}"

    timeout_seconds: float = 30.0


def _login(connection: AUTConnectionRequest) -> str:
    if not connection.login_endpoint_url:
        raise AUTAuthError("requires_login=True but login_endpoint_url was not provided.")

    try:
        response = requests.post(
            connection.login_endpoint_url,
            json={"username": connection.username, "password": connection.password},
            timeout=connection.timeout_seconds,
        )
    except requests.RequestException as e:
        raise AUTAuthError(f"Login request to '{connection.login_endpoint_url}' failed: {e}") from e

    if not response.ok:
        raise AUTAuthError(
            f"Login to '{connection.login_endpoint_url}' returned HTTP "
            f"{response.status_code}: {response.text[:500]!r}"
        )

    try:
        body = response.json()
    except ValueError as e:
        raise AUTAuthError(
            f"Login response from '{connection.login_endpoint_url}' was not valid JSON: {e}"
        ) from e

    if not isinstance(body, dict) or connection.token_field not in body:
        raise AUTAuthError(
            f"Login response from '{connection.login_endpoint_url}' is missing the "
            f"expected token field {connection.token_field!r}. Got: {body!r}"
        )

    token = body[connection.token_field]
    if not isinstance(token, str) or not token.strip():
        raise AUTAuthError(
            f"Login response field {connection.token_field!r} was empty or not a string: {token!r}"
        )
    return token


def build_authenticated_endpoint_config(connection: AUTConnectionRequest) -> CustomEndpointConfig:
    """
    Build the CustomEndpointConfig the rest of EvalMind should use for this
    AUT for an entire session.

    If connection.requires_login is False, returns
    CustomEndpointConfig(url=chat_endpoint_url, headers=None) directly -- no
    network call. If True, first POSTs {"username", "password"} to
    login_endpoint_url, extracts connection.token_field from the JSON
    response, and returns a CustomEndpointConfig whose headers carry
    {"Authorization": connection.auth_header_format.format(token=token)}.

    Args:
        connection: an AUTConnectionRequest (e.g. submitted from the New
                    Session form).

    Returns:
        A CustomEndpointConfig ready to pass straight into
        session.run_full_session(aut_config=...) -- reused unchanged for
        every call to this AUT for the whole session.

    Raises:
        AUTAuthError: if requires_login is True and the login call fails,
                      returns a non-2xx response, isn't valid JSON, or is
                      missing/has an empty token_field.
    """
    if not connection.requires_login:
        return CustomEndpointConfig(url=connection.chat_endpoint_url, headers=None)

    token = _login(connection)
    auth_header_value = connection.auth_header_format.format(token=token)
    return CustomEndpointConfig(
        url=connection.chat_endpoint_url,
        headers={"Authorization": auth_header_value},
    )


class SocketIOConnectionRequest(BaseModel):
    """Everything needed to reach a 'socketio_endpoint' AUT directly with an
    already-obtained bearer token — no login step, unlike AUTConnectionRequest's
    requires_login path. Submitted once per session from the New Session form,
    turned into a SocketIOEndpointConfig via build_socketio_endpoint_config(),
    reused unchanged for the whole session."""

    mode: Literal["socketio"] = "socketio"
    chat_endpoint_url: str
    bearer_token: str
    origin_header: Optional[str] = None
    response_timeout_seconds: float = 180.0

    # Advanced/optional — only override if the target AUT's deployment uses
    # non-default event names or path (see SocketIOEndpointConfig's own
    # docstring in aut/connector.py). Left None = use that class's defaults.
    socketio_path: Optional[str] = None
    chat_message_event: Optional[str] = None

    # Advanced/optional — max seconds of no chat:token/chat:data activity
    # before the response is treated as finished (see
    # SocketIOEndpointConfig's own docstring / _silence_watcher in
    # aut/connector.py). Left None = use that class's fixed 150.0s default.
    # Raise this for AUTs with slow-but-alive backend pauses (e.g. a cold
    # container or slow query on the first call of a session) that
    # otherwise get mistaken for "done" and truncated mid-response. Must
    # stay below response_timeout_seconds or the hard timeout wins first.
    token_silence_timeout_seconds: Optional[float] = None


def build_socketio_endpoint_config(
    connection: SocketIOConnectionRequest,
) -> SocketIOEndpointConfig:
    """Builds a SocketIOEndpointConfig directly from an already-obtained
    bearer token — unlike build_authenticated_endpoint_config(), there is no
    login call here, so this function cannot raise AUTAuthError and cannot
    validate the token. A bad/expired token is NOT caught here; it will only
    surface later, during the actual Socket.IO connect attempt inside
    run_full_session(), as a `stage: "session"` error — not `stage: "auth"`.
    Keep that distinction in main.py's ws_run() rather than "fixing" it into
    a fake auth stage; it accurately reflects that no auth step ran here.
    """
    kwargs: dict[str, Any] = dict(
        url=connection.chat_endpoint_url,
        bearer_token=connection.bearer_token,
        origin_header=connection.origin_header,
        response_timeout_seconds=connection.response_timeout_seconds,
    )
    if connection.socketio_path:
        kwargs["socketio_path"] = connection.socketio_path
    if connection.chat_message_event:
        kwargs["chat_message_event"] = connection.chat_message_event
    if connection.token_silence_timeout_seconds is not None:
        kwargs["token_silence_timeout_seconds"] = connection.token_silence_timeout_seconds
    return SocketIOEndpointConfig(**kwargs)


class CustomEndpointConnectionRequest(BaseModel):
    """Simple direct HTTP POST mode — no login, no JWT. Just POSTs
    {task_field: task} to chat_endpoint_url. The simplest connector type.
    Submitted once per session from the New Session form when
    "HTTP (No Login)" connection type is selected."""

    mode: Literal["direct_http"] = "direct_http"
    chat_endpoint_url: str
    task_field: str = "task"  # JSON key the target API expects (e.g. "user_input")
    timeout_seconds: float = 30.0


def build_custom_endpoint_config(
    connection: CustomEndpointConnectionRequest,
) -> CustomEndpointConfig:
    """Builds a CustomEndpointConfig from a no-auth direct HTTP connection
    request. No network call, no token — pure field mapping."""
    return CustomEndpointConfig(
        url=connection.chat_endpoint_url,
        task_field=connection.task_field,
        timeout_seconds=connection.timeout_seconds,
        allow_plain_text_response=True,  # direct_http APIs may return plain text instead of JSON
    )


class PublicAPIConnectionRequest(BaseModel):
    """Mode 'public_api' — the AUT IS an LLM, called directly via crewai's
    LLM() class (aut/connector.py's PublicAPIConfig), rather than reached
    over HTTP/Socket.IO. There's no endpoint to POST to and nothing to log
    into — just a system prompt and a CrewAI model string (e.g.
    'groq/llama-3.1-8b-instant', 'openai/gpt-4o-mini',
    'anthropic/claude-3-5-sonnet-20241022'). The provider's API key is read
    from this server's own .env (see config/llm_config.py's
    SUPPORTED_PROVIDERS) — never submitted from the form. Submitted once
    per session from the New Session form when "Public API (LLM)"
    connection type is selected."""

    mode: Literal["public_api"] = "public_api"
    system_prompt: str
    model: str
    temperature: Optional[float] = None


def build_public_api_config(connection: PublicAPIConnectionRequest) -> PublicAPIConfig:
    """Builds a PublicAPIConfig from a public_api connection request. Pure
    field-mapping, like build_custom_endpoint_config() — no network call,
    nothing to validate ahead of time (a bad model string or missing API
    key only surfaces later, during the actual call_aut() invocation, as a
    `stage: "session"` error — same reasoning as
    build_socketio_endpoint_config()'s docstring)."""
    kwargs: dict[str, Any] = dict(system_prompt=connection.system_prompt, model=connection.model)
    if connection.temperature is not None:
        kwargs["temperature"] = connection.temperature
    return PublicAPIConfig(**kwargs)


class SwaggerConnectionRequest(BaseModel):
    """Mode 'swagger' — the AUT is an HTTP endpoint whose request payload
    format is described by an OpenAPI/Swagger spec. EvalMind fetches the spec,
    matches the endpoint URL to a path, reads the requestBody schema, and
    identifies which field carries the user's chat message automatically.

    This is the right mode when:
      - The AUT is a documented REST API (has a /openapi.json or /swagger.yaml)
      - Its request body is NOT the simple {"task": "..."} that direct_http
        expects — it might need {"message": "...", "session_id": "abc"} or
        any other custom shape the spec describes.

    Fields:
      chat_endpoint_url: the actual API endpoint to POST to on every call.
      spec_url:          URL of the OpenAPI/Swagger spec document.
      bearer_token:      optional JWT/API key — used both to fetch the spec
                         (if it's access-controlled) and as the Authorization
                         header on every subsequent AUT call.
      timeout_seconds:   per-call HTTP timeout (default 30s).
    """

    mode: Literal["swagger"] = "swagger"
    chat_endpoint_url: str
    spec_url: str
    bearer_token: Optional[str] = None
    timeout_seconds: float = 30.0


def build_swagger_endpoint_config(
    connection: SwaggerConnectionRequest,
) -> SwaggerEndpointConfig:
    """Run Swagger auto-discovery and return a SwaggerEndpointConfig ready
    to pass into call_aut() for every round/Describer probe.

    This DOES make a network call (fetching the OpenAPI spec), so it must
    be run in a thread (asyncio.to_thread) just like build_authenticated_
    endpoint_config(). Any SwaggerAdapter* error propagates out as an
    AUTAuthError so main.py's existing `stage: 'auth'` error path handles it.

    Raises:
        AUTAuthError: wraps any SwaggerFetchError / SwaggerMatchError /
                      SwaggerSchemaError / SwaggerFieldError with a clear
                      user-facing message.
    """
    from aut.swagger_adapter import (
        discover_swagger_config,
        SwaggerAdapterError,
    )

    try:
        result = discover_swagger_config(
            endpoint_url=connection.chat_endpoint_url,
            spec_url=connection.spec_url,
            bearer_token=connection.bearer_token,
        )
    except SwaggerAdapterError as e:
        raise AUTAuthError(
            f"Swagger auto-discovery failed for '{connection.chat_endpoint_url}': {e}"
        ) from e

    return SwaggerEndpointConfig(
        url=connection.chat_endpoint_url,
        message_field=result.message_field,
        static_fields=result.static_fields,
        headers=result.extra_headers or None,
        timeout_seconds=connection.timeout_seconds,
        schema_summary=result.schema_summary,
    )


class BrowserConnectionRequest(BaseModel):
    """Mode 'browser' — the AUT is a web chatbot UI driven by a real
    Playwright-controlled Chromium browser. EvalMind types the task into
    the chat input, clicks Send, waits for the reply, and scrapes the text.

    No API key or endpoint needed — just the page URL and CSS selectors
    for the input box, send button, and response area.

    Optional login: set requires_login=True and provide the login URL,
    selectors, and credentials. Login happens once at session start; all
    subsequent rounds reuse the saved browser session (cookies stay intact).
    """

    mode: Literal["browser"] = "browser"

    # Chatbot page
    chatbot_url: str
    input_selector: str = "textarea"         # CSS selector for the chat input
    send_selector: str = "button[type=submit]"  # CSS selector for Send button
    response_selector: str = ".message:last-child"  # CSS selector for response

    # Response detection
    wait_strategy: str = "text_change"   # 'new_element' | 'text_change' | 'fixed_delay'
    wait_timeout_seconds: float = 60.0
    fixed_delay_seconds: float = 5.0

    # Browser
    headless: bool = True

    # Optional login
    requires_login: bool = False
    login_url: Optional[str] = None
    username_selector: Optional[str] = None
    password_selector: Optional[str] = None
    submit_selector: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    login_success_url_contains: Optional[str] = None
    login_success_selector: Optional[str] = None

    # Optional — selector for a floating/launcher button that must be
    # clicked to open the chat widget before typing (see BrowserConfig's
    # own docstring in aut/connector.py). Leave blank if the chat input is
    # already visible on page load.
    chat_launcher_selector: Optional[str] = None


def build_browser_config(connection: BrowserConnectionRequest) -> BrowserConfig:
    """Pure field-mapping — no network call. Translates a BrowserConnectionRequest
    (from the frontend form) into a BrowserConfig ready for call_aut().
    Any missing-playwright error surfaces later during the actual call, as a
    `stage: 'session'` error — same pattern as build_public_api_config()."""
    return BrowserConfig(
        chatbot_url=connection.chatbot_url,
        input_selector=connection.input_selector,
        send_selector=connection.send_selector,
        response_selector=connection.response_selector,
        wait_strategy=connection.wait_strategy,
        wait_timeout_seconds=connection.wait_timeout_seconds,
        fixed_delay_seconds=connection.fixed_delay_seconds,
        headless=connection.headless,
        requires_login=connection.requires_login,
        login_url=connection.login_url,
        username_selector=connection.username_selector,
        password_selector=connection.password_selector,
        submit_selector=connection.submit_selector,
        username=connection.username,
        password=connection.password,
        login_success_url_contains=connection.login_success_url_contains,
        login_success_selector=connection.login_success_selector,
        chat_launcher_selector=connection.chat_launcher_selector,
    )


# Discriminated union of every supported connection-request type, keyed on
# `mode` — the same pattern aut/connector.py already uses for AUTConfig.
ConnectionRequest = Annotated[
    Union[
        AUTConnectionRequest,
        SocketIOConnectionRequest,
        CustomEndpointConnectionRequest,
        PublicAPIConnectionRequest,
        SwaggerConnectionRequest,
        BrowserConnectionRequest,
    ],
    Field(discriminator="mode"),
]
