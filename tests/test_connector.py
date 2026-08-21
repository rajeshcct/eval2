"""
tests/test_connector.py

Manual sanity-check script for aut/connector.py — NOT a pytest suite. It
calls call_aut() once through each of the four modes against a real test
target, prints the full AUTResponse for each, and confirms none of the four
crash and all return the same response shape.

Test targets used (see aut/connector.py's own docstring for mode details):
  - public_api:       a small Groq-backed customer-support agent. Needs a
                       real GROQ_API_KEY in .env; skipped with a clear
                       message (not a failure) if it isn't set, so this
                       script still runs end-to-end with zero keys configured.
  - custom_endpoint:   tests/dummy_endpoint.py, started here in-process on a
                       background thread and shut down at the end.
  - function_import:   tests/dummy_function_target.dummy_agent — exercised
                       BOTH as an already-imported callable and via the
                       module_path + function_name dotted-reference form.
  - manual:            tests/sample_manual_outputs.json. Per the spec this
                       mode is the guaranteed live-demo fallback, so it's
                       tested most thoroughly here: a lookup by full task
                       text, a lookup by task id, a missing-task error, and
                       a missing-file error.

Run from the project root:
    python tests/test_connector.py
"""
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_connector.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aut.connector import (  # noqa: E402
    AUTConnectorError,
    AUTResponse,
    CustomEndpointConfig,
    FunctionImportConfig,
    ManualConfig,
    ManualLookupError,
    PublicAPIConfig,
    call_aut,
)
from tests.dummy_endpoint import DEFAULT_PORT, start_server  # noqa: E402
from tests.dummy_function_target import dummy_agent  # noqa: E402

SAMPLE_MANUAL_PATH = str(Path(__file__).parent / "sample_manual_outputs.json")
SAMPLE_TASK = "What's your return policy on shoes?"


def _print_response(label: str, response: AUTResponse) -> None:
    print(f"--- {label} ---")
    print(f"  output:         {response.output!r}")
    print(f"  latency_ms:     {response.latency_ms}")
    print(f"  tokens_used:    {response.tokens_used}")
    print(f"  estimated_cost: {response.estimated_cost}")
    print()


# --------------------------------------------------------------------------
# public_api
# --------------------------------------------------------------------------
def test_public_api() -> bool:
    print("=" * 78)
    print("MODE: public_api")
    print("=" * 78)

    if not os.getenv("GROQ_API_KEY", "").strip():
        print(
            "  Skipped — GROQ_API_KEY is not set in .env. Set it (see .env.example) "
            "to actually exercise this mode.\n"
        )
        return True

    config = PublicAPIConfig(
        system_prompt=(
            "You are a customer support agent for an online store, you only "
            "handle orders, returns, and sizing questions."
        ),
        model="groq/openai/gpt-oss-120b",
    )
    try:
        response = call_aut(SAMPLE_TASK, config)
    except Exception as e:  # noqa: BLE001 - this script reports, never crashes, on failure
        print(f"  [ERROR] public_api mode raised: {e}\n")
        return False

    _print_response("public_api", response)
    return True


# --------------------------------------------------------------------------
# custom_endpoint
# --------------------------------------------------------------------------
def test_custom_endpoint() -> bool:
    print("=" * 78)
    print("MODE: custom_endpoint")
    print("=" * 78)

    server, thread = start_server(DEFAULT_PORT)
    try:
        config = CustomEndpointConfig(url=f"http://127.0.0.1:{DEFAULT_PORT}")
        try:
            response = call_aut(SAMPLE_TASK, config)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] custom_endpoint mode raised: {e}\n")
            return False

        _print_response("custom_endpoint", response)

        expected = f"Echo: {SAMPLE_TASK}"
        if response.output != expected:
            print(f"  [ERROR] expected output {expected!r}, got {response.output!r}\n")
            return False
        return True
    finally:
        server.shutdown()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# function_import
# --------------------------------------------------------------------------
def test_function_import() -> bool:
    print("=" * 78)
    print("MODE: function_import (direct callable)")
    print("=" * 78)

    config = FunctionImportConfig(function=dummy_agent)
    try:
        response = call_aut(SAMPLE_TASK, config)
    except Exception as e:  # noqa: BLE001
        print(f"  [ERROR] function_import mode raised: {e}\n")
        return False

    _print_response("function_import (direct callable)", response)

    ok = True
    expected = f"Handled: {SAMPLE_TASK}"
    if response.output != expected:
        print(f"  [ERROR] expected output {expected!r}, got {response.output!r}\n")
        ok = False
    if response.tokens_used is not None or response.estimated_cost is not None:
        print("  [ERROR] expected tokens_used/estimated_cost to be None for a plain function\n")
        ok = False
    return ok


def test_function_import_dotted_path() -> bool:
    """Also exercise the module_path/function_name form, not just an
    already-imported callable — both are supported per the spec."""
    print("=" * 78)
    print("MODE: function_import (module_path + function_name)")
    print("=" * 78)

    config = FunctionImportConfig(
        module_path="tests.dummy_function_target",
        function_name="dummy_agent",
    )
    try:
        response = call_aut(SAMPLE_TASK, config)
    except Exception as e:  # noqa: BLE001
        print(f"  [ERROR] function_import (dotted) mode raised: {e}\n")
        return False

    _print_response("function_import (dotted path)", response)

    expected = f"Handled: {SAMPLE_TASK}"
    if response.output != expected:
        print(f"  [ERROR] expected output {expected!r}, got {response.output!r}\n")
        return False
    return True


# --------------------------------------------------------------------------
# manual — the guaranteed demo fallback, tested most thoroughly
# --------------------------------------------------------------------------
def test_manual() -> bool:
    print("=" * 78)
    print("MODE: manual (tested most thoroughly — the guaranteed demo fallback)")
    print("=" * 78)

    config = ManualConfig(json_path=SAMPLE_MANUAL_PATH)
    ok = True

    # 1. Lookup by full task text — response returned exactly as recorded,
    #    including a latency figure that is NOT a live measurement.
    try:
        response = call_aut("What is 15% of 240? Answer with just the number.", config)
        _print_response("manual (lookup by task text)", response)
        if response.output != "36" or response.latency_ms != 812.4 or response.tokens_used != 47:
            print("  [ERROR] recorded fields did not round-trip as expected\n")
            ok = False
    except Exception as e:  # noqa: BLE001
        print(f"  [ERROR] manual (task-text lookup) raised: {e}\n")
        ok = False

    # 2. Lookup by task id (not full task text) — same JSON file, different
    #    key style, both are supported.
    try:
        response = call_aut("task_003_out_of_scope_medical", config)
        _print_response("manual (lookup by task id)", response)
        if "medical advice" not in response.output:
            print("  [ERROR] unexpected output for task id lookup\n")
            ok = False
    except Exception as e:  # noqa: BLE001
        print(f"  [ERROR] manual (task-id lookup) raised: {e}\n")
        ok = False

    # 3. Missing task -> must raise ManualLookupError specifically, not fail
    #    silently and not raise some generic/unrelated exception.
    try:
        call_aut("this task was never recorded anywhere", config)
        print("  [ERROR] manual mode did NOT raise for a missing task — it should have!\n")
        ok = False
    except ManualLookupError as e:
        print(f"  Missing-task lookup correctly raised ManualLookupError:\n    {e}\n")
    except Exception as e:  # noqa: BLE001
        print(
            f"  [ERROR] manual mode raised the WRONG exception type for a missing task "
            f"({type(e).__name__}), expected ManualLookupError: {e}\n"
        )
        ok = False

    # 4. Missing JSON file -> AUTConnectorError, also not a silent failure.
    try:
        call_aut("anything", ManualConfig(json_path="tests/does_not_exist.json"))
        print("  [ERROR] manual mode did NOT raise for a missing JSON file — it should have!\n")
        ok = False
    except AUTConnectorError as e:
        print(f"  Missing-file lookup correctly raised AUTConnectorError:\n    {e}\n")
    except Exception as e:  # noqa: BLE001
        print(
            f"  [ERROR] manual mode raised the WRONG exception type for a missing file "
            f"({type(e).__name__}): {e}\n"
        )
        ok = False

    return ok


def main() -> None:
    print(f"Running aut/connector.py through all four modes (task: {SAMPLE_TASK!r})...\n")

    results = {
        "public_api": test_public_api(),
        "custom_endpoint": test_custom_endpoint(),
        "function_import (direct callable)": test_function_import(),
        "function_import (dotted path)": test_function_import_dotted_path(),
        "manual": test_manual(),
    }

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}  {label}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
