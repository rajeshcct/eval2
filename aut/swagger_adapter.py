"""
aut/swagger_adapter.py

Swagger / OpenAPI 3.x auto-discovery for the "swagger" AUT connection mode.

Given:
  - An endpoint URL (e.g. https://api.example.com/v1/chat/completions)
  - A Swagger/OpenAPI spec URL (e.g. https://api.example.com/openapi.json)
  - Optional bearer token / extra headers

This module:
  1. Fetches and parses the OpenAPI spec (JSON or YAML).
  2. Finds the matching path + POST operation.
  3. Extracts the requestBody JSON schema.
  4. Identifies which schema field should receive the user's chat message —
     first by heuristic name matching (message, prompt, query, text, content,
     input, user_message, user_input, question, utterance …), then by LLM
     judgment if that fails.
  5. Returns a SwaggerDiscoveryResult that carries:
       - the discovered payload template as a Python dict (task field = sentinel)
       - a build_payload(task: str) → dict callable ready to hand to the
         connector layer

The connector never needs to know about Swagger internals — it just calls
build_payload(task) to get the correctly shaped body for any API.

Error handling:
  - SwaggerFetchError   : could not fetch / parse the spec
  - SwaggerMatchError   : no path in the spec matches the given endpoint URL
  - SwaggerSchemaError  : the matched operation has no usable requestBody schema
  - SwaggerFieldError   : could not identify which field carries the chat message
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests


# ==========================================================================
# Errors — one exception class per failure mode so callers can handle them
# selectively rather than catching a broad RuntimeError and pattern-matching
# the message string.
# ==========================================================================
class SwaggerAdapterError(RuntimeError):
    """Base class for all aut/swagger_adapter.py errors."""


class SwaggerFetchError(SwaggerAdapterError):
    """Could not fetch or parse the OpenAPI spec."""


class SwaggerMatchError(SwaggerAdapterError):
    """No path in the spec matches the given endpoint URL."""


class SwaggerSchemaError(SwaggerAdapterError):
    """The matched operation has no usable requestBody schema."""


class SwaggerFieldError(SwaggerAdapterError):
    """Could not identify which field carries the chat message."""


# ==========================================================================
# Heuristics — tried before an LLM call to keep discovery fast and free.
# ==========================================================================

# Ordered list of field-name patterns most APIs use for the user message.
# Checked as exact lowercase matches first, then as substrings.
_MESSAGE_FIELD_CANDIDATES: list[str] = [
    "message",
    "prompt",
    "query",
    "text",
    "content",
    "input",
    "user_message",
    "user_input",
    "question",
    "utterance",
    "msg",
    "user_query",
    "request",
    "chat",
    "ask",
]


def _identify_message_field_heuristic(schema_properties: dict[str, Any]) -> Optional[str]:
    """Return the property name most likely to carry the user's chat message,
    using name-matching heuristics only.  Returns None if no confident match."""
    lower_props = {k.lower(): k for k in schema_properties}

    # 1. Exact match (case-insensitive).
    for candidate in _MESSAGE_FIELD_CANDIDATES:
        if candidate in lower_props:
            return lower_props[candidate]

    # 2. Substring match (e.g. "userMessage" or "chat_prompt").
    for candidate in _MESSAGE_FIELD_CANDIDATES:
        for lk, orig_k in lower_props.items():
            if candidate in lk:
                return orig_k

    return None


def _identify_message_field_llm(
    schema_properties: dict[str, Any],
    endpoint_url: str,
) -> str:
    """Ask the configured LLM to pick the message field from a list of
    property names.  Used only when heuristics fail.

    Raises SwaggerFieldError if the LLM gives an answer that doesn't match
    any property name in the schema.
    """
    from crewai import LLM  # local import — keeps crewai optional for tests
    from config.llm_config import get_llm  # uses EvalMind's own LLM config

    prop_list = "\n".join(
        f"  - {name}: {desc.get('type', '?')} — {desc.get('description', '(no description)')}"
        for name, desc in schema_properties.items()
    )

    prompt = f"""You are helping identify which JSON field in an API request body carries
the user's chat message (the text the user typed).

Endpoint: {endpoint_url}

Request body properties:
{prop_list}

Which ONE property name should receive the user's chat message text?
Reply with ONLY the exact property name, nothing else."""

    llm = get_llm()
    try:
        answer = llm.call(messages=[{"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001
        raise SwaggerFieldError(
            f"LLM call to identify message field failed: {e}"
        ) from e

    if not isinstance(answer, str):
        answer = str(answer)
    answer = answer.strip().strip('"').strip("'")

    # Exact match first, then case-insensitive.
    if answer in schema_properties:
        return answer
    for prop in schema_properties:
        if prop.lower() == answer.lower():
            return prop

    raise SwaggerFieldError(
        f"LLM suggested field name {answer!r} but it is not in the schema. "
        f"Known properties: {list(schema_properties.keys())}"
    )


# ==========================================================================
# Spec fetching + parsing
# ==========================================================================

def _fetch_spec(spec_url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Fetch and parse an OpenAPI spec from a URL. Accepts JSON or YAML."""
    try:
        resp = requests.get(spec_url, headers=headers, timeout=15)
    except requests.RequestException as e:
        raise SwaggerFetchError(f"Could not fetch spec from '{spec_url}': {e}") from e

    if not resp.ok:
        raise SwaggerFetchError(
            f"Spec URL '{spec_url}' returned HTTP {resp.status_code}: {resp.text[:300]!r}"
        )

    content_type = resp.headers.get("Content-Type", "")
    text = resp.text.strip()

    # Try JSON first regardless of Content-Type (some servers send YAML with
    # application/json; some send JSON with text/plain).
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try YAML — import lazily so pyyaml is optional if the caller never hits
    # a YAML spec.
    try:
        import yaml  # type: ignore[import]
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            return parsed
        raise SwaggerFetchError(
            f"Spec from '{spec_url}' parsed as YAML but top level is a "
            f"{type(parsed).__name__}, expected a dict."
        )
    except ImportError:
        raise SwaggerFetchError(
            "The spec at '{spec_url}' is YAML but PyYAML is not installed. "
            "Run: pip install pyyaml"
        ) from None
    except Exception as e:  # noqa: BLE001 — yaml.YAMLError or similar
        raise SwaggerFetchError(
            f"Spec from '{spec_url}' is neither valid JSON nor valid YAML: {e}"
        ) from e


def _match_path(spec: dict[str, Any], endpoint_url: str) -> tuple[str, dict[str, Any]]:
    """Find the spec path entry that matches endpoint_url.

    Returns (matched_path_string, path_item_dict).

    Matching strategy (most-specific first):
      1. The endpoint URL's path matches a spec path exactly.
      2. The endpoint URL's path matches a spec path when path-parameter
         segments ({param}) are replaced by wildcards.
      3. The spec path is a suffix of the endpoint URL's path.
    """
    parsed = urlparse(endpoint_url)
    url_path = parsed.path.rstrip("/") or "/"

    paths: dict[str, Any] = spec.get("paths", {})
    if not paths:
        raise SwaggerMatchError(
            f"OpenAPI spec has no 'paths' section — cannot match '{endpoint_url}'."
        )

    # 1. Exact match.
    if url_path in paths:
        return url_path, paths[url_path]

    # 2. Template match — replace {param} segments with regex groups.
    for spec_path, path_item in paths.items():
        pattern = re.sub(r"\{[^}]+\}", "[^/]+", spec_path)
        pattern = f"^{pattern}$"
        if re.match(pattern, url_path):
            return spec_path, path_item

    # 3. Suffix match (endpoint URL contains extra base path prefix the spec
    #    omits, e.g. /v1/chat vs. spec path /chat).
    for spec_path, path_item in paths.items():
        if url_path.endswith(spec_path.rstrip("/")):
            return spec_path, path_item

    raise SwaggerMatchError(
        f"No path in the OpenAPI spec matches the endpoint '{url_path}'. "
        f"Available paths: {list(paths.keys())[:10]}"
    )


def _extract_schema_properties(
    spec: dict[str, Any],
    path_item: dict[str, Any],
    spec_path: str,
) -> dict[str, Any]:
    """Extract the JSON schema properties from the POST operation's requestBody.

    Handles:
      - requestBody.content["application/json"].schema.properties
      - Inline $ref resolution (one level deep — nested $ref chains are unusual
        for simple chat APIs and kept out of scope to avoid over-engineering).

    Raises SwaggerSchemaError if no usable schema is found.
    """
    post_op = path_item.get("post")
    if post_op is None:
        # Fall back to any HTTP method that has a requestBody.
        for method in ("put", "patch", "get"):
            op = path_item.get(method)
            if op and op.get("requestBody"):
                post_op = op
                break
        if post_op is None:
            raise SwaggerSchemaError(
                f"No POST (or PUT/PATCH) operation found at spec path '{spec_path}'."
            )

    request_body = post_op.get("requestBody", {})
    content = request_body.get("content", {})

    # Prefer application/json; fall back to any content type.
    schema: Optional[dict[str, Any]] = None
    for ct in ("application/json", "application/x-www-form-urlencoded", "*/*"):
        ct_obj = content.get(ct, {})
        schema = ct_obj.get("schema")
        if schema:
            break
    if schema is None and content:
        schema = next(iter(content.values()), {}).get("schema")

    if not schema:
        raise SwaggerSchemaError(
            f"No requestBody schema found for the operation at '{spec_path}'."
        )

    # Resolve a top-level $ref (e.g. #/components/schemas/ChatRequest).
    if "$ref" in schema:
        ref = schema["$ref"]
        schema = _resolve_ref(spec, ref)

    properties = schema.get("properties")
    if not properties:
        raise SwaggerSchemaError(
            f"The requestBody schema at '{spec_path}' has no 'properties' — "
            f"cannot identify individual fields. Schema: {schema!r}"
        )

    return properties


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a JSON $ref string within the same spec document.
    Only handles local refs (starting with '#/'). One level of resolution only.
    """
    if not ref.startswith("#/"):
        raise SwaggerSchemaError(
            f"External $ref '{ref}' is not supported — only local refs (#/…) are resolved."
        )
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise SwaggerSchemaError(
                f"$ref '{ref}' could not be resolved in the spec — missing key '{part}'."
            )
        node = node[part]
    if not isinstance(node, dict):
        raise SwaggerSchemaError(f"$ref '{ref}' resolved to a non-dict: {node!r}")
    return node


# ==========================================================================
# Public entry point
# ==========================================================================

@dataclass
class SwaggerDiscoveryResult:
    """What discover_swagger_config() returns.

    Attributes:
        message_field: the property name that carries the user's chat message
                       (e.g. "message", "prompt", "query").
        static_fields: all other required/defaultable fields with their default
                       or zero values, so the payload is always valid.
        extra_headers: any extra HTTP headers that should be sent with every
                       AUT call (e.g. Authorization from a bearer token).
        build_payload: a callable that takes (task: str) and returns the full
                       JSON-serialisable request body dict — ready to pass to
                       requests.post(json=…).
    """
    message_field: str
    static_fields: dict[str, Any]
    extra_headers: dict[str, str]
    schema_summary: str  # human-readable summary for logging / UI feedback
    _build: Callable[[str], dict[str, Any]] = field(repr=False, compare=False)

    def build_payload(self, task: str) -> dict[str, Any]:
        """Return the full request body dict with `task` substituted into the
        message field and all static fields filled in."""
        return self._build(task)


def discover_swagger_config(
    endpoint_url: str,
    spec_url: str,
    bearer_token: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> SwaggerDiscoveryResult:
    """Auto-discover the correct request payload structure for a chat API
    endpoint by reading its OpenAPI/Swagger spec.

    Args:
        endpoint_url:  The actual API endpoint URL EvalMind will POST to
                       (e.g. https://api.example.com/v1/chat).
        spec_url:      URL of the OpenAPI/Swagger spec document
                       (e.g. https://api.example.com/openapi.json or
                        https://api.example.com/swagger.yaml).
        bearer_token:  Optional Authorization bearer token used both to
                       fetch the spec (if it's protected) and as the
                       Authorization header on every subsequent AUT call.
        extra_headers: Any additional headers to send on every AUT call
                       (merged with/after the bearer_token header, if any).

    Returns:
        SwaggerDiscoveryResult with a ready-to-call build_payload() method.

    Raises:
        SwaggerFetchError:  spec could not be fetched / parsed.
        SwaggerMatchError:  endpoint URL not found in the spec.
        SwaggerSchemaError: no usable requestBody schema on the matched op.
        SwaggerFieldError:  could not identify the message field.
    """
    # Build the headers used to fetch the spec (bearer token if given).
    fetch_headers: dict[str, str] = {}
    if bearer_token:
        fetch_headers["Authorization"] = f"Bearer {bearer_token}"
    if extra_headers:
        fetch_headers.update(extra_headers)

    # --- Step 1: fetch and parse the spec ---
    spec = _fetch_spec(spec_url, headers=fetch_headers if fetch_headers else None)

    # --- Step 2: match the endpoint URL to a spec path ---
    spec_path, path_item = _match_path(spec, endpoint_url)

    # --- Step 3: extract requestBody schema properties ---
    properties = _extract_schema_properties(spec, path_item, spec_path)

    # --- Step 4: identify the message field ---
    message_field = _identify_message_field_heuristic(properties)
    if message_field is None:
        # Heuristic failed — fall back to LLM judgment.
        message_field = _identify_message_field_llm(properties, endpoint_url)

    # --- Step 5: build static defaults for all non-message fields ---
    # Required fields get a type-appropriate zero value; optional ones are
    # omitted (the API should handle their absence gracefully).
    required_fields: list[str] = (
        spec.get("paths", {})
        .get(spec_path, {})
        .get("post", {})
        .get("requestBody", {})
        .get("required", [])
    ) or []

    # Also check schema-level required array (OpenAPI 3.x puts it there).
    post_op = path_item.get("post") or {}
    rb = post_op.get("requestBody", {})
    for ct_obj in rb.get("content", {}).values():
        schema = ct_obj.get("schema", {})
        if "$ref" in schema:
            schema = _resolve_ref(spec, schema["$ref"])
        required_fields = required_fields or schema.get("required", [])

    static_fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if prop_name == message_field:
            continue
        if prop_name not in required_fields:
            continue
        prop_type = prop_schema.get("type", "string")
        if prop_type == "string":
            static_fields[prop_name] = prop_schema.get("default", "")
        elif prop_type in ("integer", "number"):
            static_fields[prop_name] = prop_schema.get("default", 0)
        elif prop_type == "boolean":
            static_fields[prop_name] = prop_schema.get("default", False)
        elif prop_type == "array":
            static_fields[prop_name] = []
        elif prop_type == "object":
            static_fields[prop_name] = {}
        else:
            static_fields[prop_name] = None

    # --- Step 6: build the result ---
    call_headers: dict[str, str] = {}
    if bearer_token:
        call_headers["Authorization"] = f"Bearer {bearer_token}"
    if extra_headers:
        call_headers.update(extra_headers)

    captured_message_field = message_field  # closure capture
    captured_static = dict(static_fields)

    def _build(task: str) -> dict[str, Any]:
        return {captured_message_field: task, **captured_static}

    prop_names = list(properties.keys())
    schema_summary = (
        f"Matched spec path '{spec_path}' — requestBody has "
        f"{len(prop_names)} field(s): {prop_names}. "
        f"Message field identified as '{message_field}'."
    )

    return SwaggerDiscoveryResult(
        message_field=message_field,
        static_fields=static_fields,
        extra_headers=call_headers,
        schema_summary=schema_summary,
        _build=_build,
    )
