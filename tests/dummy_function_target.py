"""
tests/dummy_function_target.py

Trivial local AUT used as the test target for aut/connector.py's
"function_import" mode. Kept in its own module (rather than defined inline
in tests/test_connector.py) so the "module_path + function_name" dotted-
reference form of FunctionImportConfig has a real, separate module to point
at — exactly how a real function_import AUT would be referenced.
"""


def dummy_agent(task: str) -> str:
    """The simplest possible AUT: a str-in/str-out function."""
    return f"Handled: {task}"
