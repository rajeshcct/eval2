"""
tests/dummy_endpoint.py

Tiny local HTTP test target for aut/connector.py's "custom_endpoint" mode —
stands in for "a real deployed AUT" during testing.

The connector POSTs {"task": "..."} as JSON to the configured URL and reads
the output back out of the JSON response body (see
aut.connector._extract_output_text), so this server's only job is to accept
that POST and echo back f"Echo: {task}" as {"output": ...}.

Built on Python's stdlib http.server rather than FastAPI/Flask: neither
package is installed in this project's venv (checked before writing this),
and pulling in a whole new web framework just for a test-only echo server
isn't worth the extra dependency for a POC. http.server is more than enough
to stand in for a deployed AUT for connector-testing purposes.

Can be run two ways:

  1. Standalone, in its own terminal — useful for pointing a
     CustomEndpointConfig at it manually:
         python tests/dummy_endpoint.py
     (listens on http://127.0.0.1:8756 until Ctrl+C)

  2. Imported and started in-process (this is what tests/test_connector.py
     does, so the whole four-mode test suite runs from a single command):
         from tests.dummy_endpoint import start_server
         server, thread = start_server()
         ...
         server.shutdown()
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8756


class _EchoHandler(BaseHTTPRequestHandler):
    """Accepts POST {"task": "..."} and replies {"output": "Echo: ..."}."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib's required method name
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"

        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "request body was not valid JSON"})
            return

        task = payload.get("task", "") if isinstance(payload, dict) else ""
        self._send_json(200, {"output": f"Echo: {task}"})

    def _send_json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Quiet by default so test output stays readable. Comment out (or
        # call the default BaseHTTPRequestHandler implementation) to debug.
        pass


def start_server(port: int = DEFAULT_PORT) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the dummy echo server on a background daemon thread.

    By the time the ThreadingHTTPServer constructor returns, the socket is
    already bound and listening (stdlib does this synchronously), so it's
    safe to start making requests immediately after this call returns.

    Returns:
        (server, thread) — call server.shutdown() when done, then
        thread.join() to wait for clean exit.
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    server, thread = start_server()
    print(f"Dummy AUT echo server running at http://127.0.0.1:{DEFAULT_PORT} (POST /, Ctrl+C to stop)")
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nShutting down dummy endpoint...")
        server.shutdown()
