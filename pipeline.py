"""
pipeline.py

Block D — the first complete single-round pipeline: Generator -> AUT -> Judge.

ORCHESTRATION CHOICE (per the spec's point 5):
Generator and Judge are each kicked off as their own small, self-contained,
single-Task Crew (agents.generator.generate_task and agents.judge.judge_round
— both already built that way), with the AUT call (aut.connector.call_aut —
a plain Python function, NOT a CrewAI Agent, per the Block A boundary
decision) executed in between them in plain Python. They are NOT chained
into one multi-Task Crew via Task `context=[generator_task]`.

Why: CrewAI's `context` wiring is built for "the next Task's Agent consumes
the previous Task's raw output" — it has no clean slot for "previous output,
sent through an external system, and THAT result is what the next Task
should consume". Forcing the AUT call to happen "inside" a single Crew would
mean wrapping call_aut() as a custom Tool or a Task callback purely to
satisfy the framework's shape — more machinery, harder to unit-test in
isolation, for no real benefit over two Crews that are already each
independently reliable and already independently tested (see
tests/test_judge.py and tests/test_connector.py). Two small, explicitly-
orchestrated Crews with plain Python in between is simpler, and each stage
can be debugged on its own — which is exactly what tests/test_single_round.py
does, one category at a time.
"""
import uuid
from typing import Optional

from pydantic import BaseModel

from agents.generator import generate_task
from agents.judge import judge_round
from aut.connector import AUTConfig, call_aut
from db.store import init_db, insert_round, insert_session
from progress import OnEvent, emit_event


class RoundResult(BaseModel):
    """Everything produced by one full Generator -> AUT -> Judge round,
    already persisted to the DB by the time this is returned."""

    session_id: str
    round_id: str
    round_number: int
    category: str
    difficulty: int

    task: str
    output: str

    # Primary metrics (drive `passed` — see agents.judge.compute_passed)
    task_completion: int
    security: int
    compliance: int
    # Secondary metrics (context only, never drive `passed`)
    accuracy: int
    relevance: int
    hallucination: int
    safety: int

    passed: bool
    reasoning: str

    latency_ms: float
    tokens_used: Optional[int] = None
    estimated_cost: Optional[float] = None


def run_single_round(
    category: str,
    capability_description: str,
    difficulty: int,
    aut_config: AUTConfig,
    session_id: Optional[str] = None,
    round_number: int = 1,
    on_event: Optional[OnEvent] = None,
) -> RoundResult:
    """
    Run one full round end to end: Generator -> AUT -> Judge -> db.store.

    Args:
        category: "functionality" | "security" | "compliance".
        capability_description: plain-string AUT description, passed straight
                                 into the Generator (see
                                 agents.generator.generate_task). Also used as
                                 the session's aut_description if this call
                                 creates a new session.
        difficulty: integer 1-5, passed straight into the Generator.
        aut_config: a PublicAPIConfig / CustomEndpointConfig /
                    FunctionImportConfig / ManualConfig instance — whichever
                    of the four connection modes this round should use (see
                    aut/connector.py). All four work identically here since
                    this function only ever calls the single call_aut(task,
                    config) entry point.
        session_id: existing session id to attach this round to. If omitted,
                    a new session is created (a fresh id is generated,
                    aut_description=capability_description) — convenient for
                    single-round calls like this step's tests; later blocks
                    (the escalating loop) are expected to pass one shared
                    session_id across many rounds instead.
        round_number: stored as-is on the round row. This step always calls
                      with round_number=1 (one round per category, no loop
                      yet) — the escalating loop in a later block is what
                      increments it.
        on_event: optional progress callback (see progress.py). Fires
                  "round_started" before the Generator call, "error" (tagged
                  with the failing stage: generator/aut/judge) if any of the
                  three raises, and "round_completed" with the final result.
                  None (the default) is a no-op — existing callers are
                  unaffected.

    Returns:
        A RoundResult with the generated task, the AUT's output, all seven
        Judge scores, the pass/fail verdict, and performance/cost figures.

    Raises:
        ValueError: for invalid category/difficulty/capability_description
                    (bubbled up from agents.generator.generate_task).
        agents.generator.GeneratorError: if the Generator fails after retrying.
        agents.judge.JudgeError: if the Judge fails after retrying.
        aut.connector.AUTConnectorError / ManualLookupError: if the AUT call fails.
    """
    init_db()  # no-op if already initialized; keeps this function runnable standalone

    if session_id is None:
        session_id = str(uuid.uuid4())
        insert_session(session_id, aut_description=capability_description)

    emit_event(
        on_event,
        "round_started",
        {"category": category, "round_number": round_number, "difficulty": difficulty},
    )

    # 1. Generator -> exactly one test task for this category/difficulty.
    try:
        generated = generate_task(
            category=category,
            capability_description=capability_description,
            difficulty=difficulty,
        )
    except Exception as e:
        emit_event(on_event, "error", {"stage": "generator", "message": str(e)})
        raise

    # 2. AUT -> send the generated task through whichever of the four modes
    #    aut_config specifies. call_aut() is the ONLY thing this pipeline
    #    knows about the AUT — it never branches on aut_config.mode itself.
    try:
        aut_response = call_aut(generated.task_text, aut_config)
    except Exception as e:
        emit_event(on_event, "error", {"stage": "aut", "message": str(e)})
        raise

    # 3. Judge -> score the (task, output, category) triple. `passed` is
    #    already deterministically recomputed inside judge_round().
    try:
        score = judge_round(
            task=generated.task_text,
            output=aut_response.output,
            category=category,
        )
    except Exception as e:
        emit_event(on_event, "error", {"stage": "judge", "message": str(e)})
        raise

    # 4. Persist. latency_ms is stored as an int per db/schema.sql's INTEGER
    #    column; the RoundResult returned below keeps the original float.
    round_id = str(uuid.uuid4())
    insert_round(
        id=round_id,
        session_id=session_id,
        category=category,
        round_number=round_number,
        difficulty=str(difficulty),
        task=generated.task_text,
        output=aut_response.output,
        primary_scores={
            "task_completion": score.task_completion,
            "security": score.security,
            "compliance": score.compliance,
        },
        secondary_scores={
            "accuracy": score.accuracy,
            "relevance": score.relevance,
            "hallucination": score.hallucination,
            "safety": score.safety,
        },
        pass_fail=score.passed,
        latency_ms=int(round(aut_response.latency_ms)),
        tokens_used=aut_response.tokens_used,
        estimated_cost=aut_response.estimated_cost,
    )

    result = RoundResult(
        session_id=session_id,
        round_id=round_id,
        round_number=round_number,
        category=category,
        difficulty=difficulty,
        task=generated.task_text,
        output=aut_response.output,
        task_completion=score.task_completion,
        security=score.security,
        compliance=score.compliance,
        accuracy=score.accuracy,
        relevance=score.relevance,
        hallucination=score.hallucination,
        safety=score.safety,
        passed=score.passed,
        reasoning=score.reasoning,
        latency_ms=aut_response.latency_ms,
        tokens_used=aut_response.tokens_used,
        estimated_cost=aut_response.estimated_cost,
    )

    emit_event(on_event, "round_completed", result.model_dump())
    return result
