"""
aut/playwright_connector.py

Browser-based AUT connector — drives a real Chromium browser (headless by
default) to interact with any web chatbot UI via CSS/text selectors, with
optional automated login.

Why this exists:
  Some AUTs have NO public API at all. They are web UIs only (e.g. Reddit
  Answers, an internal company chatbot, a demo widget). The only way to
  evaluate them programmatically is to simulate what a real user does:
  open a browser, type into the chat box, click Send, wait for the reply.

Flow per call_aut() invocation (one round):
  1. Launch (or reuse) a Playwright Chromium browser context.
  2. If requires_login=True AND not yet logged in this session:
       a. Navigate to login_url
       b. Fill username + password using provided selectors
       c. Click submit, wait for redirect / success element
       d. Save browser storage state for reuse across rounds
  3. Open a new page (or reuse existing if persist_session=True).
  4. Navigate to chatbot_url.
  5. Wait for the input element to appear (up to wait_timeout_seconds).
  6. Click the input, clear it, type the task.
  7. Click the send button.
  8. Wait for the response element to appear / change.
  9. Scrape the response text.
  10. Return AUTResponse.

Thread-safety note:
  Playwright's synchronous API uses one browser instance per thread.
  BrowserSessionManager holds a single browser + context per BrowserConfig
  instance (keyed by config.session_key, a UUID generated once per
  BrowserConfig instance — not id(config), which CPython can reuse after
  garbage collection), reset between sessions (not between rounds unless
  persist_session=False). The connector is always called from a single
  worker thread inside asyncio.to_thread(), so no locking is needed.

Error handling:
  All Playwright errors are caught and re-raised as AUTConnectorError with
  a clear message so the existing error-surfacing path in main.py works
  unchanged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from aut.connector import AUTConnectorError, AUTResponse


# ==========================================================================
# Errors
# ==========================================================================
class BrowserAuthError(AUTConnectorError):
    """Login step failed — wrong credentials, selector not found, or the
    expected post-login element / URL never appeared."""


class BrowserTimeoutError(AUTConnectorError):
    """The chatbot response element didn't appear within the timeout."""


class BrowserSelectorError(AUTConnectorError):
    """A required CSS selector didn't match any element on the page."""


class BrowserAutoDetectError(AUTConnectorError):
    """Auto-detection of selectors failed even after heuristics + LLM vision."""


# ==========================================================================
# Auto-detect — heuristic candidate lists (tried in order, first match wins)
# ==========================================================================
_INPUT_CANDIDATES = [
    "textarea",
    "[role='textbox']",
    "[contenteditable='true']",
    "input[type='text'][name*='message']",
    "input[type='text'][placeholder*='ask']",
    "input[type='text'][placeholder*='message']",
    "input[type='text'][placeholder*='type']",
    "[placeholder*='message' i]",
    "[placeholder*='ask' i]",
    "[placeholder*='type' i]",
    "[placeholder*='chat' i]",
    "[aria-label*='message' i]",
    "[aria-label*='ask' i]",
    "[aria-label*='input' i]",
    "[data-testid*='input']",
    "[data-testid*='message']",
    "[data-cy*='input']",
    "input[type='text']",
]

_SEND_CANDIDATES = [
    "button[type='submit']",
    "[aria-label*='send' i]",
    "[aria-label*='submit' i]",
    "[data-testid*='send']",
    "[data-testid*='submit']",
    "[data-cy*='send']",
    "button[title*='send' i]",
    "button[title*='submit' i]",
    "form button:last-of-type",
    "button svg[class*='send']",   # icon-only send buttons
]

_RESPONSE_CANDIDATES = [
    "[data-testid*='bot-message']:last-child",
    "[data-testid*='assistant']:last-child",
    "[data-testid*='response']:last-child",
    "[data-testid*='answer']:last-child",
    "[data-testid*='message']:last-child",
    ".assistant-message:last-child",
    ".bot-message:last-child",
    "[class*='assistant']:last-child",
    "[class*='bot']:last-child",
    "[class*='response']:last-child",
    "[role='article']:last-child",
    ".message:last-child",
    "[class*='message']:last-child",
]

# Cache: config.session_key → {"input": sel, "send": sel, "response": sel}
# Keyed by the UUID-based BrowserConfig.session_key (see that field's
# docstring in aut/connector.py) rather than id(config) — id() is a memory
# address CPython reuses after garbage collection, which previously let a
# later, unrelated BrowserConfig silently inherit an earlier run's cached
# selectors for a completely different site.
_SELECTOR_CACHE: dict[str, dict[str, str]] = {}

# Keywords that betray a selector as a dropdown/autocomplete/filter rather
# than a genuine free-text chat input. When the LLM hallucinates one of these
# as the "input" we discard it and fall through to the BrowserAutoDetectError.
_NOT_CHAT_INPUT_CLUES = (
    "vs__search",       # Vue Select dropdown search
    "combobox",
    "autocomplete",
    "select",           # <select> dropdowns
    "dropdown",
    "filter",
    "search",           # generic search bars on dashboards
    "typeahead",
)

# Keywords that reveal a generic page container rather than a chat message.
# Accepting these as response_sel means text_change never fires because the
# container existed before the chat started.
_NOT_CHAT_RESPONSE_CLUES = (
    "card-body",        # Bootstrap generic card — present from page load
    "card",
    "dashboard",
    "sidebar",
    "navbar",
    "header",
    "footer",
    "modal",
)


def _is_chat_input_selector(sel: str) -> bool:
    """Return False if the selector looks like a dropdown / filter, not a chat input."""
    s = sel.lower()
    return not any(clue in s for clue in _NOT_CHAT_INPUT_CLUES)


def _is_chat_response_selector(sel: str) -> bool:
    """Return False if the selector looks like a generic page section, not a message container."""
    s = sel.lower()
    return not any(clue in s for clue in _NOT_CHAT_RESPONSE_CLUES)


def _find_first_matching(page: Any, candidates: list[str]) -> Optional[str]:
    """Return the first selector in candidates that resolves to EXACTLY ONE
    visible element.

    Previously this used page.query_selector(), which returns the first DOM
    match with no multiplicity check — a selector could "pass" detection
    here and then fail later when the exact same string is handed to
    page.fill()/page.click(), which resolve selectors through Playwright's
    strict mode (raises if 2+ elements match). That mismatch — one loose
    resolution rule for detection, a stricter one for actual use — was a
    real source of "the field is right there in the screenshot but the fill
    failed" failures. Using locator().count() == 1 here means "detected as
    usable" and "actually usable by fill()/click()" are the same check, so
    a selector matching 2+ elements is skipped (not guessed at) rather than
    silently deferring a strict-mode violation to a later step.
    """
    for sel in candidates:
        try:
            locator = page.locator(sel)
            if locator.count() == 1 and locator.first.is_visible():
                return sel
        except Exception:  # noqa: BLE001
            continue
    return None


def _auto_detect_with_llm(screenshot_bytes: bytes, url: str) -> dict[str, str]:
    """Send a screenshot to the configured LLM (vision) and ask it to identify
    the three CSS selectors. Returns a dict with keys input/send/response."""
    import base64
    from config.llm_config import get_llm

    b64 = base64.b64encode(screenshot_bytes).decode()
    prompt = f"""You are a web automation expert. Below is a base64-encoded screenshot of a chatbot web UI at {url}.

Identify the BEST CSS selector for each of these three elements:
1. The text input / textarea where the user types their message
2. The send / submit button
3. The element that contains the bot's response (the latest message)

Respond in EXACTLY this format (one selector per line, no explanation):
INPUT_SELECTOR: <selector>
SEND_SELECTOR: <selector>
RESPONSE_SELECTOR: <selector>

Screenshot (base64 PNG): data:image/png;base64,{b64}"""

    llm = get_llm()
    try:
        answer = llm.call(messages=[{"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001
        raise BrowserAutoDetectError(
            f"LLM vision call for selector auto-detection failed: {e}"
        ) from e

    if not isinstance(answer, str):
        answer = str(answer)

    result: dict[str, str] = {}
    for line in answer.strip().splitlines():
        if line.startswith("INPUT_SELECTOR:"):
            result["input"] = line.split(":", 1)[1].strip()
        elif line.startswith("SEND_SELECTOR:"):
            result["send"] = line.split(":", 1)[1].strip()
        elif line.startswith("RESPONSE_SELECTOR:"):
            result["response"] = line.split(":", 1)[1].strip()

    missing = [k for k in ("input", "send", "response") if k not in result]
    if missing:
        raise BrowserAutoDetectError(
            f"LLM did not return selectors for: {missing}. Raw response:\n{answer}"
        )
    return result


def auto_detect_selectors(
    page: Any,
    url: str,
    config: Any,
    timeout_ms: int = 5000,
) -> dict[str, str]:
    """Auto-detect input / send / response selectors for a chat UI using
    heuristics only (no LLM / vision model required).

    Tries ranked lists of common chat UI CSS patterns for each role.
    First visible match wins. Results are cached on the config object so
    detection only runs once per EvalMind session regardless of how many
    rounds are evaluated.

    If heuristics can't find a selector for a role, raises
    BrowserAutoDetectError with a clear message telling the user which
    selector to provide manually in the form.

    Args:
        page:       an open Playwright Page already at the chatbot URL.
        url:        the chatbot URL (used in error messages for context).
        config:     BrowserConfig instance (used as cache key via its
                    stable session_key, not id() — see that field's
                    docstring in aut/connector.py).
        timeout_ms: how long to wait for JS to render before scanning.

    Returns:
        dict with keys 'input', 'send', 'response' → CSS selector strings.
    """
    key = config.session_key
    if key in _SELECTOR_CACHE:
        return _SELECTOR_CACHE[key]

    # Give dynamic / React / Vue UIs a moment to render
    page.wait_for_timeout(timeout_ms)

    detected: dict[str, str] = {}

    inp = _find_first_matching(page, _INPUT_CANDIDATES)
    if inp:
        detected["input"] = inp

    snd = _find_first_matching(page, _SEND_CANDIDATES)
    if snd:
        detected["send"] = snd

    resp = _find_first_matching(page, _RESPONSE_CANDIDATES)
    if resp:
        detected["response"] = resp

    still_missing = [k for k in ("input", "send", "response") if k not in detected]
    if still_missing:
        print(f"[browser debug] Heuristics missed {still_missing}, falling back to LLM HTML analysis...")
        try:
            # Strip scripts, styles, SVGs etc to save tokens and isolate structure
            clean_html = page.evaluate('''() => {
                let clone = document.body.cloneNode(true);
                clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(el => el.remove());
                // Strip massive base64 attributes or giant class lists if needed, but innerHTML is usually okay after stripping the above
                return clone.innerHTML;
            }''')
            
            from config.llm_config import get_llm
            llm = get_llm()
            
            prompt = f"""You are a web automation expert finding CSS selectors for Playwright.
Below is the stripped HTML of a chatbot UI at {url}.
We still need CSS selectors for: {still_missing}

Identify the BEST, MOST UNIQUE CSS selector for each missing element.
CRITICAL RULES:
1. The selector MUST perfectly match an element that ACTUALLY EXISTS in the provided HTML.
2. DO NOT output generic fallback selectors like 'textarea, input'. Look at the HTML and find the actual class, id, or data-testid.
3. If it's a chat input, look for search bars, text inputs, or textareas that a user would type a message into.
4. If it's a send button, look for buttons near the input, often with an icon or 'Send' text.
5. If it's a response, look for the container holding the chatbot's messages. Use :last-child or :last-of-type if it's a list.
6. If the chat input is hidden behind a 'chat widget' launcher button (e.g. a floating icon), provide its selector as well. If the chat is already open and visible without a launcher, return 'None' for LAUNCHER_SELECTOR.

Respond in EXACTLY this format (one selector per line, no explanation, only for the missing ones):
INPUT_SELECTOR: <selector>
SEND_SELECTOR: <selector>
RESPONSE_SELECTOR: <selector>
LAUNCHER_SELECTOR: <selector or None>

HTML:
{clean_html[:30000]}"""

            print(f"[browser debug] Calling LLM ({type(llm).__name__}) for selector detection...")
            answer = llm.call(messages=[{"role": "user", "content": prompt}])
            if not isinstance(answer, str):
                answer = str(answer)
            
            print(f"[browser debug] LLM HTML fallback RAW ANSWER:\n{answer[:2000]}")
                
            for line in answer.strip().splitlines():
                if line.startswith("INPUT_SELECTOR:") and "input" in still_missing:
                    candidate = line.split(":", 1)[1].strip()
                    if _is_chat_input_selector(candidate):
                        detected["input"] = candidate
                    else:
                        print(f"[browser debug] LLM INPUT_SELECTOR '{candidate}' rejected — looks like a dropdown/filter, not a chat input")
                elif line.startswith("SEND_SELECTOR:") and "send" in still_missing:
                    detected["send"] = line.split(":", 1)[1].strip()
                elif line.startswith("RESPONSE_SELECTOR:") and "response" in still_missing:
                    candidate = line.split(":", 1)[1].strip()
                    if _is_chat_response_selector(candidate):
                        detected["response"] = candidate
                    else:
                        print(f"[browser debug] LLM RESPONSE_SELECTOR '{candidate}' rejected — looks like a generic container, not a chat message element")
                elif line.startswith("LAUNCHER_SELECTOR:"):
                    sel = line.split(":", 1)[1].strip()
                    if sel and sel.lower() not in ["none", "null", ""]:
                        detected["launcher"] = sel
                    
            still_missing = [k for k in ("input", "send", "response") if k not in detected]
            
            # ── Phase 2: if LLM found a launcher, click it then re-detect ALL selectors ──
            # The selectors above were detected from the CLOSED-panel HTML.
            # Elements like .ai-assistant-send-btn simply don't exist in the DOM
            # until the panel is open — so we MUST re-detect everything from the
            # live post-launcher HTML, not just the ones that were "still_missing".
            if detected.get("launcher"):
                launcher_sel = detected["launcher"]
                try:
                    page.locator(launcher_sel).first.click()
                    page.wait_for_timeout(3000)  # wait generously for React/Vue panel to fully mount
                    print(f"[browser debug] Clicked LLM-detected launcher '{launcher_sel}', re-scanning ALL selectors from open-panel HTML...")
                    
                    # Clear pre-launch selectors — they came from the closed DOM and may not exist now
                    for k in ("input", "send", "response"):
                        detected.pop(k, None)
                    
                    # Try fast heuristics first (free, no LLM call)
                    re_inp = _find_first_matching(page, _INPUT_CANDIDATES)
                    if re_inp:
                        detected["input"] = re_inp
                    re_snd = _find_first_matching(page, _SEND_CANDIDATES)
                    if re_snd:
                        detected["send"] = re_snd
                    re_resp = _find_first_matching(page, _RESPONSE_CANDIDATES)
                    if re_resp:
                        detected["response"] = re_resp
                    
                    still_missing = [k for k in ("input", "send", "response") if k not in detected]
                    
                    # Always do a second LLM pass with the open-panel HTML (even if
                    # heuristics found something — the LLM may find better/more specific selectors
                    # and override the generic heuristic ones where needed)
                    print(f"[browser debug] Running LLM pass on open-panel HTML (still need: {still_missing or 'validation'})...")
                    clean_html2 = page.evaluate('''() => {
                        let clone = document.body.cloneNode(true);
                        clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(el => el.remove());
                        return clone.innerHTML;
                    }''')
                    prompt2 = f"""You are a web automation expert. A chat panel has just been opened on {url}.
The HTML below shows the OPEN chat widget. Find CSS selectors for these roles: ['input', 'send', 'response']

CRITICAL RULES:
1. 'input': The TEXT INPUT / TEXTAREA where the user TYPES their chat message. Must be an editable field.
2. 'send': The SEND / SUBMIT button that POSTS the message. Look for buttons near the input.
3. 'response': The container where BOT REPLIES appear. Pick the MOST SPECIFIC selector (class with 'message', 'reply', 'assistant', 'bot').
4. DO NOT suggest filter dropdowns, search bars, dashboard cards, or navigation buttons.
5. The selector MUST match an element that EXISTS in the HTML below.

Respond ONLY in this exact format (all three lines required):
INPUT_SELECTOR: <selector>
SEND_SELECTOR: <selector>
RESPONSE_SELECTOR: <selector>

HTML:
{clean_html2[:30000]}"""
                    answer2 = llm.call(messages=[{"role": "user", "content": prompt2}])
                    if not isinstance(answer2, str):
                        answer2 = str(answer2)
                    print(f"[browser debug] Open-panel LLM pass RAW ANSWER:\n{answer2[:1000]}")
                    for line2 in answer2.strip().splitlines():
                        if line2.startswith("INPUT_SELECTOR:"):
                            c = line2.split(":", 1)[1].strip()
                            if _is_chat_input_selector(c):
                                detected["input"] = c
                            else:
                                print(f"[browser debug] Open-panel LLM INPUT '{c}' rejected — looks like dropdown/filter")
                        elif line2.startswith("SEND_SELECTOR:"):
                            detected["send"] = line2.split(":", 1)[1].strip()
                        elif line2.startswith("RESPONSE_SELECTOR:"):
                            c = line2.split(":", 1)[1].strip()
                            if _is_chat_response_selector(c):
                                detected["response"] = c
                            else:
                                print(f"[browser debug] Open-panel LLM RESPONSE '{c}' rejected — looks like generic container")
                    still_missing = [k for k in ("input", "send", "response") if k not in detected]
                except Exception as launcher_err:
                    print(f"[browser debug] Launcher click/re-scan failed: {launcher_err}")

        except Exception as e:
            from config.llm_config import MissingAPIKeyError
            if isinstance(e, MissingAPIKeyError):
                raise BrowserAutoDetectError(
                    f"LLM HTML fallback cannot run: no API key is configured. "
                    f"Set LLM_PROVIDER and the matching *_API_KEY in your .env file. "
                    f"Error: {e}\n\n"
                    f"WORKAROUND: Open the chatbot page in Chrome DevTools, right-click "
                    f"each element → Inspect → Copy selector, then paste them into the "
                    f"form's input_selector / send_selector / response_selector fields."
                ) from e
            print(f"[browser debug] LLM HTML fallback failed: {e}")

    if still_missing:
        role_hints = {
            "input":    "the chat text input / textarea",
            "send":     "the Send / Submit button",
            "response": "the element containing the bot's reply",
        }
        hints = "; ".join(f"'{k}' ({role_hints[k]})" for k in still_missing)
        raise BrowserAutoDetectError(
            f"Auto-detection (heuristics + LLM fallback) could not identify selectors for: {hints} on '{url}'. \n"
            f"The LLM may have seen dashboard/filter elements instead of chat elements.\n"
            f"SOLUTION: Open the chatbot in Chrome → right-click each element → Inspect → copy the selector "
            f"and paste it into the form's input_selector / send_selector / response_selector fields."
        )

    _SELECTOR_CACHE[key] = detected
    return detected




# ==========================================================================
# Session cache — one browser context per BrowserConfig instance so login
# only happens once per EvalMind session regardless of how many rounds run.
# ==========================================================================
@dataclass
class _BrowserSession:
    browser: Any   # playwright Browser
    context: Any   # playwright BrowserContext
    logged_in: bool = False
    active_pages: list[Any] = field(default_factory=list)
    main_page: Any = None

    @property
    def current_page(self) -> Any:
        while self.active_pages and self.active_pages[-1].is_closed():
            self.active_pages.pop()
        if not self.active_pages:
            from aut.connector import AUTConnectorError
            raise AUTConnectorError("browser: All pages were closed unexpectedly.")
        return self.active_pages[-1]


class _ActivePageProxy:
    """Proxies all attribute access to the most recently created, still-open page
    in a session. Automatically follows popups and new tabs."""
    def __init__(self, session: _BrowserSession):
        self._session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session.current_page, name)


_SESSIONS: dict[str, _BrowserSession] = {}  # keyed by config.session_key (a UUID, not id(config))


def _get_or_create_session(config: "BrowserConfig") -> _BrowserSession:  # type: ignore[name-defined]
    """Return the cached session for this config, or create a fresh one."""
    key = config.session_key
    if key in _SESSIONS:
        return _SESSIONS[key]

    from playwright.sync_api import sync_playwright  # local import — keeps playwright optional

    pw = sync_playwright().start()
    # --disable-blink-features=AutomationControlled hides the most common
    # headless "tell" (navigator.webdriver / the CDP automation flag) that
    # login pages, consent managers, and bot-detection scripts check for.
    # Sites that spot it often don't error — they silently serve a
    # stripped-down page (missing real form fields, banner, etc.), which is
    # exactly the "fields stay blank, nothing throws" symptom this fixes.
    browser = pw.chromium.launch(
        headless=config.headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
    )
    # Patch the remaining automation fingerprints Chromium still exposes to
    # page JS even with the launch flag above.
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        window.chrome = window.chrome || { runtime: {} };
        """
    )
    session = _BrowserSession(browser=browser, context=context)
    
    def on_page(new_page: Any) -> None:
        session.active_pages.append(new_page)
        new_page.on("close", lambda p: session.active_pages.remove(p) if p in session.active_pages else None)
        
    context.on("page", on_page)
    
    _SESSIONS[key] = session
    return session


def close_session(config: "BrowserConfig") -> None:  # type: ignore[name-defined]
    """Close and discard the cached browser session for this config.
    Called after a session ends so the browser process is cleaned up."""
    key = config.session_key
    session = _SESSIONS.pop(key, None)
    if session is None:
        return
    try:
        session.context.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        session.browser.close()
    except Exception:  # noqa: BLE001
        pass


# ==========================================================================
# Login selector heuristics
# ==========================================================================
_LOGIN_USERNAME_CANDIDATES = [
    "input[name='username']",
    "input[name='email']",
    "input[name='user']",
    "input[name='login']",
    "input[type='email']",
    "input[id*='username' i]",
    "input[id*='email' i]",
    "input[id*='user' i]",
    "input[placeholder*='email' i]",
    "input[placeholder*='username' i]",
    "input[placeholder*='user' i]",
    "input[autocomplete='username']",
    "input[autocomplete='email']",
]

_LOGIN_PASSWORD_CANDIDATES = [
    "input[type='password']",   # always the most reliable — standard HTML
    "input[name='password']",
    "input[id*='password' i]",
    "input[placeholder*='password' i]",
    "input[autocomplete='current-password']",
]

_LOGIN_SUBMIT_CANDIDATES = [
    "button[type='submit']",
    "input[type='submit']",
    "button[aria-label*='sign in' i]",
    "button[aria-label*='log in' i]",
    "button[aria-label*='login' i]",
    "button[aria-label*='continue' i]",
    "button[name='login']",
    "button[id*='login' i]",
    "button[id*='signin' i]",
    "button[class*='login' i]",
    "button[class*='signin' i]",
    "form button:last-of-type",
]


def _auto_detect_login_selectors(page: Any, login_url: str) -> dict[str, str]:
    """Detect username, password, and submit selectors on a login page.
    Uses heuristic candidate lists — no vision model required.
    Returns dict with keys 'username', 'password', 'submit'.
    Raises BrowserAuthError if any role cannot be found.
    """
    # Give the login page a moment to render
    page.wait_for_timeout(2000)

    detected: dict[str, str] = {}

    u = _find_first_matching(page, _LOGIN_USERNAME_CANDIDATES)
    if u:
        detected["username"] = u

    p = _find_first_matching(page, _LOGIN_PASSWORD_CANDIDATES)
    if p:
        detected["password"] = p

    s = _find_first_matching(page, _LOGIN_SUBMIT_CANDIDATES)
    if s:
        detected["submit"] = s

    missing = [k for k in ("username", "password", "submit") if k not in detected]
    if missing:
        print(f"[browser debug] Login heuristics missed {missing}, falling back to LLM HTML analysis...")
        try:
            clean_html = page.evaluate('''() => {
                let clone = document.body.cloneNode(true);
                clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(el => el.remove());
                return clone.innerHTML;
            }''')
            from config.llm_config import get_llm
            llm = get_llm()
            prompt = f"""You are a web automation expert finding CSS selectors for Playwright.
Below is the stripped HTML of a login page at {login_url}.
We still need CSS selectors for: {missing}

Identify the BEST, MOST UNIQUE CSS selector for each missing element.
- 'username': The text input for the username or email.
- 'password': The password input.
- 'submit': The log in or sign in submit button.

Respond in EXACTLY this format (one selector per line, no explanation, only for the missing ones):
USERNAME_SELECTOR: <selector>
PASSWORD_SELECTOR: <selector>
SUBMIT_SELECTOR: <selector>

HTML:
{clean_html[:30000]}"""

            answer = llm.call(messages=[{"role": "user", "content": prompt}])
            if not isinstance(answer, str):
                answer = str(answer)
                
            for line in answer.strip().splitlines():
                if line.startswith("USERNAME_SELECTOR:") and "username" in missing:
                    detected["username"] = line.split(":", 1)[1].strip()
                elif line.startswith("PASSWORD_SELECTOR:") and "password" in missing:
                    detected["password"] = line.split(":", 1)[1].strip()
                elif line.startswith("SUBMIT_SELECTOR:") and "submit" in missing:
                    detected["submit"] = line.split(":", 1)[1].strip()
                    
            missing = [k for k in ("username", "password", "submit") if k not in detected]
        except Exception as e:
            from config.llm_config import MissingAPIKeyError
            if isinstance(e, MissingAPIKeyError):
                raise BrowserAuthError(
                    f"LLM fallback for login selector detection cannot run: no API key is configured. "
                    f"Set LLM_PROVIDER and the matching *_API_KEY in your .env file. Error: {e}\n\n"
                    f"WORKAROUND: Provide username_selector, password_selector, and submit_selector "
                    f"manually in the form's login section."
                ) from e
            print(f"[browser debug] LLM HTML fallback for login failed: {e}")

    if missing:
        role_hints = {
            "username": "the username / email input",
            "password": "the password input",
            "submit":   "the login submit button",
        }
        hints = "; ".join(f"'{k}' ({role_hints[k]})" for k in missing)
        raise BrowserAuthError(
            f"Auto-detection (heuristics + LLM fallback) could not identify login selectors for: {hints} "
            f"on '{login_url}'. "
            f"Please provide them manually in the form's login section."
        )
    return detected


# ==========================================================================
# Debug screenshots — headless runs have no one watching the browser, so
# these are the only way to see what a login step actually rendered.
# ==========================================================================
def _debug_screenshot(page: Any, label: str) -> None:
    """Best-effort screenshot saved to ./debug_screenshots/. Never raises."""
    try:
        from pathlib import Path

        out_dir = Path("debug_screenshots")
        out_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"{ts}_{label}.png"
        page.screenshot(path=str(path))
        print(f"[browser debug] saved screenshot: {path}")
    except Exception as e:  # noqa: BLE001
        print(f"[browser debug] screenshot failed for '{label}': {e}")


# ==========================================================================
# Error diagnostics — every Playwright failure in this file used to collapse
# into one generic "selector not found" string regardless of whether the
# real cause was a genuine 0-match miss, a strict-mode ambiguity (2+
# matches), a timeout, or a closed/detached target. These two helpers add
# that context back without changing the exception TYPES raised (still
# BrowserAuthError/BrowserSelectorError/etc — nothing downstream that
# catches those breaks) — only the message gets more specific.
# ==========================================================================
def _classify_error(e: Exception) -> str:
    """Best-effort label for the underlying Playwright exception, so error
    messages don't collapse every failure into one indistinguishable shape.
    Never raises; falls back to the raw exception class name."""
    try:
        from playwright.sync_api import TimeoutError as PWTimeoutError
    except Exception:  # pragma: no cover - playwright not installed
        PWTimeoutError = ()  # type: ignore[assignment]

    if PWTimeoutError and isinstance(e, PWTimeoutError):
        return "TimeoutError"

    msg = str(e)
    if "strict mode violation" in msg:
        return "StrictModeViolation"
    if "Target closed" in msg or "has been closed" in msg:
        return "TargetClosedError"
    if "detached" in msg.lower():
        return "ElementDetached"
    if "intercept" in msg.lower():
        return "ElementIntercepted"
    return type(e).__name__


def _selector_diagnostic(page: Any, sel: str) -> str:
    """Best-effort extra context: how many elements `sel` currently matches.
    Distinguishes '0 matches, genuinely not on the page' from '2+ matches,
    ambiguous/strict-mode' — two very different root causes that used to
    look identical from the raised error's text alone. Never raises."""
    try:
        count = page.locator(sel).count()
    except Exception:  # noqa: BLE001
        return ""
    if count == 0:
        return " (selector currently matches 0 elements)"
    if count > 1:
        return f" (selector currently matches {count} elements — ambiguous/strict-mode)"
    return " (selector matches exactly 1 element — likely a timing/visibility issue, not a missing-element one)"


# ==========================================================================
# Frame-aware fallback resolution — every selector call in this file used to
# only ever look at the main page. Embeddable chat widgets are commonly
# delivered inside an <iframe>; when that's the case, page.wait_for_selector()
# / page.query_selector() alone find nothing and the failure gets
# misreported as "selector not found" rather than "selector exists, but in a
# different frame" — the one place this file DID already look inside frames
# was the cookie-banner dismissal loop in _do_login. These two helpers are
# only ever consulted as a fallback AFTER a page-level lookup has already
# failed, so a site where every element lives on the main page (the common
# case, and everything tested against so far) sees zero behavior or timing
# change — this is purely additive.
# ==========================================================================
def _find_in_frames(page: Any, sel: str) -> Optional[Any]:
    """Search the page's CHILD frames (not the main frame, which callers
    already try first) for a selector matching exactly one visible element.
    Returns the Frame if found, else None."""
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            locator = frame.locator(sel)
            if locator.count() == 1 and locator.first.is_visible():
                return frame
        except Exception:  # noqa: BLE001
            continue
    return None


def _query_in_frames(page: Any, sel: str) -> Any:
    """Best-effort single query (no wait) across child frames for `sel`.
    Returns the first matching ElementHandle found, or None. Used for
    one-shot snapshots (existing-response-text capture, fixed_delay reads)
    rather than the strict-count check _find_in_frames does for
    interaction targets."""
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            el = frame.query_selector(sel)
            if el is not None:
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _ensure_visible_sel(sel: str) -> str:
    """For INPUT and SEND selectors: if multiple elements match, take the first visible one.
    Prevents strict-mode timeouts when hidden variants (e.g. mobile layout) come first.
    """
    if "visible=" not in sel.lower() and "nth=" not in sel.lower():
        return f"{sel} >> visible=true >> nth=0"
    return sel


def _ensure_visible_response_sel(sel: str) -> str:
    """For RESPONSE selectors: ensure visibility but do NOT pin to nth=0.
    Chat responses are appended to the END of a list — pinning to nth=0
    always watches the *first* message (which never changes after the
    first round) instead of the *latest* bot reply.

    We strip any existing `>> nth=N` suffix so auto-detected selectors
    that already embed `:last-child` work without a conflicting nth pin.
    """
    import re as _re
    # Remove any trailing >> nth=N the caller may have added
    sel = _re.sub(r"\s*>>\s*nth=\d+", "", sel).strip()
    if "visible=" not in sel.lower():
        return f"{sel} >> visible=true"
    return sel

def _wait_for_selector_with_frames(
    page: Any,
    sel: str,
    timeout_ms: int,
    state: Optional[str] = None,
) -> Any:
    """Wait for `sel` on the main page first (unchanged fast path for the
    common case). If that times out, fall back to checking child frames
    before giving up.
    
    Returns the Locator targeting the visible element.
    """
    sel = _ensure_visible_sel(sel)
        
    try:
        kwargs: dict[str, Any] = {"timeout": timeout_ms}
        if state is not None:
            kwargs["state"] = state
        page.wait_for_selector(sel, **kwargs)
        return page.locator(sel)
    except Exception:  # noqa: BLE001
        frame = _find_in_frames(page, sel)
        if frame is not None:
            return frame.locator(sel)
        raise


# ==========================================================================
# Login helper
# ==========================================================================
def _do_login(page: Any, config: "BrowserConfig") -> None:  # type: ignore[name-defined]
    """Perform the automated login sequence on a fresh page.

    If username_selector / password_selector / submit_selector are blank,
    auto-detects them using heuristics before filling the form.

    Raises BrowserAuthError on any failure.
    """
    timeout_ms = int(config.wait_timeout_seconds * 1000)

    try:
        page.goto(config.login_url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as e:  # noqa: BLE001
        raise BrowserAuthError(
            f"Browser: could not navigate to login URL '{config.login_url}': {e}"
        ) from e

    # ---- Resolve login selectors (auto-detect if any are blank) ----------
    needs_detect = (
        not (config.username_selector or "").strip()
        or not (config.password_selector or "").strip()
        or not (config.submit_selector or "").strip()
    )
    if needs_detect:
        login_sels = _auto_detect_login_selectors(page, config.login_url)
        username_sel = (config.username_selector or "").strip() or login_sels["username"]
        password_sel = (config.password_selector or "").strip() or login_sels["password"]
        submit_sel   = (config.submit_selector or "").strip()   or login_sels["submit"]
    else:
        username_sel = config.username_selector
        password_sel = config.password_selector
        submit_sel   = config.submit_selector

    _debug_screenshot(page, "01_login_page_loaded")

    # Give the page (and any consent-manager script, which often injects
    # its banner a beat after first paint) time to actually render. 1000ms
    # was too tight for a lot of real sites, so the banner was frequently
    # still missing when this loop checked for it.
    page.wait_for_timeout(2000)

    # Attempt to dismiss common cookie banners — check the main page AND
    # every child frame, since consent managers (OneTrust, Cookiebot, etc.)
    # very often render their banner inside an <iframe> rather than
    # directly in the page, which page.locator()/page.click() alone won't
    # reach.
    cookie_buttons = [
        "button:has-text('I agree')",
        "button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('Got it')",
        "button:has-text('Allow all')",
        "[id*='onetrust-accept' i]",
        "[id*='cookie-accept' i]",
    ]
    for frame in page.frames:
        for btn in cookie_buttons:
            try:
                locator = frame.locator(btn).first
                if locator.is_visible(timeout=1500):
                    locator.click(timeout=3000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

    _debug_screenshot(page, "02_after_cookie_dismiss")

    # Fill username
    try:
        username_locator = _wait_for_selector_with_frames(page, username_sel, timeout_ms, state="visible")
        username_locator.fill(config.username or "")
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "02_username_failed")
        raise BrowserAuthError(
            f"[{_classify_error(e)}] Browser: username selector '{username_sel}' "
            f"not found or not actionable{_selector_diagnostic(page, username_sel)}: {e}"
        ) from e

    # Fill password
    try:
        password_locator = _wait_for_selector_with_frames(page, password_sel, timeout_ms, state="visible")
        password_locator.fill(config.password or "")
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "03_password_failed")
        raise BrowserAuthError(
            f"[{_classify_error(e)}] Browser: password selector '{password_sel}' "
            f"not found or not actionable{_selector_diagnostic(page, password_sel)}: {e}"
        ) from e

    _debug_screenshot(page, "04_form_filled")

    # Click submit
    try:
        submit_locator = _wait_for_selector_with_frames(page, submit_sel, timeout_ms, state="visible")
        submit_locator.click()
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "05_submit_failed")
        raise BrowserAuthError(
            f"[{_classify_error(e)}] Browser: submit selector '{submit_sel}' "
            f"not clickable{_selector_diagnostic(page, submit_sel)}: {e}"
        ) from e

    # Wait for successful login
    #
    # This branch used to be the one place in _do_login with NO
    # _debug_screenshot() call on failure — every other step here takes one,
    # but a timeout/failure right here (the actual point real runs have been
    # failing at) previously raised with zero visual evidence of what the
    # page actually looked like. Both branches below now capture a
    # screenshot immediately before raising, and the error message includes
    # the classified exception type plus (for the selector branch) how many
    # elements the selector currently matches, so "wrong success selector"
    # and "genuinely stuck on login" no longer look identical from the
    # outside.
    if config.login_success_url_contains:
        try:
            page.wait_for_url(
                f"**{config.login_success_url_contains}**",
                timeout=timeout_ms,
            )
            # FIX: give SPA time to write to localStorage before closing the page
            page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            _debug_screenshot(page, "07_login_wait_failed")
            raise BrowserAuthError(
                f"[{_classify_error(e)}] Browser: after clicking submit, URL did not contain "
                f"'{config.login_success_url_contains}' within "
                f"{config.wait_timeout_seconds}s. Still on: {page.url!r}, title: {page.title()!r}. "
                f"Possible wrong credentials, wrong login_success_url_contains value, or CAPTCHA. "
                f"Error: {e}"
            ) from e
    elif config.login_success_selector:
        try:
            page.wait_for_selector(config.login_success_selector, timeout=timeout_ms)
            # FIX: give SPA time to write to localStorage before closing the page
            page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            _debug_screenshot(page, "07_login_wait_failed")
            raise BrowserAuthError(
                f"[{_classify_error(e)}] Browser: login success element "
                f"'{config.login_success_selector}' did not appear within "
                f"{config.wait_timeout_seconds}s{_selector_diagnostic(page, config.login_success_selector)}. "
                f"Still on: {page.url!r}, title: {page.title()!r}. "
                f"Possible wrong credentials, wrong login_success_selector value, or CAPTCHA. "
                f"Error: {e}"
            ) from e
    else:
        # Generic fallback: wait 3s for the page to settle after submit
        page.wait_for_timeout(3000)

    _debug_screenshot(page, "06_login_success")



# ==========================================================================
# Main connector function
# ==========================================================================
def call_browser_aut(task: str, config: "BrowserConfig") -> AUTResponse:  # type: ignore[name-defined]
    """Open (or reuse) a browser, interact with the chatbot UI, and return
    the response text.

    This is the implementation called by aut/connector.py's _call_browser().
    It is kept here (separate file) to keep playwright's import isolated —
    the rest of the system never touches playwright directly.
    """
    timeout_ms = int(config.wait_timeout_seconds * 1000)

    session = _get_or_create_session(config)

    if session.main_page is None or session.main_page.is_closed():
        session.main_page = session.context.new_page()

    page = _ActivePageProxy(session)

    # ---- Login (once per session) ----------------------------------------
    if config.requires_login and not session.logged_in:
        try:
            _do_login(page, config)
            session.logged_in = True
        except Exception:
            # If login fails, we don't want to leave the page in a broken half-logged-in state
            session.main_page.close()
            raise

    # ---- Open chatbot page -----------------------------------------------
    start = time.perf_counter()

    try:
        current_url = page.url
        needs_navigation = True
        
        # For Single Page Applications (SPAs), forcing a page.goto() when we are already
        # on the correct page causes a hard browser reload. This can abort pending background 
        # login API calls or completely wipe volatile in-memory auth states (like Redux stores),
        # throwing the user straight back to the login screen.
        if current_url.rstrip("/") == config.chatbot_url.rstrip("/"):
            needs_navigation = False
        else:
            from urllib.parse import urlparse
            curr_p = urlparse(current_url)
            tgt_p = urlparse(config.chatbot_url)
            log_p = urlparse(config.login_url) if config.login_url else None
            
            # If the SPA natively routed us to a different path on the same host,
            # trust its native routing over forcing a hard reload, BUT only if
            # we actually left the login page.
            if curr_p.netloc == tgt_p.netloc and log_p and curr_p.path != log_p.path:
                tgt_path = tgt_p.path.rstrip("/")
                if tgt_path == "" or curr_p.path.startswith(tgt_path):
                    needs_navigation = False

        if needs_navigation:
            try:
                page.goto(config.chatbot_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:  # noqa: BLE001
                raise AUTConnectorError(
                    f"browser: could not navigate to chatbot URL '{config.chatbot_url}': {e}"
                ) from e

        # ---- Open the chat widget if it's gated behind a launcher button --
        # Some chat UIs (e.g. a floating "Open Assistant" icon) don't mount
        # the input/send/response elements into the DOM at all until this
        # is clicked — auto-detect or a manually given input_selector would
        # otherwise time out waiting for something that doesn't exist yet.
        # Only done once per page (each call opens a fresh page, so this
        # runs on every round — cheap, and idempotent if already open).
        if config.chat_launcher_selector:
            try:
                launcher_locator = _wait_for_selector_with_frames(
                    page, config.chat_launcher_selector, timeout_ms, state="visible"
                )
                launcher_locator.click()
                page.wait_for_timeout(500)  # let the modal/panel actually mount
            except Exception as e:  # noqa: BLE001
                raise BrowserSelectorError(
                    f"[{_classify_error(e)}] browser: chat launcher selector "
                    f"'{config.chat_launcher_selector}' not found or not clickable "
                    f"on '{config.chatbot_url}'{_selector_diagnostic(page, config.chat_launcher_selector)}: {e}"
                ) from e

        # ---- Auto-detect selectors if any were left blank -------------------
        # Resolve once, cache for all subsequent rounds (auto_detect_selectors
        # reads from _SELECTOR_CACHE after the first call so this is cheap).
        needs_detect = (
            not config.input_selector.strip()
            or not config.send_selector.strip()
            or not config.response_selector.strip()
        )
        if needs_detect:
            detected = auto_detect_selectors(page, config.chatbot_url, config)
            input_sel = config.input_selector.strip() or detected["input"]
            send_sel = config.send_selector.strip() or detected["send"]
            response_sel = config.response_selector.strip() or detected["response"]
            # NOTE: auto_detect_selectors now handles the launcher click + re-detection
            # internally, so we don't need to click it here again.
        else:
            input_sel = config.input_selector
            send_sel = config.send_selector
            response_sel = config.response_selector

        # Apply visibility filters:
        # INPUT + SEND: use nth=0 (first visible) to handle hidden duplicate elements (e.g. mobile layout variants)
        # RESPONSE: do NOT use nth=0 — chatbot responses are appended at the END, so we must watch the last one
        input_sel = _ensure_visible_sel(input_sel)
        send_sel = _ensure_visible_sel(send_sel)
        response_sel = _ensure_visible_response_sel(response_sel)

        # Wait for input element
        try:
            input_locator = _wait_for_selector_with_frames(page, input_sel, timeout_ms)
        except Exception as e:  # noqa: BLE001
            _debug_screenshot(page, "08_input_not_found")
            raise BrowserSelectorError(
                f"[{_classify_error(e)}] browser: input selector '{input_sel}' not found "
                f"on '{config.chatbot_url}' within {config.wait_timeout_seconds}s"
                f"{_selector_diagnostic(page, input_sel)}: {e}"
            ) from e

        # Capture existing response text (for text_change detection) or DOM node (for new_element).
        # Also checks child frames — a one-shot fallback, no wait.
        existing_response_text = ""
        try:
            if config.wait_strategy == "text_change":
                # Snapshot the LAST visible element — chat UIs append at the bottom
                loc = page.locator(response_sel)
                cnt = loc.count()
                el_snap = loc.last if cnt > 0 else (page.query_selector(response_sel) or _query_in_frames(page, response_sel))
                existing_response_text = ""
                if el_snap:
                    try:
                        existing_response_text = el_snap.inner_text() or ""
                    except Exception:  # noqa: BLE001
                        existing_response_text = ""
            elif config.wait_strategy == "new_element":
                try:
                    page.locator(response_sel).evaluate("el => { window._evalmind_last_node = el; }")
                except Exception:  # noqa: BLE001
                    page.evaluate("() => { window._evalmind_last_node = null; }")
        except Exception:  # noqa: BLE001
            pass

        # Click input and type the task.
        try:
            input_locator.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(task, delay=30)
        except Exception as e:  # noqa: BLE001
            _debug_screenshot(page, "09_type_failed")
            raise BrowserSelectorError(
                f"[{_classify_error(e)}] browser: could not type into input "
                f"'{input_sel}'{_selector_diagnostic(page, input_sel)}: {e}"
            ) from e

        # Click send button
        try:
            send_locator = _wait_for_selector_with_frames(page, send_sel, timeout_ms)
            send_locator.click()
        except Exception as e:  # noqa: BLE001
            raise BrowserSelectorError(
                f"[{_classify_error(e)}] browser: send selector '{send_sel}' not found or "
                f"not clickable{_selector_diagnostic(page, send_sel)}: {e}"
            ) from e

        # ---- Verify the send actually did something -----------------------
        def _current_input_text() -> str:
            try:
                # the locator might be stale, query_selector is safer here
                el = page.query_selector(input_sel) or _query_in_frames(page, input_sel)
                if el is None:
                    return ""
            except Exception:  # noqa: BLE001
                return ""
            try:
                value = el.input_value()
                if value:
                    return value
            except Exception:  # noqa: BLE001
                pass  # not an input/textarea/select — fall through to inner_text
            try:
                return el.inner_text() or ""
            except Exception:  # noqa: BLE001
                return ""

        cleared = False
        clear_deadline = time.perf_counter() + 3.0
        while time.perf_counter() < clear_deadline:
            if task not in _current_input_text():
                cleared = True
                break
            page.wait_for_timeout(150)

        if not cleared:
            raise BrowserSelectorError(
                f"browser: clicked send selector '{send_sel}' but input "
                f"'{input_sel}' still contains the typed task 3s later. This "
                f"usually means send_sel resolved to the wrong element (a "
                f"heuristic like 'form button:last-of-type' can match a "
                f"toolbar/regenerate button instead of Send) rather than a "
                f"slow-to-respond chatbot. Provide an explicit send_selector "
                f"if this one was auto-detected."
            )

        # ---- Wait for response -------------------------------------------
        response_text = ""

        if config.wait_strategy == "new_element":
            # Wait for a strictly NEW DOM node matching response_selector to appear. 
            # Because we no longer force a hard reload between rounds, the OLD response 
            # from the previous round might already be in the DOM.
            try:
                deadline = time.perf_counter() + config.wait_timeout_seconds
                found = False
                while time.perf_counter() < deadline:
                    try:
                        is_new = page.locator(response_sel).evaluate("el => el !== window._evalmind_last_node")
                        if is_new:
                            found = True
                            break
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(100)
                    
                if not found:
                    raise TimeoutError(f"No new DOM node for '{response_sel}' appeared")
                    
                response_locator = _wait_for_selector_with_frames(page, response_sel, timeout_ms)
                response_text = response_locator.inner_text() or ""
            except Exception as e:  # noqa: BLE001
                _debug_screenshot(page, "10_response_wait_failed")
                raise BrowserTimeoutError(
                    f"[{_classify_error(e)}] browser: response selector '{response_sel}' "
                    f"did not appear within {config.wait_timeout_seconds}s"
                    f"{_selector_diagnostic(page, response_sel)}. Still on: {page.url!r}. Error: {e}"
                ) from e

        elif config.wait_strategy == "text_change":
            # Poll until inner_text of response_selector changes AND stays
            # unchanged for at least STABILITY_WINDOW_SECONDS.
            #
            # This used to accept the FIRST read that merely differed from
            # existing_response_text — a single differing read is a real
            # correctness gap for any UI that mutates the response node more
            # than once (e.g. shows a "typing…"/streaming partial, then
            # replaces it with the final text): the partial would get
            # captured and scored as if it were the finished answer. Now a
            # candidate text has to be read as unchanged across consecutive
            # polls spanning at least STABILITY_WINDOW_SECONDS before it's
            # accepted — a genuinely-finished response naturally satisfies
            # this within one extra poll cycle; a still-streaming one keeps
            # resetting the stability clock every time it mutates.
            STABILITY_WINDOW_SECONDS = 1.0
            deadline = time.perf_counter() + config.wait_timeout_seconds
            found = False
            last_seen_text: Optional[str] = None
            stable_since: Optional[float] = None
            while time.perf_counter() < deadline:
                try:
                    # IMPORTANT: use .last, not .first or query_selector (which returns the first DOM match).
                    # Chat UIs append new responses at the END of the message list.
                    # Watching the first match means we're always looking at the oldest message,
                    # which never changes after the first round.
                    locator = page.locator(response_sel)
                    count = locator.count()
                    el_handle = locator.last if count > 0 else None
                    if el_handle is None:
                        # Try child frames as fallback
                        el_handle = _query_in_frames(page, response_sel)
                    if el_handle:
                        try:
                            text = el_handle.inner_text()
                        except Exception:  # noqa: BLE001
                            text = ""
                        if text and text != existing_response_text:
                            if text != last_seen_text:
                                last_seen_text = text
                                stable_since = time.perf_counter()
                            elif (
                                stable_since is not None
                                and (time.perf_counter() - stable_since) >= STABILITY_WINDOW_SECONDS
                            ):
                                response_text = text
                                found = True
                                break
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(500)

            if not found:
                _debug_screenshot(page, "10_response_wait_failed")
                raise BrowserTimeoutError(
                    f"browser: response text did not change within "
                    f"{config.wait_timeout_seconds}s (selector: '{response_sel}')"
                    f"{_selector_diagnostic(page, response_sel)}. Still on: {page.url!r}. "
                    f"The chatbot may still be generating or the selector is wrong."
                )

        elif config.wait_strategy == "fixed_delay":
            page.wait_for_timeout(int(config.fixed_delay_seconds * 1000))
            try:
                el = page.query_selector(response_sel) or _query_in_frames(page, response_sel)
                response_text = el.inner_text() if el else ""
            except Exception as e:  # noqa: BLE001
                _debug_screenshot(page, "10_response_wait_failed")
                raise BrowserSelectorError(
                    f"[{_classify_error(e)}] browser: response selector '{response_sel}' "
                    f"not found after fixed delay{_selector_diagnostic(page, response_sel)}: {e}"
                ) from e

        latency_ms = (time.perf_counter() - start) * 1000

    finally:
        pass

    if not response_text.strip():
        raise AUTConnectorError(
            f"browser: response element '{config.response_selector}' was found "
            f"but contained no text. The chatbot may not have responded yet, or "
            f"the selector targets the wrong element."
        )

    return AUTResponse(
        output=response_text.strip(),
        latency_ms=latency_ms,
        tokens_used=None,
        estimated_cost=None,
    )
