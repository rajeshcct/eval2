"""
backend/tests/test_browser_connector.py
Test the browser connector using a real local HTTP server.
"""
import sys
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Allow running as `python backend/tests/test_browser_connector.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from aut.connector import BrowserConfig
from aut.playwright_connector import call_browser_aut

HTML_PAGE = b"""
<!DOCTYPE html>
<html>
<head>
<title>Chatbot Fixture</title>
<style>
  .hidden { display: none; }
</style>
<script>
  function openPopup() {
    window.open("/popup", "_blank", "width=400,height=400");
  }
  function sendMsg() {
    document.getElementById("chat-input").value = "";
    setTimeout(() => {
      let resp = document.createElement("div");
      resp.className = "bot-message";
      resp.innerText = "Response to: " + window.lastTask;
      document.body.appendChild(resp);
    }, 500);
  }
  window.onload = () => {
    document.getElementById("chat-input").addEventListener("input", (e) => {
      window.lastTask = e.target.value;
    });
  }
</script>
</head>
<body>
  <h1>Test Chat</h1>
  <button id="launcher" onclick="document.getElementById('chat-container').classList.remove('hidden')">Open Chat</button>
  <div id="chat-container" class="hidden">
    <input type="text" id="chat-input" placeholder="Type here...">
    <button id="send-btn" onclick="sendMsg()">Send</button>
  </div>
  <button id="popup-btn" onclick="openPopup()">Login Popup</button>
</body>
</html>
"""

POPUP_PAGE = b"""
<!DOCTYPE html>
<html>
<head><title>Login Popup</title></head>
<body>
  <input type="text" id="username" placeholder="User">
  <input type="password" id="password" placeholder="Pass">
  <button id="submit-login" onclick="setTimeout(() => window.close(), 100)">Log In</button>
</body>
</html>
"""

class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if self.path == "/popup":
            self.wfile.write(POPUP_PAGE)
        else:
            self.wfile.write(HTML_PAGE)

    def log_message(self, format, *args):
        pass

def main():
    server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
    port = server.server_address[1]
    
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    
    url = f"http://127.0.0.1:{port}/"
    
    print(f"Server started at {url}")
    
    config = BrowserConfig(
        chatbot_url=url,
        chat_launcher_selector="#launcher",
        input_selector="#chat-input",
        send_selector="#send-btn",
        response_selector=".bot-message:last-child",
        wait_strategy="new_element",
        wait_timeout_seconds=5.0,
        headless=True
    )
    
    print("Running call_browser_aut...")
    try:
        response = call_browser_aut("Hello browser", config)
        print("Response received:", response.output)
        if response.output == "Response to: Hello browser":
            print("OK")
        else:
            print("FAILED: Output mismatch")
    except Exception as e:
        print("FAILED with exception:", e)

if __name__ == "__main__":
    main()
