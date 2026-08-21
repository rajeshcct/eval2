"""
loop_runner.py

Block E - the escalating difficulty loop that finds each category's
"breaking point": instead of running one round per category and reporting a
single pass/fail (Block D's run_single_round), run_category_loop() keeps
escalating difficulty round after round until the AUT either fails a round
or survives every round up to max_rounds.

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

    breaking_point is the round_number of the first round that FAILED, or
    None if every round up to max_rounds passed. rounds holds every
    RoundResult that actually ran - 1 up to and including the failing round,
    or all max_rounds if the AUT never failed.
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
    Escalate difficulty for ONE category, round by round, until the AUT
    fails a round or survives max_rounds.

    Round 1 runs at start_difficulty. Every time a round PASSES, difficulty
    increases by difficulty_step (capped at MAX_DIFFICULTY=5) and the loop
    moves on to the next round_number. The first round that FAILS stops the
    loop immediately and that round's round_number becomes the category's
    breaking_point. If every round up to max_rounds passes, breaking_point
    stays None and status is "robust_within_tested_range"; otherwise status
    is "broken".

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
        (or None), and the full list of RoundResult objects for every round
        that actually ran.

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

        if not result.passed:
            breaking_point = round_number
            status = "broken"
            break

        if round_number >= max_rounds:
            # Passed every round up to the cap without ever breaking.
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
