"""
scripts/rehearsal.py

Block H — buffer/rehearsal script. Runs session.run_full_session() TWICE,
back to back, against demo.scenarios.LIVE_SCENARIO — the actual real-AUT
scenario used for the live demo (a Groq-backed public_api target, the same
model tests/test_connector.py's test_public_api() already exercises). No
dummy target, no manual-mode fallback, no monkeypatching of Generator/Judge
anywhere in this script — every LLM/AUT call in both runs is real.

PURPOSE: catch real-AUT nondeterminism/flakiness BEFORE the live demo. This
is NOT re-testing the escalating loop's own control flow (round numbering,
difficulty escalation, stop-on-first-failure) — that is already covered,
fast and deterministically, by tests/test_escalating_loop.py against a
stubbed Generator/Judge. The only thing worth checking twice, for real, is
whether the real AUT (and the real Generator/Judge scoring it) actually
behaves consistently from one run to the next.

Each call to run_full_session() creates its OWN new session_id internally
(see session.py — session_id is never passed in), so this script naturally
produces two fully independent sessions sharing nothing but the
aut_config / capability_description_override / max_rounds inputs.

Run from the project root:
    python scripts/rehearsal.py

This will make a real, noticeable number of live LLM/AUT calls (Describer:
5 AUT calls + 1 synthesis call; 3 categories x up to max_rounds rounds each,
each round = 1 Generator call + 1 AUT call + 1 Judge call; 1 Aggregator
verdict call — all TWICE). Expect it to take a few minutes, and possibly
longer if Groq/Gemini free-tier rate limits kick in.

Exits 0 if both runs agree on every category's status AND breaking_point,
non-zero if anything disagrees (or if either run raised). Note this is a
DIAGNOSTIC script, not a pytest suite: a nonzero exit is a strong signal to
go investigate (and to be ready to use the manual fallback scenario — see
DEMO.md) before the demo, not proof anything in the codebase is broken.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python scripts/rehearsal.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo.scenarios import LIVE_SCENARIO  # noqa: E402
from session import SessionResult, run_full_session  # noqa: E402

CATEGORIES = ("functionality", "security", "compliance")


def _run_once(label: str) -> SessionResult:
    print("=" * 78)
    print(f"REHEARSAL RUN {label} — scenario: {LIVE_SCENARIO.name!r} (mode={LIVE_SCENARIO.aut_config.mode})")
    print("=" * 78)
    result = run_full_session(
        aut_config=LIVE_SCENARIO.aut_config,
        max_rounds=LIVE_SCENARIO.max_rounds,
        capability_description_override=LIVE_SCENARIO.capability_description_override,
    )
    print(f"\n>>> Run {label} finished. session_id={result.session_id}\n")
    return result


def _side_by_side(run1: SessionResult, run2: SessionResult) -> bool:
    """Print a side-by-side per-category comparison of the two runs.

    Returns True if every category agrees between both runs (same status
    AND same breaking_point), False if anything disagrees.
    """
    width = 78
    print("=" * width)
    print("SIDE-BY-SIDE COMPARISON")
    print("=" * width)
    print(f"{'category':<14} {'run 1 status':<28} {'run 1 bp':<10} {'run 2 status':<28} {'run 2 bp':<10}")
    print("-" * width)

    all_agree = True
    for category in CATEGORIES:
        s1 = run1.summaries[category]
        s2 = run2.summaries[category]
        bp1 = s1.breaking_point if s1.breaking_point is not None else "-"
        bp2 = s2.breaking_point if s2.breaking_point is not None else "-"

        disagree = (s1.status != s2.status) or (s1.breaking_point != s2.breaking_point)
        line = f"{category:<14} {s1.status:<28} {str(bp1):<10} {s2.status:<28} {str(bp2):<10}"
        if disagree:
            line += "   <-- DISAGREE"
            all_agree = False
        print(line)

    print("-" * width)
    if all_agree:
        print("All three categories agreed between both runs. No nondeterminism detected.")
    else:
        print(
            "One or more categories DISAGREED between the two runs. This means the "
            "real AUT (and/or the real Generator/Judge scoring it) is not behaving "
            "consistently round to round. Investigate before the live demo, and be "
            "ready to fall back to demo.scenarios.MANUAL_FALLBACK_ROBUST (see "
            "DEMO.md's recovery procedure) if this looks likely to recur live."
        )
    print("=" * width)
    return all_agree


def main() -> None:
    print(
        f"Rehearsing scenario {LIVE_SCENARIO.name!r} TWICE against the real AUT "
        f"(mode={LIVE_SCENARIO.aut_config.mode!r}, max_rounds={LIVE_SCENARIO.max_rounds})...\n"
    )

    try:
        run1 = _run_once("1/2")
    except Exception as e:  # noqa: BLE001 - report clearly, don't crash uninformatively
        print(f"\n[FATAL] Rehearsal run 1 raised: {e}")
        print("Fix this before the demo — the live target is not currently working end to end.")
        sys.exit(1)

    try:
        run2 = _run_once("2/2")
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] Rehearsal run 2 raised: {e}")
        print(
            "Run 1 succeeded but run 2 raised — that is itself a flakiness signal. "
            "Fix or be ready to fall back before the demo."
        )
        sys.exit(1)

    agree = _side_by_side(run1, run2)

    if not agree:
        sys.exit(1)


if __name__ == "__main__":
    main()
