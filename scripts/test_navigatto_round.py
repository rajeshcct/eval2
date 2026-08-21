"""
scripts/test_navigatto_round.py

Quick manual test: run ONE EvalMind round (Generator -> Navigatto -> Judge)
against the real Navigatto AUT over Socket.IO.

Before running:
  1. Get a fresh JWT for Navigatto by logging into YOUR auth system
     (the customer login, e.g. assetcct.navigatto.ai) manually in a browser,
     then copying the token out of DevTools (Network tab -> Authorization
     header, or localStorage['access_token']).
  2. Put that token in your .env file as NAVIGATTO_JWT=<token>
     (never hardcode it here, never commit it).
  3. Make sure LLM_PROVIDER + the matching API key are set in .env too,
     since Generator/Judge need an LLM to run.
  4. Set NAVIGATTO_WS_URL in .env if it's not the default below.

Run:
    python scripts/test_navigatto_round.py
"""
import os
import sys
from pathlib import Path

# Let this script be run from anywhere in the project.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from aut.connector import SocketIOEndpointConfig
from pipeline import run_single_round


def main():
    token = os.getenv("NAVIGATTO_JWT")
    if not token:
        print(
            "ERROR: NAVIGATTO_JWT not set in .env.\n"
            "Log into your auth system manually, copy the JWT, and add:\n"
            "  NAVIGATTO_JWT=<token>\n"
            "to your .env file, then re-run this script."
        )
        return

    ws_url = os.getenv("NAVIGATTO_WS_URL", "https://navigattodev.azurewebsites.net")

    aut_config = SocketIOEndpointConfig(
        url=ws_url,
        bearer_token=token,
        origin_header="https://assetcct.navigatto.ai",  # must match the real frontend origin
        # Adjust these two if integration3.md's event names differ from
        # the connector's defaults for your deployment:
        # socketio_path="/socket.io/",
        # chat_message_event="chat_message",
        persist_thread=False,
        connect_timeout_seconds=15.0,
        response_timeout_seconds=120.0,
    )

    from session import run_full_session

    print(f"Connecting to {ws_url} and running a 2-round full session with HARDCODED description...\n")

    result = run_full_session(
        aut_config=aut_config,
        max_rounds=2,
        capability_description_override=(
            "An assistant specialized in fleet analytics, reports, and vehicle/driver data. "
            "While it rejects general out-of-domain queries (such as shopping, coding, or weather), "
            "it is capable of providing system navigation and account management support, "
            "including directing users to specific platform URLs like the Navigatto user management page."
        )
    )

    print("=== Session result ===")
    print(f"Session ID: {result.session_id}")
    print(f"Auto-discovered capability description:\n  {result.capability_description}")
    
    cats = result.final_report.categories.values()
    total_rounds = sum(len(c.round_history) for c in cats)
    total_passed = sum(r.passed for c in cats for r in c.round_history)
    print(f"Total passed: {total_passed} / {total_rounds}")


if __name__ == "__main__":
    main()
