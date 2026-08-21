"""
tests/test_aggregator.py

Test script for Block G's Aggregator:
  - aggregator.build_final_report() - reads a session's rounds back out of
    the DB and builds the complete FinalReport (per-category breaking
    points + summaries + round history, session-wide performance/cost,
    one synthesized overall_verdict)
  - session.py's run_full_session() wired to call build_final_report()
    automatically as its last step (Block G's wiring requirement)
  - db.store's final_reports table (insert_final_report / the implicit
    reload path)

Same reasoning as tests/test_escalating_loop.py and tests/test_describer.py
applies to the category loops here: pipeline.generate_task and
pipeline.judge_round are monkeypatched to small deterministic stand-ins
(no LLM call, exact [[PASS]]/[[FAIL]] markers looked up from manual-mode
recordings) so this script can make EXACT assertions about breaking points,
round counts, and aggregated numbers instead of eyeballing free-form LLM
output. Unlike those two scripts, build_final_report() DOES need a real LLM
call for its own summarizing overall_verdict (see aggregator.py's module
docstring on why that call isn't monkeypatched away) - so, like tests/
test_describer.py, this whole script is skipped (not failed) if no LLM key
is configured for EvalMind's own agents (config.llm_config.is_configured()).

This test deliberately uses its OWN manual-mode fixture,
tests/sample_manual_outputs_aggregator.json, rather than reusing tests/
sample_manual_outputs.json - see that file's own "_comment" entry for why
(that file's security::diff2 is hardcoded to FAIL for tests/
test_escalating_loop.py's own assertions; this test needs security to break
at round 3 instead, plus several rounds with tokens_used/estimated_cost
intentionally omitted from the fixture, so build_final_report()'s "exclude
None token/cost rows from their averages" logic (spec point 5) actually
gets exercised against real gaps, not synthesized ones).

Two things get checked, per the spec:
  1. Correctness of the per-category and performance_and_cost numbers,
     computed by hand from the fixture and compared against what
     build_final_report() returns.
  2. That a SEPARATE, STANDALONE build_final_report(session_id) call - with
     none of run_full_session()'s in-memory summaries passed in, simulating
     reloading the report in a fresh process sometime later - reconstructs
     the identical category/performance data purely from DB state.

Run from the project root:
    python tests/test_aggregator.py
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_aggregator.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator import build_final_report, print_final_report  # noqa: E402
from agents.judge import compute_passed  # noqa: E402
from agents.schemas import GeneratedTask, JudgeScore  # noqa: E402
from aut.connector import ManualConfig  # noqa: E402
from config.llm_config import is_configured  # noqa: E402
from db.store import get_rounds_for_session, init_db  # noqa: E402
from session import run_full_session  # noqa: E402

SAMPLE_PATH = str(Path(__file__).parent / "sample_manual_outputs_aggregator.json")
CAPABILITY_DESCRIPTION = (
    "This agent is a customer support bot for an online store handling "
    "orders, returns, and sizing questions."
)

# Keep small and fast, same reasoning as tests/test_escalating_loop.py's
# MAX_ROUNDS=3 - the real run uses the default of 5. Security is recorded
# (in the fixture) to PASS rounds 1-2 and FAIL round 3; functionality and
# compliance both PASS all 3 rounds.
MAX_ROUNDS = 3

# --------------------------------------------------------------------------
# Hand-computed expected values from tests/sample_manual_outputs_aggregator.json
# - kept as plain literals here (not re-read from the JSON) so this test
# actually catches a fixture edit that silently changes the expected math,
# rather than blindly re-deriving "expected" from the same file it's
# checking against.
# --------------------------------------------------------------------------
# (category, difficulty) -> (latency_ms, tokens_used or None, estimated_cost or None)
_FIXTURE_ROUNDS = {
    ("security", 1): (500.0, None, 0.00007),
    ("security", 2): (520.0, 50, 0.00008),
    ("security", 3): (610.0, 55, 0.00009),
    ("functionality", 1): (480.0, 35, 0.00005),
    ("functionality", 2): (505.0, 38, None),
    ("functionality", 3): (522.0, 40, 0.00006),
    ("compliance", 1): (500.0, None, None),
    ("compliance", 2): (515.0, 37, 0.00006),
    ("compliance", 3): (530.0, 39, 0.00007),
}

_all_latencies = [v[0] for v in _FIXTURE_ROUNDS.values()]
_all_tokens = [v[1] for v in _FIXTURE_ROUNDS.values() if v[1] is not None]
_all_costs = [v[2] for v in _FIXTURE_ROUNDS.values() if v[2] is not None]

EXPECTED_TOTAL_ROUNDS = len(_FIXTURE_ROUNDS)  # 9
EXPECTED_TOTAL_LATENCY_MS = int(sum(_all_latencies))
EXPECTED_AVG_LATENCY_MS = round(sum(_all_latencies) / len(_all_latencies), 2)
EXPECTED_TOTAL_TOKENS = int(sum(_all_tokens))
EXPECTED_AVG_TOKENS = round(sum(_all_tokens) / len(_all_tokens), 2)
EXPECTED_MISSING_TOKENS = EXPECTED_TOTAL_ROUNDS - len(_all_tokens)
EXPECTED_TOTAL_COST = round(sum(_all_costs), 6)
EXPECTED_AVG_COST = round(sum(_all_costs) / len(_all_costs), 6)
EXPECTED_MISSING_COST = EXPECTED_TOTAL_ROUNDS - len(_all_costs)


# --------------------------------------------------------------------------
# Deterministic stand-ins for the Generator and Judge (see module docstring)
# - identical shape to tests/test_escalating_loop.py's / tests/
# test_describer.py's own fakes, so all three tests' loop behavior is
# consistent.
# --------------------------------------------------------------------------
def _fake_generate_task(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_judge_round(task: str, output: str, category: str) -> JudgeScore:
    if "[[FAIL]]" in output:
        scores = dict(
            task_completion=2, security=3, compliance=3,
            accuracy=5, relevance=5, hallucination=5, safety=5,
        )
        reasoning = "Stubbed FAIL verdict for aggregator test (see module docstring)."
    elif "[[PASS]]" in output:
        scores = dict(
            task_completion=9, security=9, compliance=9,
            accuracy=9, relevance=9, hallucination=9, safety=9,
        )
        reasoning = "Stubbed PASS verdict for aggregator test (see module docstring)."
    else:
        raise AssertionError(
            f"recorded manual output for {task!r} has no [[PASS]]/[[FAIL]] marker: {output!r}"
        )
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning=reasoning)


def main() -> None:
    print("=" * 78)
    print("Block G — Aggregator test")
    print("=" * 78)

    if not is_configured():
        print(
            "  Skipped — no LLM key configured for EvalMind's own agents "
            "(config/llm_config.py). Set LLM_PROVIDER + the matching *_API_KEY "
            "in .env to actually exercise this (build_final_report()'s "
            "overall_verdict needs a real LLM call — see aggregator.py's "
            "module docstring)."
        )
        return

    init_db()
    aut_config = ManualConfig(json_path=SAMPLE_PATH)

    ok = True

    # ----------------------------------------------------------------
    # Run the full pipeline end to end: Describer skipped via override
    # (this test is about the Aggregator, not auto-discovery — see tests/
    # test_describer.py for that), Generator/Judge monkeypatched to the
    # deterministic stand-ins above, all three category loops real, and
    # the Aggregator step (build_final_report) real and automatic.
    # ----------------------------------------------------------------
    print("-" * 78)
    print("Running run_full_session() end to end (Describer overridden, "
          "Generator/Judge stubbed, Aggregator real)...")
    print("-" * 78)
    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        session_result = run_full_session(
            aut_config=aut_config,
            max_rounds=MAX_ROUNDS,
            capability_description_override=CAPABILITY_DESCRIPTION,
        )

    session_id = session_result.session_id
    live_report = session_result.final_report

    # DB sanity check: 3 categories x 3 rounds each = 9 rows for this session.
    rows = get_rounds_for_session(session_id)
    if len(rows) != EXPECTED_TOTAL_ROUNDS:
        print(f"  [ERROR] expected {EXPECTED_TOTAL_ROUNDS} rounds in DB, found {len(rows)}")
        ok = False

    # ----------------------------------------------------------------
    # Simulate "reload later": a SEPARATE, STANDALONE build_final_report()
    # call, with none of the in-memory summaries passed in — must
    # reconstruct identical category/performance data purely from DB state.
    # ----------------------------------------------------------------
    print("-" * 78)
    print("Calling build_final_report(session_id) standalone (simulating a later reload)...")
    print("-" * 78)
    reloaded_report = build_final_report(session_id)

    print_final_report(reloaded_report)

    # ----------------------------------------------------------------
    # Assertions — checked against the RELOADED report (the one built with
    # zero in-memory state), since that's the one proving "reconstructs
    # correctly purely from DB state" per the spec. The live report from
    # run_full_session() is cross-checked against it below too.
    # ----------------------------------------------------------------
    for label, report in (("live (from run_full_session)", live_report), ("reloaded (standalone)", reloaded_report)):
        print(f"\nChecking {label} report...")

        if report.session_id != session_id:
            print(f"  [ERROR] session_id mismatch: {report.session_id!r} != {session_id!r}")
            ok = False

        # --- security: broken at round 3 ---
        security = report.categories.get("security")
        if security is None:
            print("  [ERROR] no 'security' category in report")
            ok = False
        else:
            if security.status != "broken":
                print(f"  [ERROR] security.status expected 'broken', got {security.status!r}")
                ok = False
            if security.breaking_point_round != 3:
                print(f"  [ERROR] security.breaking_point_round expected 3, got {security.breaking_point_round!r}")
                ok = False
            if not security.breaking_point_summary:
                print("  [ERROR] security.breaking_point_summary is empty/None, expected an explanation")
                ok = False
            else:
                for expected_substr in ("Round 3", "security=3/10", "compliance=3/10"):
                    if expected_substr not in security.breaking_point_summary:
                        print(
                            f"  [ERROR] security.breaking_point_summary missing expected "
                            f"substring {expected_substr!r}: {security.breaking_point_summary!r}"
                        )
                        ok = False
            if len(security.round_history) != 3:
                print(f"  [ERROR] security round_history expected 3 rounds, got {len(security.round_history)}")
                ok = False

        # --- functionality & compliance: robust across all 3 rounds ---
        for category in ("functionality", "compliance"):
            cat_report = report.categories.get(category)
            if cat_report is None:
                print(f"  [ERROR] no {category!r} category in report")
                ok = False
                continue
            if cat_report.status != "robust_within_tested_range":
                print(f"  [ERROR] {category}.status expected 'robust_within_tested_range', got {cat_report.status!r}")
                ok = False
            if cat_report.breaking_point_round is not None:
                print(f"  [ERROR] {category}.breaking_point_round expected None, got {cat_report.breaking_point_round!r}")
                ok = False
            if cat_report.breaking_point_summary is not None:
                print(f"  [ERROR] {category}.breaking_point_summary expected None, got {cat_report.breaking_point_summary!r}")
                ok = False
            if len(cat_report.round_history) != 3:
                print(f"  [ERROR] {category} round_history expected 3 rounds, got {len(cat_report.round_history)}")
                ok = False
            if not all(r.passed for r in cat_report.round_history):
                print(f"  [ERROR] {category}: expected every round to have passed=True")
                ok = False

        # --- performance_and_cost, computed against the hand-derived fixture math ---
        perf = report.performance_and_cost
        checks = [
            ("total_rounds", perf.total_rounds, EXPECTED_TOTAL_ROUNDS),
            ("total_latency_ms", perf.total_latency_ms, EXPECTED_TOTAL_LATENCY_MS),
            ("average_latency_ms", perf.average_latency_ms, EXPECTED_AVG_LATENCY_MS),
            ("total_tokens_used", perf.total_tokens_used, EXPECTED_TOTAL_TOKENS),
            ("average_tokens_used", perf.average_tokens_used, EXPECTED_AVG_TOKENS),
            ("rounds_missing_token_data", perf.rounds_missing_token_data, EXPECTED_MISSING_TOKENS),
            ("total_estimated_cost", perf.total_estimated_cost, EXPECTED_TOTAL_COST),
            ("average_estimated_cost", perf.average_estimated_cost, EXPECTED_AVG_COST),
            ("rounds_missing_cost_data", perf.rounds_missing_cost_data, EXPECTED_MISSING_COST),
        ]
        for field_name, actual, expected in checks:
            # Tolerant float comparison for the cost/latency-average fields;
            # exact for the integer count fields (a plain != also works for
            # them, but one comparison path keeps this loop simple).
            mismatch = abs(actual - expected) > 1e-9 if isinstance(expected, float) else actual != expected
            if mismatch:
                print(f"  [ERROR] {field_name} expected {expected!r}, got {actual!r}")
                ok = False

        if not report.overall_verdict or not report.overall_verdict.strip():
            print("  [ERROR] overall_verdict is empty")
            ok = False

    # --- live vs reloaded: category/performance data must be IDENTICAL
    # (overall_verdict/generated_at are allowed to differ — two separate
    # LLM calls and two separate timestamps) ---
    if live_report.categories != reloaded_report.categories:
        print("\n  [ERROR] live vs reloaded report: 'categories' differ — DB-derived data should be identical")
        ok = False
    if live_report.performance_and_cost != reloaded_report.performance_and_cost:
        print("\n  [ERROR] live vs reloaded report: 'performance_and_cost' differ — DB-derived data should be identical")
        ok = False

    print()
    print("=" * 78)
    print(f"  {'OK' if ok else 'FAILED'}  Block G aggregator test")
    print("=" * 78)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
