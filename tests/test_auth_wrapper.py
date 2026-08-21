"""
tests/test_auth_wrapper.py

Test script for Phase I's aut/auth.py — the login/auth wrapper for
login-gated "custom_endpoint" AUTs.

Spins up a tiny local HTTP test server, in the same spirit as
tests/dummy_endpoint.py (stdlib http.server, in-process, background daemon
thread — no Flask/FastAPI dependency, since neither is in requirements.txt),
with a handful of fixed routes standing in for a real AUT's login endpoint:

  POST /login               -- checks a hardcoded username/password, returns
                                200 {"auth_token": TOKEN} on match, 401
                                {"error": ...} otherwise.
  POST /login-custom-field  -- always returns 200 {"token": CUSTOM_TOKEN}
                                (a DIFFERENT field name than "auth_token") --
                                exercises AUTConnectionRequest's configurable
                                token_field / auth_header_format.
  POST /login-missing-field -- always returns 200 with neither "auth_token"
                                nor any recognizable token field.
  POST /login-not-json      -- always returns 200 with a non-JSON text body.

Six cases:
  1. requires_login=False -> returns CustomEndpointConfig(headers=None)
     directly, with NO network call at all (asserted by monkeypatching
     requests.post to raise if it's ever invoked).
  2. requires_login=True, correct credentials -> POSTs to /login, extracts
     "auth_token" (the default token_field), and returns a config whose
     headers are exactly {"Authorization": "Bearer <token>"} (the default
     auth_header_format).
  3. requires_login=True, wrong credentials (server returns 401) ->
     AUTAuthError.
  4. requires_login=True, response missing the expected token field ->
     AUTAuthError.
  5. requires_login=True, response body isn't valid JSON -> AUTAuthError.
  6. requires_login=True, a non-default token_field ("token") and a
     non-default auth_header_format ("Token {token}") -> confirms both are
     genuinely configurable, not hardcoded (per the spec).

Run from the project root:
    python tests/test_auth_wrapper.py
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Allow running as `python tests/test_auth_wrapper.py` (no package install / -m needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aut.auth import AUTAuthError, AUTConnectionRequest, build_authenticated_endpoint_config  # noqa: E402

PORT = 8757
CHAT_URL = "http://example.invalid/chat"  # never actually called by auth.py itself

VALID_USERNAME = "demo_user"
VALID_PASSWORD = "demo_pass"
VALID_TOKEN = "test-token-xyz789"
CUSTOM_TOKEN = "custom-token-abc123"


# --------------------------------------------------------------------------
# Local test server -- same stdlib http.server approach as
# tests/dummy_endpoint.py, extended with a few fixed routes.
# --------------------------------------------------------------------------
class _AuthTestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib's required method name
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"

        if self.path == "/login":
            try:
                payload = json.loads(raw_body or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "request body was not valid JSON"})
                return
            username = payload.get("username") if isinstance(payload, dict) else None
            password = payload.get("password") if isinstance(payload, dict) else None
            if username == VALID_USERNAME and password == VALID_PASSWORD:
                self._send_json(200, {"auth_token": VALID_TOKEN})
            else:
                self._send_json(401, {"error": "invalid credentials"})
            return

        if self.path == "/login-custom-field":
            self._send_json(200, {"token": CUSTOM_TOKEN})
            return

        if self.path == "/login-missing-field":
            self._send_json(200, {"unexpected_key": "irrelevant"})
            return

        if self.path == "/login-not-json":
            body = b"this is not json"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._send_json(404, {"error": f"no such test route: {self.path}"})

    def _send_json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # quiet by default, same as tests/dummy_endpoint.py


def _start_server(port: int = PORT) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", port), _AuthTestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


# --------------------------------------------------------------------------
# Case 1: requires_login=False -> no network call at all.
# --------------------------------------------------------------------------
def test_requires_login_false() -> bool:
    print("=" * 78)
    print("CASE 1: requires_login=False -> headers=None, zero network calls")
    print("=" * 78)

    ok = True
    connection = AUTConnectionRequest(chat_endpoint_url=CHAT_URL, requires_login=False)

    with patch("requests.post", side_effect=AssertionError("requests.post must NOT be called")):
        config = build_authenticated_endpoint_config(connection)

    print(f"  url={config.url!r} headers={config.headers!r}")
    if config.url != CHAT_URL:
        print(f"  [ERROR] expected url={CHAT_URL!r}, got {config.url!r}")
        ok = False
    if config.headers is not None:
        print(f"  [ERROR] expected headers=None, got {config.headers!r}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 2: correct credentials -> Authorization: Bearer <token>
# --------------------------------------------------------------------------
def test_successful_login() -> bool:
    print("=" * 78)
    print("CASE 2: requires_login=True, correct credentials -> Bearer <token> header")
    print("=" * 78)

    ok = True
    connection = AUTConnectionRequest(
        chat_endpoint_url=CHAT_URL,
        requires_login=True,
        login_endpoint_url=f"http://127.0.0.1:{PORT}/login",
        username=VALID_USERNAME,
        password=VALID_PASSWORD,
    )
    config = build_authenticated_endpoint_config(connection)
    print(f"  url={config.url!r} headers={config.headers!r}")

    if config.url != CHAT_URL:
        print(f"  [ERROR] expected url={CHAT_URL!r}, got {config.url!r}")
        ok = False
    expected_headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    if config.headers != expected_headers:
        print(f"  [ERROR] expected headers={expected_headers!r}, got {config.headers!r}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 3: wrong credentials -> AUTAuthError
# --------------------------------------------------------------------------
def test_wrong_credentials() -> bool:
    print("=" * 78)
    print("CASE 3: requires_login=True, wrong credentials -> AUTAuthError")
    print("=" * 78)

    connection = AUTConnectionRequest(
        chat_endpoint_url=CHAT_URL,
        requires_login=True,
        login_endpoint_url=f"http://127.0.0.1:{PORT}/login",
        username=VALID_USERNAME,
        password="totally-wrong-password",
    )
    ok = True
    try:
        build_authenticated_endpoint_config(connection)
        print("  [ERROR] expected AUTAuthError, no exception was raised")
        ok = False
    except AUTAuthError as e:
        print(f"  raised AUTAuthError as expected: {e}")

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 4: response missing the expected token field -> AUTAuthError
# --------------------------------------------------------------------------
def test_missing_token_field() -> bool:
    print("=" * 78)
    print("CASE 4: login response missing the expected token field -> AUTAuthError")
    print("=" * 78)

    connection = AUTConnectionRequest(
        chat_endpoint_url=CHAT_URL,
        requires_login=True,
        login_endpoint_url=f"http://127.0.0.1:{PORT}/login-missing-field",
        username=VALID_USERNAME,
        password=VALID_PASSWORD,
    )
    ok = True
    try:
        build_authenticated_endpoint_config(connection)
        print("  [ERROR] expected AUTAuthError, no exception was raised")
        ok = False
    except AUTAuthError as e:
        print(f"  raised AUTAuthError as expected: {e}")

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 5: response body isn't valid JSON -> AUTAuthError
# --------------------------------------------------------------------------
def test_non_json_response() -> bool:
    print("=" * 78)
    print("CASE 5: login response isn't valid JSON -> AUTAuthError")
    print("=" * 78)

    connection = AUTConnectionRequest(
        chat_endpoint_url=CHAT_URL,
        requires_login=True,
        login_endpoint_url=f"http://127.0.0.1:{PORT}/login-not-json",
        username=VALID_USERNAME,
        password=VALID_PASSWORD,
    )
    ok = True
    try:
        build_authenticated_endpoint_config(connection)
        print("  [ERROR] expected AUTAuthError, no exception was raised")
        ok = False
    except AUTAuthError as e:
        print(f"  raised AUTAuthError as expected: {e}")

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


# --------------------------------------------------------------------------
# Case 6: non-default token_field + auth_header_format both actually used.
# --------------------------------------------------------------------------
def test_custom_token_field_and_header_format() -> bool:
    print("=" * 78)
    print("CASE 6: custom token_field='token', auth_header_format='Token {token}'")
    print("=" * 78)

    connection = AUTConnectionRequest(
        chat_endpoint_url=CHAT_URL,
        requires_login=True,
        login_endpoint_url=f"http://127.0.0.1:{PORT}/login-custom-field",
        username=VALID_USERNAME,
        password=VALID_PASSWORD,
        token_field="token",
        auth_header_format="Token {token}",
    )
    config = build_authenticated_endpoint_config(connection)
    print(f"  headers={config.headers!r}")

    ok = True
    expected_headers = {"Authorization": f"Token {CUSTOM_TOKEN}"}
    if config.headers != expected_headers:
        print(f"  [ERROR] expected headers={expected_headers!r}, got {config.headers!r}")
        ok = False

    print(f"  {'OK' if ok else 'FAILED'}\n")
    return ok


def main() -> None:
    server, thread = _start_server(PORT)
    try:
        results = {
            "requires_login=False -> no network call": test_requires_login_false(),
            "correct credentials -> Bearer token": test_successful_login(),
            "wrong credentials -> AUTAuthError": test_wrong_credentials(),
            "missing token field -> AUTAuthError": test_missing_token_field(),
            "non-JSON response -> AUTAuthError": test_non_json_response(),
            "custom token_field/auth_header_format": test_custom_token_field_and_header_format(),
        }
    finally:
        server.shutdown()
        thread.join()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}  {label}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
