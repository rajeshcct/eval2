"""
main.py

EvalMind entry point — foundation stage only.

This does NOT run a real evaluation yet (Generator/Judge task logic isn't
implemented). It exists to prove the pieces built so far — config, DB layer,
agent stubs — import and wire together cleanly, with or without an LLM API
key configured.

Run it as the project's smoke test:
    python main.py
"""
import uuid

from config.llm_config import is_configured
from db.store import init_db, insert_session, get_rounds_for_session

# Agent builders — importing these does NOT require an API key.
from agents.describer import build_describer_agent
from agents.generator import build_generator_agent
from agents.judge import build_judge_agent


def main():
    print("=== EvalMind — foundation smoke test ===")

    configured = is_configured()
    print(f"LLM configured: {configured}")
    if not configured:
        print(
            "  (expected during early development — copy .env.example to .env "
            "and set OPENAI_API_KEY or ANTHROPIC_API_KEY when ready)"
        )

    # --- DB layer ---
    init_db()
    print("Database initialized (db/evalmind.db).")

    session_id = str(uuid.uuid4())
    insert_session(session_id, aut_description="Smoke-test placeholder AUT")
    rounds = get_rounds_for_session(session_id)
    print(f"Session '{session_id}' created; {len(rounds)} rounds recorded so far.")

    # --- Agent construction (only if a key is configured) ---
    if configured:
        describer = build_describer_agent()
        generator = build_generator_agent()
        judge = build_judge_agent()
        print(f"Agents built: {describer.role}, {generator.role}, {judge.role}")
    else:
        print("Skipping agent construction — no LLM key configured yet.")

    # TODO (next steps, in order):
    #   1. Implement aut/ — the plain-Python interface for calling the AUT.
    #   2. Implement agents/generator.py's generate_tasks() task logic.
    #   3. Implement agents/judge.py's judge_round() task logic (next step).
    #   4. Wire Describer -> Generator -> AUT -> Judge -> db.store.insert_round
    #      into a real evaluation run here in main().

    print("=== Smoke test complete ===")


if __name__ == "__main__":
    main()
