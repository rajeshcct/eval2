"""
tests/test_progress_events.py

Test script for Phase I's progress-event threading:
  - progress.py's ProgressEvent shape / emit_event() helper
  - pipeline.run_single_round()'s "round_started" / "round_completed" / "error"
  - loop_runner.run_category_loop()'s "category_started" / "category_completed"
    (plus every round event bubbling straight through it, unmodified)

Like tests/test_escalating_loop.py, this makes EXACT assertions about which
event types fire and in what order - which needs deterministic Generator/Judge
behavior. So this file reuses the exact same monkeypatch trick (pipeline.
generate_task / pipeline.judge_round swapped for fixed stand-ins, no LLM
call, no randomness), against the same tests/sample_manual_outputs.json
"manual" AUT data. See tests/test_escalating_loop.py's module docstring for
why that pattern is necessary here specifically.

Four cases:
  1. A single passing round -> exactly ["round_started", "round_completed"],
     in that order, with round_completed's data matching the real RoundResult.
  2. A single round whose AUT call fails (ManualLookupError, from asking for
     a task_text with no recorded entry) -> exactly
     ["round_started", "error"], the error tagged stage="aut", and the
     original ManualLookupError still propagates out of run_single_round()
     (an on_event hook must never swallow or change a real failure).
  3. A full category loop (security: PASS then FAIL, same fixture data
     tests/test_escalating_loop.py uses) -> confirms category_started fires
     first, category_completed fires last, and every round's own
     round_started/round_completed pair from case 1 lands in between, in
     order - i.e. run_category_loop() doesn't just fire its own two events,
     it correctly threads on_event down into every run_single_round() call.
  4. A deliberately broken on_event callback (raises every time it's called)
     -> run_single_round() must still complete and return its normal
     RoundResult, proving progress.py's emit_event() swallows callback
     errors instead of ever letting them interrupt a real evaluation run.

Run from the project root:
    python tests/test_progress_events.py
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_progress_events.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.judge import compute_passed  # noqa: E402
from agents.schemas import GeneratedTask, JudgeScore  # noqa: E402
from aut.connector import ManualConfig, ManualLookupError  # noqa: E402
from db.store import init_db, insert_session  # noqa: E402
from loop_runner import run_category_loop  # noqa: E402
from pipeline import run_single_round  # noqa: E402

SAMPLE_MANUAL_PATH = str(Path(__file__).parent / "sample_manual_outputs.json")
CAPABILITY_DESCRIPTION = (
    "This agent is a customer support bot for an online store handling "
    "orders, returns, and sizing questions."
)


# --------------------------------------------------------------------------
# Same deterministic Generator/Judge stand-ins as tests/test_escalating_loop.py
# (see that file's module docstring for why this is necessary).
# --------------------------------------------------------------------------
def _fake_generate_task(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_generate_task_no_manual_entry(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    # Deliberately NOT a key in sample_manual_outputs.json, so ManualConfig's
    # lookup misses and call_aut() raises ManualLookupError - this is what
    # drives case 2's "error" (stage="aut") event.
    return GeneratedTask(
        task_text="no such recorded task, this key is intentionally absent from the fixture",
        category=category,
        difficulty=difficulty,
    )


def _fake_judge_round(task: str, output: str, category: str) -> JudgeScore:
    if "[[FAIL]]" in output:
        scores = dict(
            task_completion=2, security=3, compliance=3,
            accuracy=5, relevance=5, hallucination=5, safety=5,
        )
        reasoning = "Stubbed FAIL verdict for progress-event test (see module docstring)."
    elif "[[PASS]]" in output:
        scores = dict(
            task_completion=9, security=9, compliance=9,
            accuracy=9, relevance=9, hallucination=9, safety=9,
        )
        reasoning = "Stubbed PASS verdict for progress-event test (see module docstring)."
    else:
        raise AssertionError(
            f"recorded manual output for {task!r} has no [[PASS]]/[[FAIL]] marker: {output!r}"
        )
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning=reasoning)


# --------------------------------------------------------------------------
# Case 1: a single passing round -> ["round_started", "round_completed"]
# --------------------------------------------------------------------------
def test_single_round_success_events() -> bool:
    print("=" * 78)
    print("CASE 1: single passing round -> exactly [round_started, round_completed]")
    print("=" * 78)

    events = []
    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)
    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)

    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        result = run_single_round(
            category="functionality",
            capability_description=CAPABILITY_DESCRIPTION,
            difficulty=1,
            aut_config=aut_config,
            session_id=session_id,
            round_number=1,
            on_event=events.append,
        )

    ok = True
    types = [e["type"] for e in events]
    print(f"  event types fired: {types}")

    if types != ["round_started", "round_completed"]:
        print(f"  [ERROR] expected ['round_started', 'round_completed'], got {types}")
        ok = False

    if events:
        started_data = events[0]["data"]
        if started_data != {"category": "functionality", "round_number": 1, "difficulty": 1}:
            print(f"  [ERROR] round_started data wrong: {started_data}")
            ok = False

    if len(events) == 2:
        completed_data = events[1]["data"]
        if completed_data.get("round_id") != result.round_id:
            print("  [ERROR] round_completed data's round_id doesn't match the returned RoundResult")
            ok = False
        if completed_data.get("passed") is not True:
            print(f"  [ERROR] expected a passing round, round_completed data says passed={completed_data.get('passed')!r}")
            ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 2: AUT call fails -> ["round_started", "error"(stage="aut")], and the
# original exception still propagates.
# --------------------------------------------------------------------------
def test_single_round_error_event() -> bool:
    print("=" * 78)
    print("CASE 2: AUT call fails (ManualLookupError) -> exactly [round_started, error]")
    print("=" * 78)

    events = []
    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)
    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)

    ok = True
    raised = None
    with patch("pipeline.generate_task", _fake_generate_task_no_manual_entry):
        try:
            run_single_round(
                category="functionality",
                capability_description=CAPABILITY_DESCRIPTION,
                difficulty=1,
                aut_config=aut_config,
                session_id=session_id,
                round_number=1,
                on_event=events.append,
            )
        except ManualLookupError as e:
            raised = e

    types = [e["type"] for e in events]
    print(f"  event types fired: {types}")

    if raised is None:
        print("  [ERROR] expected ManualLookupError to propagate out of run_single_round(), none was raised")
        ok = False

    if types != ["round_started", "error"]:
        print(f"  [ERROR] expected ['round_started', 'error'], got {types}")
        ok = False
    elif events[1]["data"].get("stage") != "aut":
        print(f"  [ERROR] expected error event stage='aut', got {events[1]['data'].get('stage')!r}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 3: full category loop (security: PASS then FAIL) -> category_started
# first, category_completed last, every round's events threaded through
# in between, in order.
# --------------------------------------------------------------------------
def test_category_loop_events() -> bool:
    print("=" * 78)
    print("CASE 3: category loop (security PASS then FAIL) -> events thread through in order")
    print("=" * 78)

    events = []
    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)
    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)

    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        run_category_loop(
            category="security",
            capability_description=CAPABILITY_DESCRIPTION,
            aut_config=aut_config,
            max_rounds=3,
            session_id=session_id,
            on_event=events.append,
        )

    ok = True
    types = [e["type"] for e in events]
    print(f"  event types fired: {types}")

    expected = [
        "category_started",
        "round_started", "round_completed",   # round 1 (diff1, PASS)
        "round_started", "round_completed",   # round 2 (diff2, FAIL -> loop stops)
        "category_completed",
    ]
    if types != expected:
        print(f"  [ERROR] expected {expected}, got {types}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 4: a broken on_event callback must never crash a real run.
# --------------------------------------------------------------------------
def test_broken_callback_is_swallowed() -> bool:
    print("=" * 78)
    print("CASE 4: on_event callback that always raises -> run_single_round() still completes")
    print("=" * 78)

    def _always_raises(event) -> None:
        raise RuntimeError("simulated broken UI callback")

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)
    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)

    ok = True
    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        try:
            result = run_single_round(
                category="functionality",
                capability_description=CAPABILITY_DESCRIPTION,
                difficulty=1,
                aut_config=aut_config,
                session_id=session_id,
                round_number=1,
                on_event=_always_raises,
            )
        except Exception as e:  # noqa: BLE001 - this is exactly what must NOT happen
            print(f"  [ERROR] a broken on_event callback crashed run_single_round(): {e}")
            return False

    if result is None or result.passed is not True:
        print("  [ERROR] run_single_round() did not return its normal successful result")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


def main() -> None:
    init_db()

    results = {
        "single round success events": test_single_round_success_events(),
        "single round error event": test_single_round_error_event(),
        "category loop events thread through in order": test_category_loop_events(),
        "broken callback is swallowed, run still completes": test_broken_callback_is_swallowed(),
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
