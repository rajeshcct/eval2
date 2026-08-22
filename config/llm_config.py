"""
config/llm_config.py

Single source of truth for "which LLM do EvalMind's CrewAI agents use".

Every agent (Describer, Generator, Judge) calls `get_llm()` from this module
instead of constructing its own `crewai.LLM`. That means:
  - Swapping LLMs is a one-line change in `.env`
    (LLM_PROVIDER=openai | anthropic | groq), never a code change.
  - Dropping in a real API key at hackathon time is a `.env` edit only.
  - No API key is ever hardcoded anywhere in the codebase.

No API call is made at import time — the key is only required when
`get_llm()` is actually invoked (e.g. when a Crew kicks off), so the rest
of the project (DB layer, agent stubs, main.py wiring) can be imported and
tested with zero API key configured, which is exactly the situation during
early development before a real key exists.
"""
import os
from functools import lru_cache
from dotenv import load_dotenv
from crewai import LLM

load_dotenv()  # reads .env in the project root (no-op if the file doesn't exist)

SUPPORTED_PROVIDERS = ("openai", "anthropic", "groq", "gemini")


class MissingAPIKeyError(RuntimeError):
    """Raised when get_llm() is called but no key is configured for the selected provider."""


def _get_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM_PROVIDER='{provider}' in .env. "
            f"Supported values: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return provider


# Roles that support a per-role model override. Each maps to an env var
# named f"{PROVIDER}_MODEL_{ROLE}" (e.g. OPENAI_MODEL_JUDGE), checked before
# falling back to the provider's plain f"{PROVIDER}_MODEL" default. This
# lets Describer/Generator/Judge each run on a different model — e.g.
# a cheap model for the Describer's light extraction, a stronger creative
# model for the Generator's adversarial task-writing, a mid-tier model for
# the Judge's rubric-following scoring — without touching any agent code
# beyond the get_llm(role=...) call site.
VALID_ROLES = ("describer", "generator", "judge")

_PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-3.5-flash",
}

# model string prefixes crewai/litellm needs to route to the right native
# provider. openai has none — its models are unprefixed.
_PROVIDER_MODEL_PREFIX = {
    "openai": "",
    "anthropic": "anthropic/",
    "groq": "groq/",
    "gemini": "gemini/",
}


def _resolve_model(provider: str, role: str | None) -> str:
    """Role-specific env var (e.g. OPENAI_MODEL_JUDGE) wins if set and
    non-empty; otherwise fall back to the provider's plain *_MODEL var;
    otherwise fall back to the hardcoded default for that provider."""
    provider_upper = provider.upper()
    if role:
        role_specific = os.getenv(f"{provider_upper}_MODEL_{role.upper()}", "").strip()
        if role_specific:
            return role_specific
    return os.getenv(f"{provider_upper}_MODEL", _PROVIDER_DEFAULT_MODELS[provider]).strip()


@lru_cache(maxsize=None)
def get_llm(provider: str | None = None, temperature: float | None = None, role: str | None = None) -> LLM:
    """
    Build (and cache) a crewai.LLM configured from .env.

    Args:
        provider: optional override ("openai", "anthropic", "groq", or
                  "gemini"). If omitted, reads LLM_PROVIDER from .env
                  (defaults to "openai").
        temperature: optional per-call override (e.g. a low, stable value for
                     an evaluator agent like the Judge). If omitted, the
                     provider's own default temperature is used.
        role: optional one of "describer" | "generator" | "judge". When set,
              the model is looked up from f"{PROVIDER}_MODEL_{ROLE}" first
              (e.g. OPENAI_MODEL_JUDGE), falling back to the provider's
              plain *_MODEL var if that's unset — so a role only needs its
              own .env line when you actually want it on a different model
              than the rest. (provider, temperature, role) triples are
              cached separately, so e.g. the Judge and Describer can each
              get their own LLM instance without either one mutating a
              shared object.

    Raises:
        ValueError: if role is given but isn't one of VALID_ROLES.
        MissingAPIKeyError: if the relevant *_API_KEY is not set in .env.
                             This is the expected error today, since no real
                             key has been configured yet — set one in .env
                             when you're ready to actually run a Crew.
    """
    provider = (provider or _get_provider()).strip().lower()
    if role is not None and role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES} or None, got {role!r}")

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    api_key = os.getenv(f"{provider.upper()}_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKeyError(
            f"LLM_PROVIDER is '{provider}' but {provider.upper()}_API_KEY is empty in .env. "
            "Copy .env.example to .env and set a real key."
        )

    model = _resolve_model(provider, role)
    prefix = _PROVIDER_MODEL_PREFIX[provider]
    kwargs = {"model": f"{prefix}{model}" if prefix else model, "api_key": api_key}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return LLM(**kwargs)


def is_configured() -> bool:
    """True if the currently-selected provider has a non-empty API key set. Never raises."""
    try:
        get_llm()
        return True
    except MissingAPIKeyError:
        return False
