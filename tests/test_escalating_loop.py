"""
tests/test_escalating_loop.py

Test script for Block E's escalating difficulty loop:
  - loop_runner.run_category_loop() - one category's escalate-until-it-breaks loop
  - db.store - confirms the right number of rounds actually got persisted

Unlike tests/test_single_round.py and tests/test_judge.py (deliberately
"eyeball the real LLM output" scripts), this one makes EXACT assertions
about breaking_point/status/round-count - which needs deterministic,
repeatable Generator and Judge behavior. The real Generator (temperature
0.7, an LLM call) and even the real Judge (temperature 0.15, still an LLM
call) can't guarantee bit-for-bit repeatable pass/fail verdicts run to run,
and chaining ~5-6 real LLM calls per category through Groq's free-tier rate
limits (see tests/test_judge.py's 15s inter-call sleep) would make this both
slow and flaky for what should be a fast, deterministic check of the LOOP's
own control flow (round numbering, difficulty escalation, stop-on-first-
failure, robust-if-never-fails) - logic this file adds, not logic already
covered by tests/test_single_round.py or tests/test_judge.py.

So this script monkeypatches exactly two functions, at the exact names
pipeline.py looks them up under (pipeline.generate_task, pipeline.judge_round):

  - generate_task is replaced with a stand-in that deterministically returns
    task_text=f"{category}::diff{difficulty}" - no LLM call, no randomness.
    This is what makes "manual" AUT mode usable here at all: manual mode
    looks up `task` by an EXACT string match (see aut/connector.py), which
    is impossible to pre-record ahead of time for a real Generator's
    free-form LLM phrasing.
  - judge_round is replaced with a stand-in that reads a "[[PASS]]" /
    "[[FAIL]]" marker out of the (manually-recorded) AUT output text and
    returns fixed scores accordingly - but it still calls the REAL
    agents.judge.compute_passed() for the actual pass/fail verdict, so this
    test also exercises the real, category-aware pass/fail gating logic,
    not a reimplementation of it.

Everything else in the chain is real: aut/connector.py's actual "manual"
mode (reading tests/sample_manual_outputs.json), db/store.py's actual
SQLite inserts, and all of loop_runner.py's / pipeline.py's own control flow.

Two cases, per the spec:
  1. "security" fails partway through (round 2 of 3) -> status="broken",
     breaking_point=2 - but the loop no longer stops there. It keeps going
     through max_rounds regardless of the failure, still escalating
     difficulty every round, so this case now proves the OPPOSITE of what
     it used to: that a failure at round 2 does NOT cut the run short -
     all 3 rounds still get stored, and round 2 stays the recorded
     breaking_point even though round 3 also ran.
  2. "functionality" passes every round -> status="robust_within_tested_range",
     breaking_point=None, and all max_rounds rounds get stored.

Run from the project root:
    python tests/test_escalating_loop.py
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_escalating_loop.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.judge import compute_passed  # noqa: E402
from agents.schemas import GeneratedTask, JudgeScore  # noqa: E402
from aut.connector import ManualConfig  # noqa: E402
from db.store import get_rounds_for_session, init_db, insert_session  # noqa: E402
from loop_runner import run_category_loop  # noqa: E402

SAMPLE_MANUAL_PATH = str(Path(__file__).parent / "sample_manual_outputs.json")
CAPABILITY_DESCRIPTION = (
    "This agent is a customer support bot for an online store handling "
    "orders, returns, and sizing questions."
)

# Keep this small and fast, per the spec - the real run uses the default of 5.
MAX_ROUNDS = 3


# --------------------------------------------------------------------------
# Deterministic stand-ins for the Generator and Judge (see module docstring).
# --------------------------------------------------------------------------
def _fake_generate_task(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_judge_round(task: str, output: str, category: str) -> JudgeScore:
    if "[[FAIL]]" in output:
        scores = dict(
            task_completion=2, security=3, compliance=3,
            accuracy=5, relevance=5, hallucination=5, safety=5,
        )
        reasoning = "Stubbed FAIL verdict for escalating-loop test (see module docstring)."
    elif "[[PASS]]" in output:
        scores = dict(
            task_completion=9, security=9, compliance=9,
            accuracy=9, relevance=9, hallucination=9, safety=9,
        )
        reasoning = "Stubbed PASS verdict for escalating-loop test (see module docstring)."
    else:
        raise AssertionError(
            f"recorded manual output for {task!r} has no [[PASS]]/[[FAIL]] marker: {output!r}"
        )

    # Real pass/fail logic, not reimplemented - exactly what the real
    # judge_round() does after its (here, skipped) LLM call.
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning=reasoning)


def _patched_run_category_loop(*args, **kwargs):
    """run_category_loop(), with pipeline's Generator/Judge swapped for the
    deterministic stand-ins above for the duration of this one call."""
    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        return run_category_loop(*args, **kwargs)


# --------------------------------------------------------------------------
# Case 1: security fails partway through (round 2 of 3) -> "broken"
# --------------------------------------------------------------------------
def test_breaks_partway() -> bool:
    print("=" * 78)
    print(
        "CASE 1: security fails at round 2 of 3 -> expect status='broken', "
        "breaking_point=2, but ALL 3 rounds still run (failure no longer stops the loop)"
    )
    print("=" * 78)

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)

    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)
    summary = _patched_run_category_loop(
        category="security",
        capability_description=CAPABILITY_DESCRIPTION,
        aut_config=aut_config,
        max_rounds=MAX_ROUNDS,
        session_id=session_id,
    )

    ok = True
    print(f"  status={summary.status!r}  breaking_point={summary.breaking_point!r}  rounds_run={len(summary.rounds)}")
    for r in summary.rounds:
        print(f"    R{r.round_number} difficulty={r.difficulty} passed={r.passed}")

    if summary.status != "broken":
        print(f"  [ERROR] expected status='broken', got {summary.status!r}")
        ok = False
    if summary.breaking_point != 2:
        print(f"  [ERROR] expected breaking_point=2, got {summary.breaking_point!r}")
        ok = False
    if len(summary.rounds) != MAX_ROUNDS:
        print(f"  [ERROR] expected all {MAX_ROUNDS} rounds to have run despite the round-2 "
              f"failure, got {len(summary.rounds)}")
        ok = False
    if summary.rounds and summary.rounds[0].passed is not True:
        print("  [ERROR] round 1 should have passed=True (it escalated to round 2 at all)")
        ok = False
    if len(summary.rounds) >= 2 and summary.rounds[1].passed is not False:
        print("  [ERROR] round 2 (the recorded breaking_point) should have passed=False")
        ok = False
    # Difficulty keeps escalating after a failure now, same as after a pass -
    # round 3 should be at difficulty 3, not frozen at round 2's difficulty.
    if len(summary.rounds) == MAX_ROUNDS and summary.rounds[-1].difficulty != MAX_ROUNDS:
        print(
            f"  [ERROR] expected difficulty to keep escalating past the round-2 failure "
            f"(round {MAX_ROUNDS} at difficulty {MAX_ROUNDS}), got {summary.rounds[-1].difficulty}"
        )
        ok = False

    # DB check: all MAX_ROUNDS rows for this category/session now get
    # stored, even though round 2 failed - the loop no longer stops early.
    rows = get_rounds_for_session(session_id)
    security_rows = [r for r in rows if r["category"] == "security"]
    if len(security_rows) != MAX_ROUNDS:
        print(f"  [ERROR] expected exactly {MAX_ROUNDS} stored rounds in DB, found {len(security_rows)}")
        ok = False
    round_numbers = sorted(r["round_number"] for r in security_rows)
    if round_numbers != list(range(1, MAX_ROUNDS + 1)):
        print(f"  [ERROR] expected stored round_numbers {list(range(1, MAX_ROUNDS + 1))}, got {round_numbers}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 2: functionality never fails within max_rounds -> "robust_within_tested_range"
# --------------------------------------------------------------------------
def test_stays_robust() -> bool:
    print("=" * 78)
    print(
        "CASE 2: functionality passes all 3 rounds -> expect "
        "status='robust_within_tested_range', breaking_point=None"
    )
    print("=" * 78)

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)

    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)
    summary = _patched_run_category_loop(
        category="functionality",
        capability_description=CAPABILITY_DESCRIPTION,
        aut_config=aut_config,
        max_rounds=MAX_ROUNDS,
        session_id=session_id,
    )

    ok = True
    print(f"  status={summary.status!r}  breaking_point={summary.breaking_point!r}  rounds_run={len(summary.rounds)}")
    for r in summary.rounds:
        print(f"    R{r.round_number} difficulty={r.difficulty} passed={r.passed}")

    if summary.status != "robust_within_tested_range":
        print(f"  [ERROR] expected status='robust_within_tested_range', got {summary.status!r}")
        ok = False
    if summary.breaking_point is not None:
        print(f"  [ERROR] expected breaking_point=None, got {summary.breaking_point!r}")
        ok = False
    if len(summary.rounds) != MAX_ROUNDS:
        print(f"  [ERROR] expected exactly {MAX_ROUNDS} rounds to have run, got {len(summary.rounds)}")
        ok = False
    if not all(r.passed for r in summary.rounds):
        print("  [ERROR] expected every round to have passed=True")
        ok = False
    expected_last_difficulty = min(MAX_ROUNDS, 5)
    if summary.rounds and summary.rounds[-1].difficulty != expected_last_difficulty:
        print(
            f"  [ERROR] expected difficulty to have escalated to {expected_last_difficulty} by "
            f"the last round, got {summary.rounds[-1].difficulty}"
        )
        ok = False

    # DB check: exactly MAX_ROUNDS rows for this category/session.
    rows = get_rounds_for_session(session_id)
    func_rows = [r for r in rows if r["category"] == "functionality"]
    if len(func_rows) != MAX_ROUNDS:
        print(f"  [ERROR] expected exactly {MAX_ROUNDS} stored rounds in DB, found {len(func_rows)}")
        ok = False
    round_numbers = sorted(r["round_number"] for r in func_rows)
    if round_numbers != list(range(1, MAX_ROUNDS + 1)):
        print(f"  [ERROR] expected stored round_numbers {list(range(1, MAX_ROUNDS + 1))}, got {round_numbers}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


def main() -> None:
    init_db()

    results = {
        "breaks partway (security @ round 2)": test_breaks_partway(),
        "stays robust (functionality, all 3 rounds)": test_stays_robust(),
    }

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}  {label}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
