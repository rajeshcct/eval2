import sys
from pathlib import Path
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from aut.connector import BrowserConfig
from aut.playwright_connector import call_browser_aut, close_session, BrowserTimeoutError, BrowserSelectorError

HTML_FIXTURE = b"""
<!DOCTYPE html>
<html>
<head>
<title>Chatbot Fixture</title>
<style>
  .overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 9999; }
  .hidden { display: none; }
</style>
<script>
  function showOverlayTemp() {
    let overlay = document.createElement("div");
    overlay.className = "overlay";
    document.body.appendChild(overlay);
    setTimeout(() => { document.body.removeChild(overlay); }, 1000);
  }

  function sendMsg() {
    let input = document.getElementById("chat-input");
    let task = input.value;
    if (!task) return;
    
    input.value = "";
    
    if (task === "SLOW") {
      setTimeout(() => {
        addResponse("Too slow!");
      }, 5000);
    } else if (task === "NO_CLEAR") {
      input.value = task;
    } else {
      setTimeout(() => {
        addResponse("Response to: " + task);
      }, 500);
    }
  }

  function addResponse(text) {
    let resp = document.createElement("div");
    resp.className = "bot-message";
    resp.innerText = text;
    document.getElementById("chat-container").appendChild(resp);
  }

  window.onload = () => {
    showOverlayTemp();
    setTimeout(() => {
      document.getElementById("chat-container").classList.remove("hidden");
    }, 1500);
  }
</script>
</head>
<body>
  <h1>Test Chat</h1>
  
  <div id="chat-container" class="hidden">
    <input type="text" class="loose-input" style="display:none;" value="hidden">
    <input type="text" id="chat-input" class="loose-input" placeholder="Type here..." data-testid="chat-input">
    <button id="send-btn" onclick="sendMsg()">Send</button>
  </div>
  
  <button id="login-launcher" onclick="window.open('/login', '_blank', 'width=400,height=400')">Login</button>
</body>
</html>
"""

LOGIN_FIXTURE = b"""
<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
  <input type="text" id="username" placeholder="User">
  <input type="password" id="password" placeholder="Pass">
  <button id="submit-login" onclick="login()">Log In</button>
  <script>
    function login() {
      let u = document.getElementById("username").value;
      if (u) {
        setTimeout(() => {
          let s = document.createElement("div");
          s.id = "success-msg";
          s.innerText = "Logged in!";
          document.body.appendChild(s);
          setTimeout(() => window.close(), 500);
        }, 500);
      }
    }
  </script>
</body>
</html>
"""

class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if self.path == "/login":
            self.wfile.write(LOGIN_FIXTURE)
        else:
            self.wfile.write(HTML_FIXTURE)
    def log_message(self, format, *args):
        pass

def run_tests():
    server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    
    url = f"http://127.0.0.1:{port}/"
    print(f"Fixture Server at {url}")

    config = BrowserConfig(
        chatbot_url=url,
        input_selector="[data-testid='chat-input']",
        send_selector="#send-btn",
        response_selector=".bot-message:last-child",
        wait_strategy="new_element",
        wait_timeout_seconds=3.0,
        headless=True,
        requires_login=True,
        login_url=url + "login",
        username_selector="#username",
        password_selector="#password",
        submit_selector="#submit-login",
        login_success_selector="#success-msg",
        username="testuser",
        password="testpassword"
    )

    try:
        print("Test 1: Normal flow + Login + Delayed Mount + Overlay wait")
        resp = call_browser_aut("Hello", config)
        assert "Response to: Hello" in resp.output, f"Got {resp.output}"
        print("  OK")
        
        print("Test 2: Second session reuse")
        resp2 = call_browser_aut("Second", config)
        assert "Response to: Second" in resp2.output
        print("  OK")
        
        print("Test 3: Send verification failure (NO_CLEAR)")
        try:
            call_browser_aut("NO_CLEAR", config)
            assert False, "Should have raised BrowserSelectorError"
        except BrowserSelectorError as e:
            assert "still contains the typed task" in str(e)
            print("  OK")

        print("Test 4: Response timeout (SLOW)")
        try:
            call_browser_aut("SLOW", config)
            assert False, "Should have raised BrowserTimeoutError"
        except BrowserTimeoutError as e:
            assert "did not appear within" in str(e)
            print("  OK")
            
        print("Closing session...")
        close_session(config)
        print("Session closed. All tests passed.")
        sys.exit(0)
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
