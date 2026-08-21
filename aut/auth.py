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

from aut.connector import CustomEndpointConfig, PublicAPIConfig, SocketIOEndpointConfig


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


# Discriminated union of every supported connection-request type, keyed on
# `mode` — the same pattern aut/connector.py already uses for AUTConfig.
# SessionStartRequest.connection (backend/app/main.py) is typed as this
# union so a single /ws/run request can carry an HTTP/login-gated
# connection, a Socket.IO one, a direct no-auth HTTP one, or a direct
# public-API (AUT-is-an-LLM) one.
ConnectionRequest = Annotated[
    Union[
        AUTConnectionRequest,
        SocketIOConnectionRequest,
        CustomEndpointConnectionRequest,
        PublicAPIConnectionRequest,
    ],
    Field(discriminator="mode"),
]
