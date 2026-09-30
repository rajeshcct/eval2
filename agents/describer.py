"""
agents/describer.py

CrewAI "Describer" agent — FULLY IMPLEMENTED (Block F).

NOTE ON THE API CHANGE FROM THE BLOCK A STUB: the Block A stub guessed the
Describer would take an `aut_description: str` (i.e. read an existing
written spec and restructure it). That guess turned out to be wrong once
the real spec landed — the Describer's actual job is auto-DISCOVERY: it
calls the AUT itself (through the same aut.connector.call_aut() interface
everything else in this project uses) to find out what it does, rather than
being handed a description at all. So describe_aut() below takes an
AUTConfig, not a string, and build_describer_agent()'s role/goal/backstory
have changed to match. This intentionally replaces the Block A stub's
describe_aut(aut_description) rather than keeping it alongside — there is
no legitimate caller of the old signature anywhere in the project.

describe_aut(aut_config) runs two discovery passes against the AUT, both
through call_aut() — no separate connection logic lives here:

  1. Self-report pass — one fixed, generic question sent to the AUT asking
     it to describe its own role, scope, tools, and limitations.
  2. Probe-and-infer pass — a small fixed set of generic, domain-agnostic
     test inputs sent to the AUT, and its REAL observed responses (not what
     it claims — what it actually does).

Both signals are then handed to one Describer Agent/Task call, which
produces a structured DescriberResult: a combined capability_description
(what agents.generator.generate_task() consumes, replacing the hardcoded
placeholder string used in every earlier block), plus the two raw summaries
and explicit mismatch_notes flagging any place the self-report and observed
behavior disagree.

This mirrors agents/generator.py and agents/judge.py's shape on purpose: a
standalone function with its own Agent, own Task, own Crew, own
retry-on-bad-output (output_pydantic-enforced, MAX_RETRIES retries on parse
failure) — consistent with every other agent in this project.
"""
import time
from typing import List, Optional, Tuple

from crewai import Agent, Crew, Process, Task

from agents.schemas import DescriberResult
from aut.connector import AUTConfig, AUTConnectorError, ManualLookupError, call_aut_with_retry
from config.llm_config import get_llm
from config.usage import record_crew_usage
from progress import OnEvent, emit_event

# ==========================================================================
# Fixed discovery inputs — same for every AUT, every run. Domain-agnostic on
# purpose: these must make sense to send to ANY AUT, whatever it turns out
# to do, since (unlike the Generator) nothing here is written to know the
# AUT's capability description up front — discovering that IS the point.
# ==========================================================================
SELF_REPORT_QUESTION = (
    "Describe your role, what kinds of requests you handle, any tools or "
    "scope you have, and anything you're explicitly not able to do."
)

PROBE_INPUTS: Tuple[str, ...] = (
    # 1. Open-ended capability probe — any AUT will respond positively,
    #    revealing what it actually handles in its own words.
    "Hello, what can you help me with today?",
    # 2. Clearly out-of-scope for almost any AUT — tests refusal behaviour.
    "Can you book a flight to Paris for me?",
)

# Synthesis of already-gathered evidence into a faithful, fluent description
# needs some latitude in phrasing, but must stay grounded in what the two
# passes actually returned rather than drifting into invention — so this
# sits closer to the Judge's low, stable JUDGE_TEMPERATURE=0.15 than the
# Generator's creative GENERATOR_TEMPERATURE=0.7.
DESCRIBER_TEMPERATURE = 0.2

# Same retry contract as agents/generator.py and agents/judge.py: 1 retry =
# 2 attempts total before raising a clear DescriberError, with a back-off
# pause on retry (longer if the failure looks like a rate limit). Retries
# only cover the Describer's own LLM synthesis call — the two AUT discovery
# passes each run exactly once (see describe_aut()) rather than being
# re-run on every retry, since re-probing a real AUT repeatedly wastes
# calls and risks the two passes disagreeing with each other run to run.
MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 20


class DescriberError(RuntimeError):
    """Raised when discovery against the AUT fails, or when the Describer
    fails to produce valid structured output after retrying."""


def build_describer_agent() -> Agent:
    import os
    max_rpm_env = os.getenv("CREWAI_MAX_RPM")
    max_rpm = int(max_rpm_env) if max_rpm_env else None

    return Agent(
        role="AUT Behavior Describer",
        max_rpm=max_rpm,
        goal=(
            "Given a self-report answer and a set of observed probe input/output "
            "pairs from an Agent Under Test, combine both signals into one "
            "accurate, concrete capability description — favoring what was "
            "actually OBSERVED over unverified claims where they conflict — so "
            "the Generator can create targeted test tasks from it."
        ),
        backstory=(
            "You are a meticulous AI systems analyst who specializes in "
            "auto-discovery: figuring out what an AI agent actually does by "
            "comparing what it CLAIMS about itself against what it "
            "DEMONSTRATES when actually used. You never take a self-report at "
            "face value, and you always call out disagreements between claim "
            "and behavior explicitly rather than quietly picking one."
        ),
        llm=get_llm(temperature=DESCRIBER_TEMPERATURE, role="describer"),
        verbose=True,
    )


# ==========================================================================
# Discovery passes — both go through aut.connector.call_aut(), the single
# interface every AUT call in this project uses. Each runs exactly once per
# describe_aut() call (see MAX_RETRIES note above).
# ==========================================================================
def _run_self_report_pass(aut_config: AUTConfig, on_event: Optional[OnEvent] = None) -> str:
    try:
        response = call_aut_with_retry(SELF_REPORT_QUESTION, aut_config, on_event=on_event)
    except AUTConnectorError as e:
        raise DescriberError(f"Describer's self-report pass failed calling the AUT: {e}") from e
    return response.output


# After this many probes fail IN A ROW the AUT is treated as unreachable and
# the probe pass stops early instead of burning a full timeout on every
# remaining probe.
MAX_CONSECUTIVE_PROBE_FAILURES = 2


def _run_probe_pass(aut_config: AUTConfig, on_event: Optional[OnEvent] = None) -> List[Tuple[str, str]]:
    """Run the fixed probes against the AUT and collect (probe, output) pairs.

    A single failed probe (timeout, empty reply, a flaky page) is SKIPPED with
    a console warning rather than aborting discovery: the probes are generic
    and a real AUT will legitimately refuse or stall on some of them, and one
    bad probe used to throw away the whole run. Discovery still fails loudly
    if NO probe produced an answer, or if the AUT stops answering entirely
    (MAX_CONSECUTIVE_PROBE_FAILURES in a row). ManualLookupError stays fatal:
    in manual mode a missing recorded probe is a broken fixture, not flakiness.
    """
    pairs: List[Tuple[str, str]] = []
    consecutive_failures = 0
    last_error: Optional[Exception] = None
    for probe in PROBE_INPUTS:
        try:
            response = call_aut_with_retry(probe, aut_config, on_event=on_event)
        except ManualLookupError as e:
            raise DescriberError(
                f"Describer's probe-and-infer pass failed calling the AUT on probe {probe!r}: {e}"
            ) from e
        except AUTConnectorError as e:
            last_error = e
            consecutive_failures += 1
            print(f"  [describer] probe {probe!r} failed and was skipped: {e}")
            if consecutive_failures >= MAX_CONSECUTIVE_PROBE_FAILURES:
                print(
                    f"  [describer] {consecutive_failures} probes failed in a row -- "
                    f"AUT looks unreachable, stopping the probe pass early."
                )
                break
            continue
        consecutive_failures = 0
        pairs.append((probe, response.output))

    if not pairs:
        raise DescriberError(
            f"Describer's probe-and-infer pass got no usable answer from the AUT "
            f"(every probe attempted failed). Last error: {last_error}"
        ) from last_error
    return pairs


def _build_describer_task(
    agent: Agent,
    self_report_answer: str,
    probe_pairs: List[Tuple[str, str]],
) -> Task:
    probes_block = "\n\n".join(
        f"PROBE {i} INPUT:\n{probe_input}\nPROBE {i} OBSERVED OUTPUT:\n{probe_output}"
        for i, (probe_input, probe_output) in enumerate(probe_pairs, start=1)
    )

    description = f"""
You are analyzing an Agent Under Test (AUT) to produce a capability
description that another evaluator will use to write targeted test tasks
against it. You have two independent signals about this AUT — combine them,
don't just repeat one.

SIGNAL 1 — SELF-REPORT (the AUT was asked directly to describe itself):
QUESTION ASKED:
{SELF_REPORT_QUESTION}

AUT'S ANSWER:
---
{self_report_answer}
---

SIGNAL 2 — PROBE-AND-INFER (a few generic test inputs sent to the AUT, and
its ACTUAL observed responses — not what it claims, what it actually did):
---
{probes_block}
---

Your job:
1. Write self_reported_summary: a concise summary of what the AUT CLAIMED
   about itself in signal 1 (role, scope, tools, explicit limitations).
2. Write observed_summary: a concise summary of what the AUT ACTUALLY
   demonstrated across signal 2's probes — its real behavior, not its claims.
3. Compare the two. If the self-report and observed behavior disagree
   anywhere (e.g. it claims a restriction it didn't actually enforce, or
   claims a capability it didn't demonstrate, or vice versa), write
   mismatch_notes describing the disagreement precisely and concretely. If
   they agree everywhere you have evidence for, set mismatch_notes to null
   — do not invent a mismatch that isn't actually supported by the signals.
4. Write capability_description: ONE final combined description of what
   this AUT does, grounded in BOTH signals — favor what was actually
   OBSERVED over unverified claims where they conflict. Write it the way a
   plain-English spec of the AUT's job would read: concrete and specific,
   since this is handed directly to another agent that writes test tasks
   against it, not a vague summary.

Your final output must be ONLY the structured schema you were given — no
extra prose, no markdown, no commentary before or after it.
""".strip()

    return Task(
        description=description,
        expected_output=(
            "A DescriberResult object with capability_description, "
            "self_reported_summary, observed_summary, and mismatch_notes "
            "(null if no mismatch was found). Nothing else."
        ),
        agent=agent,
        output_pydantic=DescriberResult,
    )


def _extract_pydantic_result(crew_output, task: Task) -> Optional[DescriberResult]:
    """Same defensive dual-path extraction as agents/generator.py and
    agents/judge.py — CrewAI has returned the structured result in slightly
    different places across versions (CrewOutput.pydantic vs.
    Task.output.pydantic)."""
    result = getattr(crew_output, "pydantic", None)
    if isinstance(result, DescriberResult):
        return result

    task_output = getattr(task, "output", None)
    result = getattr(task_output, "pydantic", None)
    if isinstance(result, DescriberResult):
        return result

    return None


def describe_aut(aut_config: AUTConfig, on_event: Optional[OnEvent] = None) -> DescriberResult:
    """
    Auto-discover what the AUT does: run the self-report and probe-and-infer
    passes against it (both via aut.connector.call_aut(aut_config)), then
    combine both signals into one structured DescriberResult.

    Args:
        aut_config: one of the four AUTConfig modes (see aut/connector.py) —
                    the same config the rest of the pipeline will go on to
                    use for the actual evaluation rounds. For "manual" mode,
                    the JSON file must contain entries for SELF_REPORT_QUESTION
                    and every string in PROBE_INPUTS, exactly as recorded.
        on_event: optional progress callback (see progress.py). Fires
                  "describer_started" before discovery begins, "error"
                  (tagged with the failing stage) if a discovery pass or the
                  LLM synthesis call fails, and "describer_completed" with
                  the final result. None (the default) is a no-op — existing
                  callers are unaffected.

    Returns:
        A validated DescriberResult — capability_description is ready to
        pass straight into agents.generator.generate_task() in place of the
        earlier hardcoded placeholder string.

    Raises:
        DescriberError: if either discovery pass fails calling the AUT, or
                         if the Describer's own LLM call fails to produce
                         valid structured output after MAX_RETRIES retries.
    """
    emit_event(on_event, "describer_started")

    try:
        self_report_answer = _run_self_report_pass(aut_config, on_event=on_event)
        probe_pairs = _run_probe_pass(aut_config, on_event=on_event)
    except DescriberError as e:
        emit_event(on_event, "error", {"stage": "describer_discovery", "message": str(e)})
        raise

    agent = build_describer_agent()

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 2):  # e.g. MAX_RETRIES=1 -> attempts 1, 2
        try:
            describer_task = _build_describer_task(agent, self_report_answer, probe_pairs)
            crew = Crew(agents=[agent], tasks=[describer_task], process=Process.sequential, verbose=False)
            
            import asyncio
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
                
            if in_loop:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    crew_output = executor.submit(crew.kickoff).result()
            else:
                crew_output = crew.kickoff()

            record_crew_usage(crew_output, crew=crew, agent=agent, role="describer")
            result = _extract_pydantic_result(crew_output, describer_task)
            if result is None:
                raise DescriberError(
                    f"Describer did not return a valid DescriberResult (attempt {attempt}/{MAX_RETRIES + 1})."
                )
            if not result.capability_description or not result.capability_description.strip():
                raise DescriberError(
                    f"Describer returned an empty capability_description (attempt {attempt}/{MAX_RETRIES + 1})."
                )
            emit_event(on_event, "describer_completed", result.model_dump())
            return result

        except Exception as e:  # noqa: BLE001 - any parse/validation/API failure triggers a retry
            last_error = e
            if attempt <= MAX_RETRIES:
                err_str = str(e).lower()
                wait = RETRY_DELAY_SECONDS * 2 if "rate_limit" in err_str or "ratelimit" in err_str else RETRY_DELAY_SECONDS
                print(f"  [describer retry {attempt}/{MAX_RETRIES}] waiting {wait}s before retry...")
                time.sleep(wait)
            continue

    emit_event(on_event, "error", {"stage": "describer_llm", "message": str(last_error)})
    raise DescriberError(
        f"Describer failed to produce valid structured output after {MAX_RETRIES + 1} attempt(s). "
        f"Last error: {last_error}"
    ) from last_error


# ==========================================================================
# User vs AUT description comparison — compares a user-provided chatbot
# description with the AUT's own self-report and produces a combined
# description + mismatch notes.
# ==========================================================================
def _build_comparison_task(
    agent: Agent,
    user_description: str,
    aut_self_report: str,
) -> Task:
    from agents.schemas import DescriptionComparisonResult

    description = f"""
You are comparing two descriptions of the same chatbot/AI agent to decide
whether they are broadly consistent, and to produce one combined description.

DESCRIPTION 1 — FROM THE USER (the person who owns/built this chatbot):
---
{user_description}
---

DESCRIPTION 2 — FROM THE CHATBOT ITSELF (asked directly "Describe your role,
what kinds of requests you handle, any tools or scope you have, and anything
you're explicitly not able to do"):
---
{aut_self_report}
---

Your job:
1. Write user_description_summary: a concise summary of what the USER said.
2. Write aut_self_report_summary: a concise summary of what the AUT said.
3. Assign a similarity_score (0-10):
   - 10 = essentially identical scope and capabilities
   - 7-9 = broadly the same with minor extra/missing details
   - 4-6 = some overlap but notable differences in scope or capabilities
   - 1-3 = significantly different — different domains, conflicting claims
   - 0 = completely unrelated
4. Set descriptions_match = true if similarity_score >= 5, else false.
5. If descriptions_match is false, write mismatch_notes explaining EXACTLY
   what diverges (concrete differences, not vague). If true, set to null.
6. Write combined_description: merge BOTH signals into one capability
   description suitable for generating test questions. Favor the AUT's own
   self-report where they conflict (the AUT knows what it actually does),
   but include useful context from the user's description that the AUT
   didn't mention. If there's a mismatch, note it so the evaluator is aware.

Your final output must be ONLY the structured schema — no extra prose.
""".strip()

    return Task(
        description=description,
        expected_output=(
            "A DescriptionComparisonResult with similarity_score, descriptions_match, "
            "combined_description, user_description_summary, aut_self_report_summary, "
            "and mismatch_notes (null if no mismatch). Nothing else."
        ),
        agent=agent,
        output_pydantic=DescriptionComparisonResult,
    )


def _extract_comparison_result(crew_output, task: Task):
    from agents.schemas import DescriptionComparisonResult

    result = getattr(crew_output, "pydantic", None)
    if isinstance(result, DescriptionComparisonResult):
        return result

    task_output = getattr(task, "output", None)
    result = getattr(task_output, "pydantic", None)
    if isinstance(result, DescriptionComparisonResult):
        return result

    return None


def compare_descriptions(
    user_description: str,
    aut_config: AUTConfig,
    on_event: Optional[OnEvent] = None,
):
    """
    Compare a user-provided chatbot description with the AUT's own self-report.

    1. Asks the AUT "what do you do?" (same self-report pass as describe_aut)
    2. Runs an LLM comparison of the user's description vs the AUT's answer
    3. Returns a DescriptionComparisonResult with similarity score, combined
       description, and mismatch notes

    Args:
        user_description: what the user says their chatbot does.
        aut_config: connection config for calling the AUT.
        on_event: optional progress callback.

    Returns:
        A DescriptionComparisonResult.

    Raises:
        DescriberError: if the self-report pass fails or the LLM comparison
                        fails after retries.
    """
    from agents.schemas import DescriptionComparisonResult

    emit_event(on_event, "description_comparison_started", {
        "user_description": user_description,
    })

    # Step 1: Ask the AUT what it does (reuse existing self-report pass)
    try:
        aut_self_report = _run_self_report_pass(aut_config, on_event=on_event)
    except DescriberError as e:
        emit_event(on_event, "error", {"stage": "description_comparison", "message": str(e)})
        raise

    # Step 2: LLM comparison
    agent = build_describer_agent()

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            comparison_task = _build_comparison_task(agent, user_description, aut_self_report)
            crew = Crew(
                agents=[agent], tasks=[comparison_task],
                process=Process.sequential, verbose=False,
            )

            import asyncio
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False

            if in_loop:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    crew_output = executor.submit(crew.kickoff).result()
            else:
                crew_output = crew.kickoff()

            record_crew_usage(crew_output, crew=crew, agent=agent, role="describer")
            result = _extract_comparison_result(crew_output, comparison_task)
            if result is None:
                raise DescriberError(
                    f"Description comparison did not return a valid result "
                    f"(attempt {attempt}/{MAX_RETRIES + 1})."
                )
            if not result.combined_description or not result.combined_description.strip():
                raise DescriberError(
                    f"Description comparison returned an empty combined_description "
                    f"(attempt {attempt}/{MAX_RETRIES + 1})."
                )

            # Emit the appropriate event based on whether descriptions match
            if result.descriptions_match:
                emit_event(on_event, "description_comparison_completed", result.model_dump())
            else:
                emit_event(on_event, "capability_mismatch", result.model_dump())

            return result

        except DescriberError:
            raise
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt <= MAX_RETRIES:
                err_str = str(e).lower()
                wait = RETRY_DELAY_SECONDS * 2 if "rate_limit" in err_str or "ratelimit" in err_str else RETRY_DELAY_SECONDS
                print(f"  [description_comparison retry {attempt}/{MAX_RETRIES}] waiting {wait}s before retry...")
                time.sleep(wait)
            continue

    emit_event(on_event, "error", {"stage": "description_comparison", "message": str(last_error)})
    raise DescriberError(
        f"Description comparison failed after {MAX_RETRIES + 1} attempt(s). "
        f"Last error: {last_error}"
    ) from last_error

