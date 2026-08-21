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


@lru_cache(maxsize=None)
def get_llm(provider: str | None = None, temperature: float | None = None) -> LLM:
    """
    Build (and cache) a crewai.LLM configured from .env.

    Args:
        provider: optional override ("openai", "anthropic", or "groq"). If omitted,
                  reads LLM_PROVIDER from .env (defaults to "openai").
        temperature: optional per-call override (e.g. a low, stable value for
                     an evaluator agent like the Judge). If omitted, the
                     provider's own default temperature is used. Different
                     (provider, temperature) pairs are cached separately, so
                     e.g. the Judge and Describer can each get their own LLM
                     instance without either one mutating a shared object.

    Raises:
        MissingAPIKeyError: if the relevant *_API_KEY is not set in .env.
                             This is the expected error today, since no real
                             key has been configured yet — set one in .env
                             when you're ready to actually run a Crew.
    """
    provider = (provider or _get_provider()).strip().lower()

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        if not api_key:
            raise MissingAPIKeyError(
                "LLM_PROVIDER is 'openai' but OPENAI_API_KEY is empty in .env. "
                "Copy .env.example to .env and set a real key."
            )
        kwargs = {"model": model, "api_key": api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LLM(**kwargs)

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()
        if not api_key:
            raise MissingAPIKeyError(
                "LLM_PROVIDER is 'anthropic' but ANTHROPIC_API_KEY is empty in .env. "
                "Copy .env.example to .env and set a real key."
            )
        # model string is prefixed so crewai routes to the native Anthropic provider
        kwargs = {"model": f"anthropic/{model}", "api_key": api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LLM(**kwargs)

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        if not api_key:
            raise MissingAPIKeyError(
                "LLM_PROVIDER is 'groq' but GROQ_API_KEY is empty in .env. "
                "Copy .env.example to .env and set a real key."
            )
        kwargs = {"model": f"groq/{model}", "api_key": api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LLM(**kwargs)

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
        if not api_key:
            raise MissingAPIKeyError(
                "LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is empty in .env. "
                "Copy .env.example to .env and set a real key."
            )
        kwargs = {"model": f"gemini/{model}", "api_key": api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return LLM(**kwargs)

    raise ValueError(f"Unsupported provider: {provider}")


def is_configured() -> bool:
    """True if the currently-selected provider has a non-empty API key set. Never raises."""
    try:
        get_llm()
        return True
    except MissingAPIKeyError:
        return False
