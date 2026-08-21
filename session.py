"""
session.py

Block F - run_full_session() now runs the Describer FIRST (agents.describer.
describe_aut()) to auto-discover the AUT's capability_description, then
proceeds exactly as Block E did: the escalating loop_runner.run_category_loop()
for all three categories (functionality, security, compliance) under ONE
shared session, collecting their summaries and printing a console report.
This is still the top-level entry point a real evaluation run is expected to
call (kept in its own module rather than folded into pipeline.py - see
pipeline.py's own module docstring for why that boundary matters).

BLOCK G ADDITION: after all three category loops finish, run_full_session()
now makes exactly one more call - aggregator.build_final_report(session_id,
category_summaries=summaries) - which reads every round back out of the DB
(the authoritative source; `summaries` is passed only as a diagnostic
cross-check, see aggregator.py's module docstring), computes each category's
breaking point, aggregates performance/cost across the whole session, adds
one synthesized overall_verdict, and persists the result to the
final_reports table. This keeps the spec's "one function call produces
Describer output, session creation, all three category loops, and the final
report together" property true for run_full_session()'s own callers -
nothing outside this module needs to know the Aggregator step exists.

WHAT CHANGED FROM BLOCK E: capability_description is no longer a required
parameter. By default, run_full_session() calls describe_aut(aut_config)
before doing anything else - before the session row is even created - and
uses its capability_description output everywhere Block E's hardcoded
placeholder used to go, INCLUDING as the session's aut_description in the
DB (so a session row's aut_description always reflects however the
description was actually obtained, auto-discovered or not). An optional
capability_description_override parameter skips the Describer entirely and
uses the given string instead, for tests/debugging - this is what Block D's
and Block E's own tests (tests/test_single_round.py, tests/
test_escalating_loop.py) already rely on via pipeline.run_single_round() /
loop_runner.run_category_loop() directly (neither of those went through
run_full_session() in the first place, so they're unaffected either way),
and it's also what lets tests/test_describer.py isolate "does auto-discovery
work" from "does the escalating loop work" as separate concerns.
"""
import uuid
from typing import Dict, Optional

from pydantic import BaseModel

from aggregator import FinalReport, build_final_report
from agents.describer import describe_aut
from agents.schemas import DescriberResult
from aut.connector import AUTConfig
from db.store import init_db, insert_session
from loop_runner import CategoryLoopResult, run_category_loop
from progress import OnEvent, emit_event

CATEGORIES = ("functionality", "security", "compliance")

_STATUS_LABELS = {
    "broken": "BROKEN",
    "robust_within_tested_range": "ROBUST (within tested range)",
}


class SessionResult(BaseModel):
    """Everything produced by one full evaluation session: all three
    categories' escalating-loop summaries, sharing one session_id.

    describer_result is the full auto-discovery output (self-report,
    observed behavior, mismatch notes, and the final capability_description
    itself) when the Describer actually ran - None when
    capability_description_override was used instead, since there is no
    discovery output to report in that case.
    """

    session_id: str
    capability_description: str
    describer_result: Optional[DescriberResult] = None
    summaries: Dict[str, CategoryLoopResult]
    final_report: FinalReport


def run_full_session(
    aut_config: AUTConfig,
    max_rounds: int = 5,
    capability_description_override: Optional[str] = None,
    on_event: Optional[OnEvent] = None,
) -> SessionResult:
    """
    Run the full EvalMind evaluation: auto-discover the AUT's capability
    description (unless overridden), then an escalating difficulty loop for
    each of functionality/security/compliance, all sharing one session, then
    print a console report of the results (a first draft of the eventual
    final report).

    Args:
        aut_config: one of the four AUTConfig modes (see aut/connector.py).
                    Used for the Describer's two discovery passes AND,
                    unchanged, for every round of every category's loop.
        max_rounds: hard cap on rounds PER CATEGORY - each category gets
                    its own independent escalating loop, each capped at
                    this many rounds. Defaults to 5.
        capability_description_override: if given, SKIPS the Describer
                                          entirely and uses this string as
                                          the capability_description
                                          everywhere instead (still creates
                                          the session, still runs all three
                                          category loops, in the same
                                          "description first, then session,
                                          then loops" order - it's only the
                                          SOURCE of the description that
                                          changes). Intended for tests/
                                          debugging where a fixed, known
                                          description is needed. Must be a
                                          non-empty string if provided.
        on_event: optional progress callback (see progress.py), passed
                  straight through to describe_aut() and every
                  run_category_loop() call (each of which fires its own
                  granular events). This function additionally fires
                  "error" if the Aggregator step fails, and
                  "session_completed" with the final report at the very
                  end. None (the default) is a no-op — existing callers
                  (main.py, scripts/rehearsal.py, every tests/test_*.py
                  file) are unaffected.

    Returns:
        A SessionResult with the shared session_id, the capability
        description actually used, the full DescriberResult (or None if
        capability_description_override was used), a
        {category: CategoryLoopResult} summaries dict for all three
        categories, and the Aggregator's (Block G) FinalReport - built and
        persisted (db.store.insert_final_report) automatically as the last
        step, from the session's DB rows (see aggregator.build_final_report).

    Raises:
        ValueError: if capability_description_override is provided but empty.
        agents.describer.DescriberError: if auto-discovery fails (only
                                          possible when no override is given).
        Any exception loop_runner.run_category_loop() can raise.
        aggregator.AggregatorError: if the final Aggregator step's
                                     summarizing LLM call fails after
                                     retrying (all three category loops
                                     will already have completed and been
                                     persisted by this point either way).
    """
    init_db()

    describer_result: Optional[DescriberResult] = None
    if capability_description_override is not None:
        if not capability_description_override.strip():
            raise ValueError("capability_description_override must be a non-empty string if provided")
        capability_description = capability_description_override
    else:
        # Describer runs BEFORE the session row is created - the session's
        # aut_description is only ever written once the real description is
        # known, auto-discovered or not.
        describer_result = describe_aut(aut_config, on_event=on_event)
        capability_description = describer_result.capability_description

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=capability_description)

    summaries: Dict[str, CategoryLoopResult] = {}
    for category in CATEGORIES:
        summaries[category] = run_category_loop(
            category=category,
            capability_description=capability_description,
            aut_config=aut_config,
            max_rounds=max_rounds,
            session_id=session_id,
            on_event=on_event,
        )

    # Block G: one call builds AND persists the FinalReport, from the DB
    # rows every category loop just wrote - `summaries` is passed only as a
    # diagnostic cross-check, never as the source of report data (see
    # aggregator.build_final_report's docstring).
    try:
        final_report = build_final_report(session_id, category_summaries=summaries)
    except Exception as e:
        emit_event(on_event, "error", {"stage": "aggregator", "message": str(e)})
        raise

    _print_session_report(session_id, capability_description, summaries, final_report, describer_result)

    emit_event(on_event, "session_completed", final_report.model_dump())

    return SessionResult(
        session_id=session_id,
        capability_description=capability_description,
        describer_result=describer_result,
        summaries=summaries,
        final_report=final_report,
    )


# ==========================================================================
# Console report - a first draft of the eventual final report.
# ==========================================================================
def _breaking_point_label(summary: CategoryLoopResult) -> str:
    if summary.breaking_point is None:
        return "none - robust"
    return f"round {summary.breaking_point}"


def _round_line(result) -> str:
    verdict = "PASS" if result.passed else "FAIL"
    return (
        f"    R{result.round_number} (difficulty {result.difficulty}) {verdict:<4} "
        f"tc={result.task_completion:>2} sec={result.security:>2} comp={result.compliance:>2}"
    )


def _print_describer_section(describer_result: DescriberResult, width: int) -> None:
    print("-" * width)
    print("AUTO-DISCOVERY (Describer)")
    print("-" * width)
    print("Self-reported:")
    print(f"  {describer_result.self_reported_summary}")
    print("Observed:")
    print(f"  {describer_result.observed_summary}")
    print("Mismatch notes:")
    print(f"  {describer_result.mismatch_notes or '(none found)'}")
    print()


# --- Block G additions: overall_verdict at the top, performance_and_cost at
# the end - both pulled straight off the FinalReport aggregator.
# build_final_report() already computed, not recomputed here. ---
def _print_overall_verdict_section(final_report: FinalReport, width: int) -> None:
    print("-" * width)
    print("OVERALL VERDICT")
    print("-" * width)
    print(f"  {final_report.overall_verdict}")
    print()


def _print_performance_and_cost_section(final_report: FinalReport, width: int) -> None:
    perf = final_report.performance_and_cost
    print("-" * width)
    print("PERFORMANCE & COST")
    print("-" * width)
    print(f"  Total rounds:         {perf.total_rounds}")
    print(f"  Total latency:        {perf.total_latency_ms} ms   (avg {perf.average_latency_ms} ms/round)")
    if perf.average_tokens_used is not None:
        print(f"  Total tokens used:    {perf.total_tokens_used}   (avg {perf.average_tokens_used}/round)")
    else:
        print(f"  Total tokens used:    {perf.total_tokens_used}   (avg: no token data available)")
    if perf.average_estimated_cost is not None:
        print(f"  Total estimated cost: ${perf.total_estimated_cost}   (avg ${perf.average_estimated_cost}/round)")
    else:
        print(f"  Total estimated cost: ${perf.total_estimated_cost}   (avg: no cost data available)")
    if perf.rounds_missing_token_data:
        print(f"  ({perf.rounds_missing_token_data}/{perf.total_rounds} rounds had no token data)")
    if perf.rounds_missing_cost_data:
        print(f"  ({perf.rounds_missing_cost_data}/{perf.total_rounds} rounds had no cost data)")
    print()


def _print_session_report(
    session_id: str,
    capability_description: str,
    summaries: Dict[str, CategoryLoopResult],
    final_report: FinalReport,
    describer_result: Optional[DescriberResult] = None,
) -> None:
    width = 78
    print("=" * width)
    print("EvalMind - Session Report")
    print("=" * width)
    print(f"session_id: {session_id}")
    print(f"AUT: {capability_description}")
    print()

    if describer_result is not None:
        _print_describer_section(describer_result, width)

    # Block G: overall_verdict goes at the top, ahead of the per-category
    # breakdown - it's the synthesized headline, the per-category sections
    # below are the supporting detail.
    _print_overall_verdict_section(final_report, width)

    for category in CATEGORIES:
        summary = summaries[category]
        label = _STATUS_LABELS.get(summary.status, summary.status.upper())
        print("-" * width)
        print(f"{category.upper():<14} status: {label:<28} breaking point: {_breaking_point_label(summary)}")
        print("-" * width)
        for result in summary.rounds:
            print(_round_line(result))
        print()

    # Block G: performance_and_cost goes at the very end, after every
    # category's breakdown.
    _print_performance_and_cost_section(final_report, width)

    print("=" * width)
    broken = [c for c in CATEGORIES if summaries[c].status == "broken"]
    if broken:
        print(f"Summary: {len(broken)}/3 categories broke within the tested range: {', '.join(broken)}")
    else:
        print("Summary: all 3 categories remained robust within the tested range.")
    print("=" * width)
