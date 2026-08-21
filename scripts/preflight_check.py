"""
scripts/preflight_check.py

Block H — run this MINUTES BEFORE the live demo, not during it. Three
checks, in order, each printed as a clear PASS/FAIL line. This script never
raises out to the caller — every check catches its own failures and reports
them, so a broken environment produces a readable FAIL list instead of a
stack trace.

  1. EvalMind's own LLM is configured (config.llm_config.is_configured()) —
     needed for every Describer/Generator/Judge/Aggregator call, regardless
     of which AUT mode a given scenario uses.
  2. Every demo scenario's aut_config (demo/scenarios.py) is reachable: one
     trivial call_aut() call per scenario, checked only for "did it raise"
     — not for any particular output content.
  3. Every manual-mode scenario's JSON fallback file loads and contains
     every task text that scenario is declared to expect
     (DemoScenario.expected_manual_tasks in demo/scenarios.py). A missing
     entry here is exactly what would turn into a hard, live
     ManualLookupError mid-demo (see aut/connector.py's ManualLookupError
     docstring) — this check exists so that failure happens now, on a
     terminal, instead of in front of an audience.

Exits non-zero if ANY check fails, so this is safe to script as the final
gate before walking into the demo room, e.g.:
    python scripts/preflight_check.py && echo "go"

Run from the project root:
    python scripts/preflight_check.py
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python scripts/preflight_check.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aut.connector import ManualConfig, call_aut  # noqa: E402
from config.llm_config import is_configured  # noqa: E402
from demo.scenarios import SCENARIOS  # noqa: E402

WIDTH = 78


def _print_header(title: str) -> None:
    print("=" * WIDTH)
    print(title)
    print("=" * WIDTH)


def _print_result(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


# ==========================================================================
# Check 1 — EvalMind's own LLM configuration
# ==========================================================================
def check_llm_configured() -> bool:
    _print_header("CHECK 1 — EvalMind's own LLM configuration (Describer/Generator/Judge/Aggregator)")
    ok = is_configured()
    _print_result(
        "config.llm_config.is_configured()",
        ok,
        "LLM_PROVIDER + matching API key found in .env" if ok else "no key configured — see .env.example",
    )
    print()
    return ok


# ==========================================================================
# Check 2 — each scenario's aut_config is reachable
# ==========================================================================
def _trivial_task_for(scenario) -> str:
    """A single task text safe to send through call_aut() for a bare
    reachability check.

    For a manual-mode scenario this MUST be an exact key already present in
    that scenario's JSON file — manual mode has no fuzzy/best-effort
    lookup, it raises ManualLookupError on any miss (see
    aut/connector.py) — so this uses the scenario's own first declared
    expected_manual_tasks entry, which is always present for a manual
    scenario. For every other mode, a short generic sentence is fine: the
    point here is only "did the call raise", not any particular output.
    """
    if scenario.aut_config.mode == "manual" and scenario.expected_manual_tasks:
        return scenario.expected_manual_tasks[0]
    return "Preflight check — please reply with any short acknowledgement."


def check_scenarios_reachable() -> bool:
    _print_header("CHECK 2 — demo scenario AUT reachability (one trivial call_aut() per scenario)")
    all_ok = True
    for scenario in SCENARIOS:
        task = _trivial_task_for(scenario)
        try:
            call_aut(task, scenario.aut_config)
            _print_result(f"{scenario.name!r} (mode={scenario.aut_config.mode})", True)
        except Exception as e:  # noqa: BLE001 - report every failure, never crash the script
            _print_result(f"{scenario.name!r} (mode={scenario.aut_config.mode})", False, str(e))
            all_ok = False
    print()
    return all_ok


# ==========================================================================
# Check 3 — manual-mode JSON files load and are fully populated
# ==========================================================================
def check_manual_files_populated() -> bool:
    _print_header("CHECK 3 — manual-mode JSON fallback files: load + fully populated")
    manual_scenarios = [s for s in SCENARIOS if s.aut_config.mode == "manual"]

    if not manual_scenarios:
        print("  (no scenario uses manual mode — nothing to check)")
        print()
        return True

    all_ok = True
    for scenario in manual_scenarios:
        config: ManualConfig = scenario.aut_config
        path = Path(config.json_path)
        print(f"  Scenario {scenario.name!r} -> {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _print_result("file exists", False, f"not found at {path}")
            all_ok = False
            print()
            continue
        except json.JSONDecodeError as e:
            _print_result("file is valid JSON", False, str(e))
            all_ok = False
            print()
            continue

        is_obj = isinstance(data, dict)
        _print_result("file loads as a JSON object", is_obj)
        if not is_obj:
            all_ok = False
            print()
            continue

        expected = scenario.expected_manual_tasks or []
        missing = [task for task in expected if task not in data]
        ok = not missing
        _print_result(
            f"all {len(expected)} expected task(s) present",
            ok,
            "" if ok else f"missing {len(missing)}: {missing}",
        )
        if not ok:
            all_ok = False
        print()

    return all_ok


def main() -> None:
    print("EvalMind — PRE-FLIGHT CHECK (run this minutes before the demo)\n")

    results = {
        "LLM configuration": check_llm_configured(),
        "scenario AUT reachability": check_scenarios_reachable(),
        "manual JSON file completeness": check_manual_files_populated(),
    }

    _print_header("SUMMARY")
    for label, ok in results.items():
        _print_result(label, ok)

    all_ok = all(results.values())
    print()
    if all_ok:
        print("All checks passed — safe to proceed to the demo.")
    else:
        print("One or more checks FAILED — fix before walking into the demo room.")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
