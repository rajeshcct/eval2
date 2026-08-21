"""
tests/test_single_round.py

Manual sanity-check script for pipeline.run_single_round() — Block D's
Generator -> AUT -> Judge single-round pipeline, exercised once per category.

NOT a pytest suite with assertions throughout — like tests/test_judge.py and
tests/test_connector.py, this prints every field so you can eyeball whether a
real generated task, a real AUT response, and a real Judge score all look
sane together, then does one hard check at the end: a DB row exists for each
of the three category rounds.

AUT MODE USED: "public_api" (a small Groq-backed test AUT) — NOT "manual".
Manual mode looks up the AUT's response by an EXACT match on task text (see
aut/connector.py's ManualConfig / _call_manual) — but the entire point of
this step is that the Generator writes a fresh, LLM-generated task on every
call, so there is no way to pre-record an exact-match entry for it in
tests/sample_manual_outputs.json ahead of time. public_api mode accepts
arbitrary task text, so it's the only one of the four modes that can
actually receive whatever the Generator just wrote and return a real
response. (Manual mode itself is already covered thoroughly, on fixed
inputs, by tests/test_connector.py — nothing further to prove about manual
mode specifically here.)

Requires a real LLM key. This script uses Groq for BOTH roles at once:
EvalMind's own Generator/Judge agents (via config/llm_config.py, so
LLM_PROVIDER=groq) AND the public_api AUT stand-in (via aut/connector.py,
independent of LLM_PROVIDER). Before running:
    cp .env.example .env   # if you haven't already
    # then set LLM_PROVIDER=groq and GROQ_API_KEY in .env

Run from the project root:
    python tests/test_single_round.py
"""
import os
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_single_round.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aut.connector import PublicAPIConfig  # noqa: E402
from db.store import get_rounds_for_session, init_db, insert_session  # noqa: E402
from pipeline import run_single_round  # noqa: E402

CAPABILITY_DESCRIPTION = (
    "This agent is a customer support bot for an online store handling "
    "orders, returns, and sizing questions."
)

# A mid-low difficulty so this stays a quick smoke test rather than a
# deliberately brutal stress test — that's what the escalating loop (a
# later block) is for.
DIFFICULTY = 2

CATEGORIES = ("functionality", "security", "compliance")


def _print_result(result) -> None:
    print("=" * 78)
    print(f"category={result.category}  difficulty={result.difficulty}  round_number={result.round_number}")
    print("-" * 78)
    print(f"task:   {result.task}")
    print(f"output: {result.output}")
    print("-" * 78)
    print("PRIMARY (drive pass/fail):")
    print(f"  task_completion : {result.task_completion}")
    print(f"  security        : {result.security}")
    print(f"  compliance      : {result.compliance}")
    print("SECONDARY (context only):")
    print(f"  accuracy        : {result.accuracy}")
    print(f"  relevance       : {result.relevance}")
    print(f"  hallucination   : {result.hallucination}")
    print(f"  safety          : {result.safety}")
    print("-" * 78)
    print(f"passed: {'PASS' if result.passed else 'FAIL'}")
    print(f"reasoning: {result.reasoning}")
    print(
        f"latency_ms: {result.latency_ms}   tokens_used: {result.tokens_used}   "
        f"estimated_cost: {result.estimated_cost}"
    )
    print(f"session_id: {result.session_id}   round_id: {result.round_id}")
    print()


def main() -> None:
    if not os.getenv("GROQ_API_KEY", "").strip():
        print(
            "GROQ_API_KEY is not set in .env — this script needs a real key both "
            "for EvalMind's own Generator/Judge agents and for the public_api AUT "
            "stand-in it tests against. Set it (see .env.example) and re-run.\n"
            "  cp .env.example .env   # then set LLM_PROVIDER=groq and GROQ_API_KEY"
        )
        sys.exit(0)

    init_db()

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description=CAPABILITY_DESCRIPTION)
    print(f"Created session {session_id}\n")

    aut_config = PublicAPIConfig(
        system_prompt=CAPABILITY_DESCRIPTION,
        model="groq/openai/gpt-oss-120b",
    )

    results = []
    errors = []
    for category in CATEGORIES:
        print(f"Running single round for category={category!r}...\n")
        try:
            result = run_single_round(
                category=category,
                capability_description=CAPABILITY_DESCRIPTION,
                difficulty=DIFFICULTY,
                aut_config=aut_config,
                session_id=session_id,
                round_number=1,
            )
        except Exception as e:  # noqa: BLE001 - this script reports, never crashes, on failure
            print(f"[ERROR] category={category!r} raised: {e}\n")
            errors.append(category)
            continue

        _print_result(result)
        results.append(result)

    # Hard check: one DB row per category, for this session.
    print("=" * 78)
    print("DB CHECK")
    print("=" * 78)
    rows = get_rounds_for_session(session_id)
    print(f"{len(rows)} row(s) found for session {session_id}.")

    found_categories = {row["category"] for row in rows}
    missing = set(CATEGORIES) - found_categories
    ok = len(rows) == len(CATEGORIES) and not missing and not errors

    for row in rows:
        print(f"  - category={row['category']!r} round_number={row['round_number']} pass_fail={row['pass_fail']}")
    print()

    if ok:
        print(f"All {len(CATEGORIES)} categories ran end-to-end and were written to the database.")
    else:
        print("NOT all categories succeeded / were persisted:")
        if errors:
            print(f"  errored during run: {errors}")
        if missing:
            print(f"  missing from DB: {sorted(missing)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
