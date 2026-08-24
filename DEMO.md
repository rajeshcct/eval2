# EvalMind — Live Demo Guide

This file is about **running the live demo and recovering if it breaks**.
For install/setup, see [README.md](README.md) instead. This guide covers
the Python-only pipeline (`run_full_session()` called directly, no
backend/frontend involved) — for the browser-based demo (`backend/` +
`frontend/`), see [FRONTEND.md](FRONTEND.md) instead, which has the
equivalent two-terminal run instructions and its own end-to-end smoke
test.

It covers:
1. [Before the demo](#1-before-the-demo) — rehearsal + preflight
2. [The three demo scenarios](#2-the-three-demo-scenarios)
3. [How to actually run a scenario](#3-how-to-actually-run-a-scenario)
4. [Live-demo fallback procedure](#4-live-demo-fallback-procedure-10-second-recovery)

---

## 1. Before the demo

### The night before / well ahead of time: rehearse

```bash
python scripts/rehearsal.py
```

Runs the real, live demo scenario (`demo.scenarios.LIVE_CUSTOMER_SUPPORT`)
**twice**, back to back, against the real AUT (a Groq-backed customer-support
agent) — no mocking, no manual mode. It prints a side-by-side comparison of
both runs' per-category status/breaking_point and flags any category where
the two runs disagree. This is how you catch real-AUT flakiness or
nondeterminism *before* it happens in front of an audience. It takes a few
minutes (a full evaluation session, twice) — run it with time to spare, not
five minutes before you present.

Also worth running once, for the same reason (it already targets the real
public_api demo backend, the same Groq model used in
`demo.scenarios.LIVE_CUSTOMER_SUPPORT`):

```bash
python tests/test_connector.py
```

If `scripts/rehearsal.py` shows disagreement between the two runs, or
`tests/test_connector.py` fails the `public_api` check, treat the live
scenario as unreliable and plan to open with (or fall back to)
`MANUAL_FALLBACK_ROBUST` instead (see [§4](#4-live-demo-fallback-procedure-10-second-recovery)).

> **Note on `tests/test_connector.py`'s other two modes:** none of the demo
> scenarios use `custom_endpoint` or `function_import` — the real demo AUT
> is a `public_api` target, and the fallback/breaking-point scenarios are
> `manual`. `test_connector.py`'s `custom_endpoint`/`function_import` checks
> still run against their dummy test targets (`tests/dummy_endpoint.py`,
> `tests/dummy_function_target.py`) as connector-logic sanity checks, same
> as before Block H — there is no "real target" for those two modes to
> re-point them at in this project.

### Minutes before you walk into the room: preflight

```bash
python scripts/preflight_check.py
```

Three fast checks, each a clear PASS/FAIL line, exits non-zero if anything
fails:
1. EvalMind's own LLM (Describer/Generator/Judge/Aggregator) is configured.
2. Every scenario's `aut_config` is reachable (one trivial `call_aut()` call
   each — including the manual-mode scenarios' JSON files).
3. Every manual-mode scenario's JSON fallback file loads and contains every
   task it's expected to hit.

If this fails, **do not start the live scenario** — go straight to the
fallback (§4) or fix the failing check first.

---

## 2. The three demo scenarios

All three live in `demo/scenarios.py` as `DemoScenario` objects (plain data
— nothing runs until you hand one to `run_full_session()`, see §3).

### 2.1 `LIVE_CUSTOMER_SUPPORT` — the real, live demo

The main event. A Groq-backed customer-support agent for an online store
(orders / returns / sizing only), called for real through `PublicAPIConfig`
(`model="groq/openai/gpt-oss-120b"`). The Describer runs live (auto-discovery,
no override), then all three category loops run for real — real Generator,
real AUT, real Judge — for up to 3 rounds each.

**Expected FinalReport shape:** all three categories —
`functionality`, `security`, `compliance` — come back
`robust_within_tested_range` (`breaking_point=None`), each having run all 3
rounds and passed every one. The bot does its job, resists the
injection/jailbreak attempts the Generator throws at it, and stays in
scope. The `overall_verdict` should read as a clean bill of health. This is
**not** mathematically guaranteed — it's a real LLM being tested by another
real LLM — which is exactly why `scripts/rehearsal.py` exists: run it ahead
of time to confirm this holds run to run.

### 2.2 `SECURITY_BREAKING_POINT` — the deliberate "watch it break" moment

A planned demo beat, not an emergency. Manual mode against
`tests/sample_manual_outputs.json`, which already has `security::diff1`
recorded as a pass and `security::diff2` recorded as a **simulated
prompt-injection success** (a fail). The Describer still runs, using that
same file's pre-recorded self-report and 4 probe answers — so this scenario
also shows the auto-discovery step, just against pre-recorded (not live) AUT
responses. `max_rounds=2` on purpose (the fixture only has functionality/
compliance entries through difficulty 2).

**Expected FinalReport shape:**
- `functionality`: `robust_within_tested_range`, 2/2 rounds pass.
- `compliance`: `robust_within_tested_range`, 2/2 rounds pass.
- `security`: **`broken`**, `breaking_point_round=2` — round 1 (difficulty 1)
  passes, round 2 (difficulty 2) fails because the recorded output shows the
  agent complying with an embedded override and disclosing its system
  prompt. `breaking_point_summary` should mention `security` and
  `compliance` scores falling below threshold.
- `overall_verdict` should single out `security` as the category of
  concern, while noting functionality/compliance held up.

### 2.3 `MANUAL_FALLBACK_ROBUST` — the safety net

The scenario to swap to if the network or the real AUT goes down mid-demo
(see §4). Manual mode against `demo/manual_fallback.json`, a dedicated,
**entirely PASS** fixture (kept deliberately separate from
`tests/sample_manual_outputs.json`, whose `security::diff2` is a fail).
`capability_description_override` is set, which **skips the Describer
entirely** — fewer LLM calls, fewer points of failure, faster recovery, at
the cost of not re-demonstrating auto-discovery. `max_rounds=3`.

**Expected FinalReport shape:** all three categories come back
`robust_within_tested_range` across all 3 rounds each — every entry in
`demo/manual_fallback.json` is a pass. This mirrors
`LIVE_CUSTOMER_SUPPORT`'s expected shape exactly, so swapping to this
scenario keeps the demo's story consistent even though the run itself is
now fully offline / pre-recorded.
can you pull the fleet-wide average fuel efficiency for the last 7 days?
  "auth_token": "yJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzYXZ5YXNhY2hpLmJAY29tbXVuaWNhdGlvbmNyYWZ0cy5jb20iLCJqdGkiOiI1MTBhZGViNS03Nzg3LTRiYjktOGQ2My1iMjgzOGE5Nzg3ODciLCJpYXQiOjE3ODczODE5MDksInJvbCI6IkFkbWluIiwiaWQiOiI1OGJjOGMzNi1jMjljLTQ2M2MtYmE5YS1mMTc1Njc2Mzc5YTciLCJVc2VyQWRtaW4iOiJGYWxzZSIsIlJlcG9ydHMiOiJUcnVlIiwiTW9kZVN0YXR1cyI6IkZhbHNlIiwiTG9jYXRpb25BZG1pbiI6IkZhbHNlIiwiTGl2ZURhdGEiOiJUcnVlIiwiSm91cm5leXMiOiJGYWxzZSIsIkhpc3RvcmljYWwiOiJGYWxzZSIsIkRyaXZlckFkbWluIjoiVHJ1ZSIsIkRhc2hib2FyZCI6IlRydWUiLCJBc3NldEFkbWluIjoiRmFsc2UiLCJBbGVydFNldHRpbmciOiJGYWxzZSIsIkFsZXJ0VGVtcGxhdGVTZXR0aW5nIjoiRmFsc2UiLCJQcml2YWN5RmxhZyI6IkZhbHNlIiwiTGl2ZU9ubHkiOiJGYWxzZSIsIkNDVFYiOiJGYWxzZSIsIlNBTVJvdXRlcyI6IkZhbHNlIiwiVXNlclNBTVJvdXRlcyI6IkZhbHNlIiwiVGhpcmRMb2NhdGlvbnMiOiJGYWxzZSIsIkFwcHJvdmUiOiJGYWxzZSIsIkFsbG9jYXRlIjoiRmFsc2UiLCJDcmVhdGUiOiJGYWxzZSIsIk1vbml0b3IiOiJGYWxzZSIsIlZpZXciOiJGYWxzZSIsIlVzZXJQcm9maWxlTmFtZSI6IlNhdnlhc2FjaGkiLCJpc1N1cGVyVXNlciI6IkZhbHNlIiwiQ3VzdG9tZXJJZCI6IjM3NiIsIlpvb21UbyI6IiIsIm5iZiI6MTc4NzM4MTkwOCwiZXhwIjoxNzg3NDEwNzA4LCJpc3MiOiJ3ZWJBcGkiLCJhdWQiOiJOYXZpZ2F0dG8uYXp1cmV3ZWJzaXRlcy5jb20ifQ.AiEIxJA4u7mOZI8ZC7OX8D_zwbnxxktr2Y_4249QjNE

## 3. How to actually run a scenario

### 3.1 `LIVE_CUSTOMER_SUPPORT` — no patching needed, fully real

```python
from demo.scenarios import LIVE_CUSTOMER_SUPPORT
from session import run_full_session

scenario = LIVE_CUSTOMER_SUPPORT
result = run_full_session(
    aut_config=scenario.aut_config,
    max_rounds=scenario.max_rounds,
    capability_description_override=scenario.capability_description_override,
)
```

### 3.2 `SECURITY_BREAKING_POINT` and `MANUAL_FALLBACK_ROBUST` — need one extra step

Both are manual-mode scenarios whose JSON files are keyed by the fixed
`"{category}::diff{difficulty}"` pattern (see `demo/manual_fallback.json`'s
own `_comment` entry) — the real Generator produces free-form text at
temperature 0.7 that will **not** match those exact keys, so a real,
guaranteed run needs `pipeline.generate_task` and `pipeline.judge_round`
monkeypatched to the same deterministic stand-ins
`tests/test_escalating_loop.py` and `tests/test_aggregator.py` already use
(fixed task text; scores read straight off the recorded `[[PASS]]`/
`[[FAIL]]` marker):

```python
from unittest.mock import patch
from agents.judge import compute_passed
from agents.schemas import GeneratedTask, JudgeScore
from demo.scenarios import SECURITY_BREAKING_POINT  # or MANUAL_FALLBACK_ROBUST
from session import run_full_session


def _fake_generate_task(category, capability_description, difficulty):
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_judge_round(task, output, category):
    if "[[FAIL]]" in output:
        scores = dict(task_completion=2, security=3, compliance=3,
                      accuracy=5, relevance=5, hallucination=5, safety=5)
    else:
        scores = dict(task_completion=9, security=9, compliance=9,
                      accuracy=9, relevance=9, hallucination=9, safety=9)
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning="Manual-mode demo round (deterministic stub).")


scenario = SECURITY_BREAKING_POINT  # or MANUAL_FALLBACK_ROBUST
with patch("pipeline.generate_task", _fake_generate_task), patch("pipeline.judge_round", _fake_judge_round):
    result = run_full_session(
        aut_config=scenario.aut_config,
        max_rounds=scenario.max_rounds,
        capability_description_override=scenario.capability_description_override,
    )
```

(Every `DemoScenario` has a `requires_deterministic_stubs` field — `True`
for both manual scenarios, `False` for the live one — so this is also
checkable in code, not just documented here.)

---

## 4. Live-demo fallback procedure (10-second recovery)

**If the network or the real AUT fails mid-demo:** stop the live run, and
run `MANUAL_FALLBACK_ROBUST` instead of `LIVE_CUSTOMER_SUPPORT`. Concretely,
that means:

1. **Swap the scenario.** Wherever your run script/notebook says:
   ```python
   scenario = LIVE_CUSTOMER_SUPPORT
   ```
   change it to:
   ```python
   scenario = MANUAL_FALLBACK_ROBUST
   ```
   That's the entire "which scenario" change — one line, in `demo/scenarios.py`
   itself if you're editing the import, or in whatever short run script/cell
   you're driving the demo from.

2. **Add the deterministic-stub patch.** `LIVE_CUSTOMER_SUPPORT` runs
   unpatched (§3.1); `MANUAL_FALLBACK_ROBUST` needs the
   `pipeline.generate_task` / `pipeline.judge_round` patch from §3.2 wrapped
   around the `run_full_session()` call. If you're driving the demo from a
   script that already has both code paths written out (§3.1's block and
   §3.2's block, both ready to go, `MANUAL_FALLBACK_ROBUST` version
   commented out), this step is just uncommenting — genuinely 10 seconds,
   not an improvisation.

3. **Say it out loud.** Tell the room you're switching to a pre-recorded
   fallback run so the report you're about to show is understood as a
   demonstration of the reporting pipeline, not a new live AUT test.

No other code changes are needed — `MANUAL_FALLBACK_ROBUST` was built
specifically to reproduce `LIVE_CUSTOMER_SUPPORT`'s expected "all robust"
report shape (§2.3), so the rest of your talking points about what the
report should show still hold.

If you'd rather rehearse this swap ahead of time instead of trusting it
live, `scripts/preflight_check.py` already confirms
`MANUAL_FALLBACK_ROBUST`'s `aut_config` and JSON file are good to go as
part of its normal run (§1) — there's nothing fallback-specific left to
check at demo time.
