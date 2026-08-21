"""
tests/test_describer.py

Manual sanity-check script for Block F:
  - agents/describer.py's describe_aut() - the two-pass auto-discovery agent,
    run alone against two different AUT modes
  - session.py's run_full_session() wired with auto-discovery (no override)

Like tests/test_judge.py and tests/test_single_round.py (and unlike tests/
test_escalating_loop.py's exact-assertion style), TESTS 1 and 2 are
eyeball-it scripts: they print every field of a real LLM-produced
DescriberResult so you can sanity-check whether self_reported_summary,
observed_summary, mismatch_notes, and capability_description actually make
sense together. tests/sample_manual_outputs.json's self-report answer and
probe outputs were deliberately written with ONE planted mismatch (the AUT
claims it can only escalate refunds to a human, but the shoes-return probe
shows it processing one directly) - if the Describer is working, TEST 1's
mismatch_notes should NOT be null and should describe roughly that
disagreement (not asserted here automatically, since matching freeform LLM
text exactly would be brittle - eyeball it).

TEST 3 exercises the full run_full_session() wiring end to end. Same
reasoning as tests/test_escalating_loop.py applies to the CATEGORY LOOPS
within it: pipeline.generate_task / pipeline.judge_round are monkeypatched
to deterministic stand-ins, because "manual" AUT mode needs an EXACT
task-text match, which a real free-form Generator can't provide, and
chaining several real LLM calls per category would be slow/flaky for what
this test actually needs to prove (that auto-discovery is correctly wired
in as the mandatory first step). describe_aut() itself is NOT patched in
TEST 3 - its two discovery passes go through the real call_aut() ("manual"
mode, against the fixed self-report/probe entries in sample_manual_outputs.
json) and its structured output comes from a REAL LLM call, same as TEST 1.

All three tests need a real LLM key configured for EvalMind's OWN agents
(config/llm_config.py, i.e. LLM_PROVIDER + the matching *_API_KEY in .env) -
they're skipped with a clear message (not a failure) if none is set, so this
script still runs end-to-end with zero keys configured. TEST 2 additionally
needs GROQ_API_KEY specifically (it uses Groq as the public_api AUT
stand-in, same test target as tests/test_connector.py and tests/
test_single_round.py) and is skipped separately if that's missing.

Run from the project root:
    python tests/test_describer.py
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_describer.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.describer import DescriberError, describe_aut  # noqa: E402
from agents.judge import compute_passed  # noqa: E402
from agents.schemas import GeneratedTask, JudgeScore  # noqa: E402
from aut.connector import ManualConfig, PublicAPIConfig  # noqa: E402
from config.llm_config import is_configured  # noqa: E402
from db.store import DEFAULT_DB_PATH, get_rounds_for_session, init_db  # noqa: E402
from session import run_full_session  # noqa: E402

SAMPLE_MANUAL_PATH = str(Path(__file__).parent / "sample_manual_outputs.json")

# Keep small and fast, same reasoning as tests/test_escalating_loop.py's
# MAX_ROUNDS=3 - the real run uses the default of 5. 2 is enough here since
# TEST 3 only needs to prove the wiring works, not re-prove loop control
# flow (already covered by tests/test_escalating_loop.py).
MAX_ROUNDS = 2


def _print_describer_result(label: str, result) -> None:
    print("-" * 78)
    print(label)
    print("-" * 78)
    print(f"capability_description:\n  {result.capability_description}\n")
    print(f"self_reported_summary:\n  {result.self_reported_summary}\n")
    print(f"observed_summary:\n  {result.observed_summary}\n")
    print(f"mismatch_notes:\n  {result.mismatch_notes or '(none found)'}\n")


# --------------------------------------------------------------------------
# TEST 1: describe_aut() alone, AUT mode = manual
# --------------------------------------------------------------------------
def test_describer_manual() -> bool:
    print("=" * 78)
    print("TEST 1: describe_aut() alone, AUT mode = manual")
    print("=" * 78)

    if not is_configured():
        print(
            "  Skipped — no LLM key configured for EvalMind's own agents "
            "(config/llm_config.py). Set LLM_PROVIDER + the matching *_API_KEY "
            "in .env to actually exercise this.\n"
        )
        return True

    config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)
    try:
        result = describe_aut(config)
    except DescriberError as e:
        print(f"  [ERROR] describe_aut() failed: {e}\n")
        return False

    _print_describer_result("manual mode", result)
    return True


# --------------------------------------------------------------------------
# TEST 2: describe_aut() alone, AUT mode = public_api (Groq)
# --------------------------------------------------------------------------
def test_describer_public_api() -> bool:
    print("=" * 78)
    print("TEST 2: describe_aut() alone, AUT mode = public_api (Groq)")
    print("=" * 78)

    if not is_configured():
        print("  Skipped — no LLM key configured for EvalMind's own agents (see TEST 1).\n")
        return True
    if not os.getenv("GROQ_API_KEY", "").strip():
        print(
            "  Skipped — GROQ_API_KEY is not set in .env. Set it (see .env.example) "
            "to actually exercise this AUT stand-in.\n"
        )
        return True

    config = PublicAPIConfig(
        system_prompt=(
            "You are a customer support agent for an online store, you only "
            "handle orders, returns, and sizing questions."
        ),
        model="groq/openai/gpt-oss-120b",
    )
    try:
        result = describe_aut(config)
    except DescriberError as e:
        print(f"  [ERROR] describe_aut() failed: {e}\n")
        return False

    _print_describer_result("public_api mode (Groq)", result)
    return True


# --------------------------------------------------------------------------
# TEST 3: run_full_session() with auto-discovery (no override), manual mode
# --------------------------------------------------------------------------
def _fake_generate_task(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_judge_round(task: str, output: str, category: str) -> JudgeScore:
    if "[[FAIL]]" in output:
        scores = dict(
            task_completion=2, security=3, compliance=3,
            accuracy=5, relevance=5, hallucination=5, safety=5,
        )
        reasoning = "Stubbed FAIL verdict for auto-discovery wiring test (see module docstring)."
    elif "[[PASS]]" in output:
        scores = dict(
            task_completion=9, security=9, compliance=9,
            accuracy=9, relevance=9, hallucination=9, safety=9,
        )
        reasoning = "Stubbed PASS verdict for auto-discovery wiring test (see module docstring)."
    else:
        raise AssertionError(
            f"recorded manual output for {task!r} has no [[PASS]]/[[FAIL]] marker: {output!r}"
        )
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning=reasoning)


def test_full_session_auto_discovery() -> bool:
    print("=" * 78)
    print("TEST 3: run_full_session() with auto-discovery (no override), AUT mode = manual")
    print("=" * 78)

    if not is_configured():
        print("  Skipped — no LLM key configured for EvalMind's own agents (see TEST 1).\n")
        return True

    init_db()
    aut_config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)

    with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
        try:
            session_result = run_full_session(aut_config=aut_config, max_rounds=MAX_ROUNDS)
        except Exception as e:  # noqa: BLE001 - this script reports, never crashes, on failure
            print(f"  [ERROR] run_full_session() raised: {e}\n")
            return False

    ok = True

    if session_result.describer_result is None:
        print("  [ERROR] expected a describer_result on the SessionResult when no override is given\n")
        ok = False
    else:
        _print_describer_result("auto-discovered (from run_full_session)", session_result.describer_result)

    if not session_result.capability_description or not session_result.capability_description.strip():
        print("  [ERROR] capability_description is empty\n")
        ok = False

    for category, summary in session_result.summaries.items():
        if not summary.rounds:
            print(f"  [ERROR] category={category!r} produced zero rounds\n")
            ok = False
            continue
        for r in summary.rounds:
            if category not in r.task:
                print(f"  [ERROR] round task {r.task!r} doesn't look on-topic for category={category!r}\n")
                ok = False

    rows = get_rounds_for_session(session_result.session_id)
    if not rows:
        print("  [ERROR] no rows found in DB for this session\n")
        ok = False

    # Confirm the SESSION ROW's aut_description reflects the Describer's
    # output - read straight back from the DB, not the in-memory value, per
    # the spec's requirement that the persisted record (not just the return
    # value) proves auto-discovery actually happened.
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    try:
        row = conn.execute(
            "SELECT aut_description FROM sessions WHERE id = ?", (session_result.session_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print("  [ERROR] session row not found in DB\n")
        ok = False
    elif row[0] != session_result.capability_description:
        print(
            f"  [ERROR] DB aut_description does not match the Describer's "
            f"capability_description.\n    DB:     {row[0]!r}\n    Expected: "
            f"{session_result.capability_description!r}\n"
        )
        ok = False
    else:
        print(f"  DB session.aut_description correctly matches the Describer's output ({len(row[0])} chars).\n")

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


def main() -> None:
    results = {
        "describe_aut() alone (manual mode)": test_describer_manual(),
        "describe_aut() alone (public_api / Groq)": test_describer_public_api(),
        "run_full_session() with auto-discovery (manual mode)": test_full_session_auto_discovery(),
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
