"""
aut/chatbotapp_wrapper.py

function_import-mode AUT wrapper for chatbotapp.ai's internal chat API
(https://api.chatbotapp.ai/api/v2/chat).

WHY function_import AND NOT custom_endpoint:
  - The response is a Server-Sent Events stream (accept: text/event-stream),
    not a single JSON body -- CustomEndpointConfig's _extract_output_text()
    expects one JSON object back, not a stream to reassemble.
  - Auth is a Firebase ID token in a custom `x_token` header (plus
    `x_user_id`, `x_model`, `x_platform`), not a bearer token
    CustomEndpointConfig's `headers` dict couldn't also handle the
    stream-reassembly problem above even if it could carry these headers.
  - The request body has a specific nested shape (botId, sessionId,
    userPseudoId, hubxId, message: {prompt, messageId}, actions: {...})
    that isn't the generic {task_field: task} shape.

Credentials come from environment variables (loaded via python-dotenv, same
pattern as the rest of this project's .env usage) -- never hardcoded here.

IMPORTANT -- token lifetime: chatbotapp.ai's x_token is a Firebase ID token
and is SHORT-LIVED (observed ~1 hour). If you get 401/403 errors partway
through a long EvalMind session, the token has expired -- re-grab it from
your browser's DevTools Network tab (log into https://chat.chatbotapp.ai,
send a message, copy the `x_token` header off the /api/v2/chat request) and
update CHATBOTAPP_X_TOKEN in your .env. There is no refresh-token flow
wired up here; for a long-running session you may need to re-run with a
fresh token.

SETUP:
  1. Add these to your .env (see .env.example for the pattern):
       CHATBOTAPP_X_TOKEN=<the x_token header value from DevTools>
       CHATBOTAPP_X_USER_ID=<the x_user_id header value>
       CHATBOTAPP_HUBX_ID=<the hubxId field value from the request body>
       CHATBOTAPP_USER_PSEUDO_ID=<the userPseudoId field value from the request body>
       CHATBOTAPP_BOT_ID=120

  2. FIRST: run this file directly with debug mode on to inspect the real
     SSE event shape before trusting the text-extraction logic below --
     it's a best-guess based on common SSE chat API conventions, not
     confirmed against a real chatbotapp.ai response:
       python aut/chatbotapp_wrapper.py "hi" --debug

     This prints every raw SSE line so you can see the actual field names
     chatbotapp.ai uses for the streamed text chunks, then adjust
     _extract_text_from_event() below to match.

  3. Once _extract_text_from_event() is confirmed correct, wire it in:
       from aut.connector import FunctionImportConfig
       from aut.chatbotapp_wrapper import call_chatbotapp
       aut_config = FunctionImportConfig(function=call_chatbotapp)
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

CHATBOTAPP_URL = "https://api.chatbotapp.ai/api/v2/chat"


class ChatbotAppConfigError(RuntimeError):
    """Raised when a required CHATBOTAPP_* env var is missing."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ChatbotAppConfigError(
            f"{name} is not set. Add it to your .env -- see this file's module "
            f"docstring for the full list of required CHATBOTAPP_* variables."
        )
    return value


def _build_headers() -> dict[str, str]:
    return {
        "accept": "text/event-stream",
        "content-type": "application/json",
        "origin": "https://chat.chatbotapp.ai",
        "referer": "https://chat.chatbotapp.ai/",
        "x_model": os.getenv("CHATBOTAPP_BOT_ID", "120"),
        "x_platform": "web",
        "x_token": _required_env("CHATBOTAPP_X_TOKEN"),
        "x_user_id": _required_env("CHATBOTAPP_X_USER_ID"),
    }


def _build_payload(task: str) -> dict[str, Any]:
    return {
        "botId": int(os.getenv("CHATBOTAPP_BOT_ID", "120")),
        # A fresh sessionId per call keeps each EvalMind probe/round
        # independent (no leaked context between adversarial security
        # probes and functionality probes) -- mirrors the connector.py
        # SocketIOEndpointConfig default of persist_thread=False, and the
        # README's own reasoning for why that's usually what an evaluator
        # wants.
        "sessionId": uuid.uuid4().hex[:20],
        "userPseudoId": _required_env("CHATBOTAPP_USER_PSEUDO_ID"),
        "hubxId": _required_env("CHATBOTAPP_HUBX_ID"),
        "message": {
            "prompt": task,
            # Must be unique per call -- reusing a messageId risks the
            # backend treating a later call as a duplicate/update of an
            # earlier one instead of a new message.
            "messageId": str(uuid.uuid4()),
        },
        "actions": {
            "webSearch": False,
            "createImage": False,
            "deepSearch": False,
            "privateSearch": False,
        },
    }


def _extract_text_from_event(data: dict) -> Optional[str]:
    """Best-guess text extraction from one parsed SSE `data: {...}` JSON
    event. NOT yet confirmed against a real chatbotapp.ai response -- run
    this module's __main__ block with --debug first and adjust the key
    names here to match what you actually see.

    Tries several common streaming-chat-API field name conventions.
    """
    for key in ("text", "content", "delta", "token", "chunk"):
        value = data.get(key)
        if isinstance(value, str):
            return value

    # OpenAI-style choices[0].delta.content
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content

    # Nested under a "message" key
    message = data.get("message")
    if isinstance(message, dict):
        for key in ("text", "content", "prompt"):
            value = message.get(key)
            if isinstance(value, str):
                return value

    return None


def call_chatbotapp(task: str, *, debug: bool = False, timeout_seconds: float = 60.0) -> str:
    """function_import target for aut.connector.FunctionImportConfig.

    Sends `task` as the chat prompt, reassembles the SSE stream into one
    plain-text output string. Raises requests.HTTPError on a non-2xx
    response (e.g. a 401 means CHATBOTAPP_X_TOKEN has expired -- see this
    module's docstring on token lifetime).
    """
    headers = _build_headers()
    payload = _build_payload(task)

    response = requests.post(
        CHATBOTAPP_URL,
        headers=headers,
        json=payload,
        stream=True,
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    chunks: list[str] = []
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        if debug:
            print(f"[SSE] {raw_line!r}", file=sys.stderr)
        if not raw_line.startswith("data:"):
            continue

        data_str = raw_line[len("data:"):].strip()
        if data_str in ("", "[DONE]"):
            continue

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            # Not JSON -- treat the raw payload as a plain text chunk
            # rather than silently dropping it.
            chunks.append(data_str)
            continue

        if isinstance(data, dict):
            text = _extract_text_from_event(data)
            if text:
                chunks.append(text)

    output = "".join(chunks)
    if not output and not debug:
        raise RuntimeError(
            "chatbotapp_wrapper: no text extracted from the SSE response. "
            "Re-run with debug=True (or `python aut/chatbotapp_wrapper.py "
            "\"hi\" --debug`) to inspect the raw event shape and fix "
            "_extract_text_from_event()."
        )
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python aut/chatbotapp_wrapper.py "your message" [--debug]')
        sys.exit(1)

    task_arg = sys.argv[1]
    debug_flag = "--debug" in sys.argv[2:]

    result = call_chatbotapp(task_arg, debug=debug_flag)
    print("\n--- Final assembled output ---")
    print(result)
