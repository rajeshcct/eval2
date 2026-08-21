"""
backend/tests/test_ws_flow.py

End-to-end test of Phase II's FastAPI backend: connect to WS /ws/run, send
a SessionStartRequest, stream every event through to session_completed,
then reload the same report independently via
GET /api/sessions/{session_id}/report.

Uses FastAPI's TestClient (a real ASGI transport over httpx, not a mock),
so this exercises the actual app: a real asyncio.to_thread() worker, a real
asyncio.Queue bridged via loop.call_soon_threadsafe(), and a real WebSocket
handshake/close — none of the WS plumbing itself is faked.

Two things ARE swapped out, for the same reason tests/test_escalating_loop.py
and tests/test_aggregator.py swap them:

  1. pipeline.generate_task / pipeline.judge_round -> deterministic
     stand-ins (see those two files' own module docstrings) so this test
     can assert an EXACT event sequence instead of eyeballing free-form LLM
     output.
  2. aut.auth.build_authenticated_endpoint_config, as imported into
     backend.app.main, is patched to always return "manual" mode
     (ManualConfig(json_path=SAMPLE_MANUAL_PATH)) instead of actually
     building a CustomEndpointConfig. The WS *client* below still sends a
     normal AUTConnectionRequest payload — proving that part of the
     request schema/validation works end-to-end — but this test's whole
     point is to never make a real HTTP call to a chat_endpoint_url that
     doesn't exist. build_authenticated_endpoint_config()'s own real
     login/network behavior is already covered in isolation by
     tests/test_auth_wrapper.py; nothing further to prove about it here.

capability_description_override is set, so the Describer never runs either
— no real self-report/probe AUT calls, no real Describer LLM call.

What this test CANNOT avoid needing a real key for: aggregator.
build_final_report()'s own overall_verdict call, always real (see
aggregator.py's module docstring for why that one specific call is never
monkeypatched away anywhere in this project). So, exactly like
tests/test_aggregator.py, this whole script is SKIPPED (not failed) if
config.llm_config.is_configured() is False.

Run from the project root:
    python backend/tests/test_ws_flow.py
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python backend/tests/test_ws_flow.py` (no package
# install / -m needed) — same trick every tests/test_*.py file uses, just
# one directory deeper.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.judge import compute_passed  # noqa: E402
from agents.schemas import GeneratedTask, JudgeScore  # noqa: E402
from aut.connector import ManualConfig  # noqa: E402
from config.llm_config import is_configured  # noqa: E402
from db.store import init_db  # noqa: E402

SAMPLE_MANUAL_PATH = str(PROJECT_ROOT / "tests" / "sample_manual_outputs.json")

CAPABILITY_DESCRIPTION = (
    "This agent is a customer support bot for an online store handling "
    "orders, returns, and sizing questions."
)

# 2 rounds is enough to exercise every event type end-to-end using only
# tests/sample_manual_outputs.json's diff1/diff2 entries: functionality and
# compliance both PASS diff1 and diff2 (robust within this 2-round cap);
# security PASSes diff1 then FAILs diff2 (breaks at round 2).
MAX_ROUNDS = 2


# --------------------------------------------------------------------------
# Same deterministic Generator/Judge stand-ins as tests/test_escalating_loop.py
# and tests/test_aggregator.py.
# --------------------------------------------------------------------------
def _fake_generate_task(category: str, capability_description: str, difficulty: int) -> GeneratedTask:
    return GeneratedTask(task_text=f"{category}::diff{difficulty}", category=category, difficulty=difficulty)


def _fake_judge_round(task: str, output: str, category: str) -> JudgeScore:
    if "[[FAIL]]" in output:
        scores = dict(
            task_completion=2, security=3, compliance=3,
            accuracy=5, relevance=5, hallucination=5, safety=5,
        )
        reasoning = "Stubbed FAIL verdict for backend WS test (see module docstring)."
    elif "[[PASS]]" in output:
        scores = dict(
            task_completion=9, security=9, compliance=9,
            accuracy=9, relevance=9, hallucination=9, safety=9,
        )
        reasoning = "Stubbed PASS verdict for backend WS test (see module docstring)."
    else:
        raise AssertionError(f"recorded manual output for {task!r} has no [[PASS]]/[[FAIL]] marker: {output!r}")
    passed = compute_passed(category, scores["task_completion"], scores["security"], scores["compliance"])
    return JudgeScore(**scores, passed=passed, reasoning=reasoning)


def _fake_build_authenticated_endpoint_config(connection) -> ManualConfig:
    # Ignores whatever AUTConnectionRequest the client actually sent — see
    # module docstring for why. Real login/network behavior for this
    # function is already covered by tests/test_auth_wrapper.py.
    return ManualConfig(json_path=SAMPLE_MANUAL_PATH)


def main() -> None:
    print("=" * 78)
    print("Phase II — backend WS flow test")
    print("=" * 78)

    if not is_configured():
        print(
            "  Skipped — no LLM key configured for EvalMind's own agents "
            "(config/llm_config.py). Even with the Describer overridden and "
            "Generator/Judge stubbed, a full run_full_session() call still "
            "ends in aggregator.build_final_report()'s real overall_verdict "
            "LLM call (see tests/test_aggregator.py for the same caveat) — "
            "set LLM_PROVIDER + the matching *_API_KEY in .env to actually "
            "exercise this end to end."
        )
        return

    init_db()

    # Imported here (after sys.path is set up) so patch() targets the names
    # actually bound inside backend.app.main's own module namespace.
    from fastapi.testclient import TestClient
    from backend.app.main import app

    events = []
    session_id = None
    ok = True

    with patch("pipeline.generate_task", _fake_generate_task), \
         patch("pipeline.judge_round", _fake_judge_round), \
         patch("backend.app.main.build_authenticated_endpoint_config", _fake_build_authenticated_endpoint_config):

        client = TestClient(app)

        print("-" * 78)
        print("Connecting to /ws/run and sending SessionStartRequest...")
        print("-" * 78)

        start_message = {
            "connection": {
                # Deliberately fake/unreachable — build_authenticated_endpoint_config
                # is patched above, so this URL is never actually called.
                "chat_endpoint_url": "http://ignored.invalid/chat",
                "requires_login": False,
            },
            "max_rounds": MAX_ROUNDS,
            "capability_description_override": CAPABILITY_DESCRIPTION,
        }

        with client.websocket_connect("/ws/run") as websocket:
            websocket.send_json(start_message)
            while True:
                event = websocket.receive_json()
                events.append(event)
                print(f"  <- {event['type']}")
                if event["type"] in ("session_completed", "error"):
                    break

    types = [e["type"] for e in events]
    print(f"\n  event types received: {types}")

    expected_prefix = ["category_started", "round_started", "round_completed"]
    if types[: len(expected_prefix)] != expected_prefix:
        print(f"  [ERROR] expected to start with {expected_prefix}, got {types[: len(expected_prefix)]}")
        ok = False

    if not types or types[-1] != "session_completed":
        print(f"  [ERROR] expected the last event to be 'session_completed', got {types[-1] if types else None!r}")
        ok = False
    else:
        final_report_data = events[-1]["data"]
        session_id = final_report_data.get("session_id")
        if not session_id:
            print("  [ERROR] session_completed event's data has no session_id")
            ok = False
        for cat in ("functionality", "security", "compliance"):
            if cat not in final_report_data.get("categories", {}):
                print(f"  [ERROR] session_completed's FinalReport is missing category {cat!r}")
                ok = False
        security_status = final_report_data.get("categories", {}).get("security", {}).get("status")
        if security_status != "broken":
            print(f"  [ERROR] expected security status='broken', got {security_status!r}")
            ok = False

    print(f"\n  {'OK' if ok else 'FAILED'}  WS run streamed to session_completed\n")

    # ----------------------------------------------------------------
    # REST reload: GET /api/sessions/{session_id}/report, with none of the
    # WS connection's state — a fresh TestClient, no patches active.
    # ----------------------------------------------------------------
    reload_ok = True
    if session_id:
        print("-" * 78)
        print(f"Reloading via GET /api/sessions/{session_id}/report...")
        print("-" * 78)
        client2 = TestClient(app)
        response = client2.get(f"/api/sessions/{session_id}/report")
        print(f"  status_code={response.status_code}")
        if response.status_code != 200:
            print(f"  [ERROR] expected 200, got {response.status_code}: {response.text}")
            reload_ok = False
        else:
            reloaded = response.json()
            if reloaded.get("session_id") != session_id:
                print(f"  [ERROR] reloaded session_id mismatch: {reloaded.get('session_id')!r} != {session_id!r}")
                reload_ok = False
            if reloaded.get("categories", {}).get("security", {}).get("status") != "broken":
                print("  [ERROR] reloaded report's security status isn't 'broken'")
                reload_ok = False

        print(f"\n  {'OK' if reload_ok else 'FAILED'}  REST reload by session_id\n")

        print("-" * 78)
        print("Checking GET /api/sessions/{bogus-id}/report -> 404...")
        print("-" * 78)
        bogus_response = client2.get(f"/api/sessions/{uuid.uuid4()}/report")
        print(f"  status_code={bogus_response.status_code}")
        if bogus_response.status_code != 404:
            print(f"  [ERROR] expected 404 for an unknown session_id, got {bogus_response.status_code}")
            reload_ok = False
        print(f"\n  {'OK' if reload_ok else 'FAILED'}  404 for unknown session_id\n")
    else:
        reload_ok = False
        print("  Skipped REST reload check — no session_id was captured from the WS run.\n")

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  {'OK' if ok else 'FAILED'}  WS run event sequence + session_completed payload")
    print(f"  {'OK' if reload_ok else 'FAILED'}  REST reload (200 + matching data) and 404 for unknown id")

    if not (ok and reload_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
