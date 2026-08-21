"""
progress.py

Shared ProgressEvent contract for the optional live-progress callbacks
threaded through the pipeline (agents.describer.describe_aut,
pipeline.run_single_round, loop_runner.run_category_loop,
session.run_full_session).

Every function that accepts an `on_event` callback fires events through
emit_event() below rather than calling on_event(...) directly, so a broken
or slow callback (e.g. a dropped websocket on the caller's side) can never
crash or hang a real evaluation run in progress. `on_event=None` (the
default everywhere it's threaded through) is a complete no-op — every
existing call site (main.py, scripts/rehearsal.py, every tests/test_*.py
file) is unaffected.

Event types and their `data` payload:
    describer_started    -- {}
    describer_completed  -- DescriberResult.model_dump()
    category_started     -- {"category": str}
    round_started         -- {"category": str, "round_number": int, "difficulty": int}
    round_completed       -- RoundResult.model_dump()
    category_completed    -- CategoryLoopResult.model_dump()
    session_completed     -- FinalReport.model_dump()
    error                  -- {"stage": str, "message": str}
"""
from typing import Any, Callable, Dict, Optional, TypedDict


class ProgressEvent(TypedDict):
    type: str
    data: Dict[str, Any]


OnEvent = Callable[[ProgressEvent], None]

EVENT_TYPES = (
    "describer_started",
    "describer_completed",
    "category_started",
    "round_started",
    "round_completed",
    "category_completed",
    "session_completed",
    "error",
)


def emit_event(on_event: Optional[OnEvent], event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Fire one ProgressEvent through on_event, if given.

    Never raises — a broken callback must never interrupt or crash a real
    evaluation run. Any exception the callback itself raises is caught and
    logged, not propagated.
    """
    if on_event is None:
        return
    try:
        on_event({"type": event_type, "data": data or {}})
    except Exception as e:  # noqa: BLE001 - intentionally broad; see docstring
        print(f"  [progress] on_event callback raised, ignoring: {e}")
