"""
loop_runner.py

Block E - the escalating difficulty loop that finds each category's
"breaking point": instead of running one round per category and reporting a
single pass/fail (Block D's run_single_round), run_category_loop() always
runs every round up to max_rounds, escalating difficulty round after
round regardless of whether earlier rounds passed or failed. A failure no
longer stops the loop early - it's recorded (the first failing round
becomes the category's breaking_point) and the loop keeps going, so every
category always contributes the same number of rounds to the final report.

Every round still goes through the exact same pipeline.run_single_round()
Generator -> AUT -> Judge -> db.store chain from Block D, completely
unchanged - this module only adds the *loop* around it (difficulty
escalation, round numbering, stop conditions, and the summary shape). It
does not duplicate any Generator/AUT/Judge/DB logic itself.
"""
import uuid
from typing import List, Optional

from pydantic import BaseModel

from aut.connector import AUTConfig
from db.store import insert_session
from pipeline import RoundResult, run_single_round
from progress import OnEvent, emit_event

VALID_CATEGORIES = ("functionality", "security", "compliance")
MIN_DIFFICULTY, MAX_DIFFICULTY = 1, 5

VALID_STATUSES = ("broken", "robust_within_tested_range")


class CategoryLoopResult(BaseModel):
    """Everything produced by one category's escalating loop.

    breaking_point is the round_number of the FIRST round that failed, or
    None if every round up to max_rounds passed. The loop no longer stops
    at the first failure - rounds always holds every RoundResult for all
    max_rounds rounds, whether or not (and however many times) the AUT
    failed along the way.
    """

    category: str
    status: str  # "broken" | "robust_within_tested_range"
    breaking_point: Optional[int] = None
    rounds: List[RoundResult]


def run_category_loop(
    category: str,
    capability_description: str,
    aut_config: AUTConfig,
    max_rounds: int = 5,
    start_difficulty: int = 1,
    difficulty_step: int = 1,
    session_id: Optional[str] = None,
    on_event: Optional[OnEvent] = None,
) -> CategoryLoopResult:
    """
    Escalate difficulty for ONE category, round by round, for all
    max_rounds rounds - a failed round no longer cuts the loop short.

    Round 1 runs at start_difficulty. After EVERY round - pass or fail -
    difficulty increases by difficulty_step (capped at MAX_DIFFICULTY=5)
    and the loop moves on to the next round_number, all the way through
    max_rounds. The first round that FAILS sets the category's
    breaking_point to that round's round_number and flips status to
    "broken" - but the loop keeps running the remaining rounds regardless
    (their results are still recorded in `rounds`; only the first failure
    is ever recorded as the breaking_point). If every round up to
    max_rounds passes, breaking_point stays None and status is
    "robust_within_tested_range".

    Args:
        category: "functionality" | "security" | "compliance".
        capability_description: plain-string AUT description, passed
                                 straight through to every round's Generator
                                 call (see pipeline.run_single_round).
        aut_config: one of the four AUTConfig modes (see aut/connector.py),
                    used unchanged for every round in this loop.
        max_rounds: hard cap on how many rounds this loop will run, whether
                    or not the AUT ever fails. Keep this small in tests
                    (e.g. 3); the real run uses the default of 5.
        start_difficulty: difficulty (1-5) for round 1. Defaults to 1.
        difficulty_step: how much difficulty increases after each PASS.
                          Defaults to 1. Difficulty is capped at
                          MAX_DIFFICULTY=5 - once capped, further passes just
                          keep re-running at difficulty 5 until max_rounds.
        session_id: existing session id to attach every round in this loop
                    to. If omitted, a new session is created (matching
                    pipeline.run_single_round's own behavior when it isn't
                    given one) - convenient for calling run_category_loop()
                    standalone; run_full_session() (session.py) always
                    passes one shared session_id across all three
                    categories instead.
        on_event: optional progress callback (see progress.py), passed
                  straight through to every pipeline.run_single_round() call
                  in this loop (which fires its own "round_started" /
                  "round_completed" / "error" events). This function
                  additionally fires "category_started" before the loop
                  begins and "category_completed" with the final summary at
                  the end. None (the default) is a no-op — existing callers
                  are unaffected.

    Returns:
        A CategoryLoopResult with the category, final status, breaking_point
        (the first failing round's number, or None), and the full list of
        RoundResult objects for all max_rounds rounds.

    Raises:
        ValueError: for an invalid category/max_rounds/start_difficulty (or
                    bubbled up from pipeline.run_single_round /
                    agents.generator.generate_task for a bad difficulty
                    reached mid-loop, which should not be possible given the
                    capping below, but is not re-validated here).
        Any exception pipeline.run_single_round can raise (GeneratorError,
        JudgeError, AUTConnectorError / ManualLookupError) - this loop does
        not catch or retry those itself (run_single_round already retries
        Generator/Judge failures on its own). A round that can't even be
        scored is a harder failure than a round that scored low, and should
        surface immediately rather than being silently treated as a
        breaking point.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"category must be one of {VALID_CATEGORIES}, got {category!r}")
    if max_rounds < 1:
        raise ValueError(f"max_rounds must be >= 1, got {max_rounds!r}")
    if not (MIN_DIFFICULTY <= start_difficulty <= MAX_DIFFICULTY):
        raise ValueError(
            f"start_difficulty must be {MIN_DIFFICULTY}-{MAX_DIFFICULTY}, got {start_difficulty!r}"
        )

    if session_id is None:
        session_id = str(uuid.uuid4())
        insert_session(session_id, aut_description=capability_description)

    emit_event(on_event, "category_started", {"category": category})

    difficulty = start_difficulty
    round_number = 1
    rounds: List[RoundResult] = []
    breaking_point: Optional[int] = None
    status = "robust_within_tested_range"

    while True:
        result = run_single_round(
            category=category,
            capability_description=capability_description,
            difficulty=difficulty,
            aut_config=aut_config,
            session_id=session_id,
            round_number=round_number,
            on_event=on_event,
        )
        rounds.append(result)

        if not result.passed and breaking_point is None:
            # Record only the FIRST failure as the breaking point - later
            # failures in this same loop don't overwrite it - but no
            # longer stop the loop: every category always runs all
            # max_rounds rounds.
            breaking_point = round_number
            status = "broken"

        if round_number >= max_rounds:
            break

        difficulty = min(difficulty + difficulty_step, MAX_DIFFICULTY)
        round_number += 1

    loop_result = CategoryLoopResult(
        category=category,
        status=status,
        breaking_point=breaking_point,
        rounds=rounds,
    )
    emit_event(on_event, "category_completed", loop_result.model_dump())
    return loop_result
