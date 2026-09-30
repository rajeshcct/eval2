"""
config/usage.py

Collects EvalMind's OWN LLM usage (the Describer, Generator, Judge and the
Aggregator's verdict call) so the report can show evaluator tokens and cost
alongside the Agent-Under-Test's figures.

Two independent collectors
--------------------------
* ROUND collector -- run_single_round() calls start_collection() at the top of
  a round and collect_usage() just before the round is saved. It catches that
  round's Generator + Judge calls, and is stored on the round row.
* SESSION collector -- for work that belongs to no single round: the Describer
  (once, before the rounds), the Aggregator's overall-verdict call (once,
  after), and a re-judge. Callers use start_session_collection() /
  collect_session_usage() and persist the result with
  db.store.add_session_eval_usage(), which ADDS to whatever is already stored.

A recording goes to the round collector if one is active, otherwise to the
session collector if one is active, otherwise it is dropped -- so nothing is
counted twice.

Recording happens right after the LLM call returns, BEFORE the output is
parsed, so a call whose output failed validation and was retried is still
counted (it still cost money). Nothing here raises: usage tracking must never
break an evaluation. Anything the provider did not report is None, never a
guessed 0.

Cost is tokens x the model's price from LiteLLM's price table (CrewAI runs on
LiteLLM, and CrewAI itself never computes cost). A model missing from that
table is left unpriced rather than given a made-up figure.
"""
from __future__ import annotations

import contextvars
from typing import Any, Optional

_round_collector: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "evalmind_round_usage_collector", default=None
)
_session_collector: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "evalmind_session_usage_collector", default=None
)


def start_collection() -> None:
    """Begin collecting usage for the current ROUND (resets any previous one)."""
    _round_collector.set([])


def start_session_collection() -> None:
    """Begin collecting usage for work outside any round (resets any previous)."""
    _session_collector.set([])


def _active_calls() -> Optional[list]:
    calls = _round_collector.get()
    return calls if calls is not None else _session_collector.get()


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cost_for(model: Optional[str], prompt: int, completion: int) -> Optional[float]:
    if not model or (prompt <= 0 and completion <= 0):
        return None
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=prompt, completion_tokens=completion
        )
        return float(prompt_cost) + float(completion_cost)
    except Exception:  # noqa: BLE001 - unknown model / litellm change: report "unknown"
        return None


def _append(calls: list, role: str, prompt: int, completion: int, total: int, model: Optional[str]) -> None:
    total = total or (prompt + completion)
    if total <= 0:
        return
    calls.append(
        {
            "role": role,
            "total": total,
            "prompt": prompt,
            "completion": completion,
            "cost": _cost_for(model, prompt, completion),
        }
    )


def record_crew_usage(crew_output: Any, crew: Any = None, agent: Any = None, role: str = "") -> None:
    """Record the token usage of one crew.kickoff() call. No-op when no
    collection is active or the provider reported nothing."""
    calls = _active_calls()
    if calls is None:
        return
    try:
        usage = getattr(crew_output, "token_usage", None)
        if usage is None and crew is not None:
            usage = getattr(crew, "usage_metrics", None)
        if usage is None:
            return
        model = getattr(getattr(agent, "llm", None), "model", None)
        _append(
            calls,
            role,
            _int(getattr(usage, "prompt_tokens", 0)),
            _int(getattr(usage, "completion_tokens", 0)),
            _int(getattr(usage, "total_tokens", 0)),
            model,
        )
    except Exception:  # noqa: BLE001 - never let usage tracking break a run
        return


def snapshot_llm_usage(llm: Any) -> tuple[int, int, int]:
    """Lifetime (prompt, completion, total) tokens of a crewai LLM instance.
    get_llm() caches instances, so these are cumulative -- take a snapshot
    before a call and pass it to record_llm_usage() after it."""
    try:
        u = llm.get_token_usage_summary()
        return (
            _int(getattr(u, "prompt_tokens", 0)),
            _int(getattr(u, "completion_tokens", 0)),
            _int(getattr(u, "total_tokens", 0)),
        )
    except Exception:  # noqa: BLE001
        return (0, 0, 0)


def record_llm_usage(llm: Any, before: tuple[int, int, int], role: str = "") -> None:
    """Record the tokens a direct llm.call() used: usage now minus `before`."""
    calls = _active_calls()
    if calls is None:
        return
    try:
        after = snapshot_llm_usage(llm)
        _append(
            calls,
            role,
            max(after[0] - before[0], 0),
            max(after[1] - before[1], 0),
            max(after[2] - before[2], 0),
            getattr(llm, "model", None),
        )
    except Exception:  # noqa: BLE001
        return


def _summarize(calls: list) -> dict[str, Any]:
    if not calls:
        return {
            "tokens": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_known": None,
            "cost_unknown": False,
        }
    priced = [c["cost"] for c in calls if c["cost"] is not None]
    return {
        "tokens": sum(c["total"] for c in calls),
        "prompt_tokens": sum(c["prompt"] for c in calls),
        "completion_tokens": sum(c["completion"] for c in calls),
        "cost_known": round(sum(priced), 6) if priced else None,
        "cost_unknown": len(priced) < len(calls),
    }


def collect_usage() -> dict[str, Optional[float]]:
    """Return the summed usage for the ROUND and stop collecting.

    Keys: tokens, prompt_tokens, completion_tokens, cost -- each None when
    nothing was reported. cost is None unless EVERY recorded call could be
    priced (a partial sum would silently understate the spend)."""
    s = _summarize(_round_collector.get() or [])
    _round_collector.set(None)
    return {
        "tokens": s["tokens"],
        "prompt_tokens": s["prompt_tokens"],
        "completion_tokens": s["completion_tokens"],
        "cost": None if s["cost_unknown"] else s["cost_known"],
    }


def collect_session_usage() -> dict[str, Any]:
    """Return the summed SESSION-level usage and stop collecting.

    Keys: tokens, prompt_tokens, completion_tokens, cost (sum of the calls
    that could be priced) and cost_unknown (True when at least one call could
    not be). tokens is None when nothing was reported."""
    s = _summarize(_session_collector.get() or [])
    _session_collector.set(None)
    return {
        "tokens": s["tokens"],
        "prompt_tokens": s["prompt_tokens"],
        "completion_tokens": s["completion_tokens"],
        "cost": s["cost_known"],
        "cost_unknown": s["cost_unknown"],
    }
