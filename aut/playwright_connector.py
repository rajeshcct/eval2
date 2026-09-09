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
  instance (keyed by id(config)), reset between sessions (not between rounds
  unless persist_session=False). The connector is always called from a
  single worker thread inside asyncio.to_thread(), so no locking is needed.

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

# Cache: config id → {"input": sel, "send": sel, "response": sel}
_SELECTOR_CACHE: dict[int, dict[str, str]] = {}


def _find_first_matching(page: Any, candidates: list[str]) -> Optional[str]:
    """Return the first selector in candidates that finds a visible element."""
    for sel in candidates:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
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
        config:     BrowserConfig instance (used as cache key via id()).
        timeout_ms: how long to wait for JS to render before scanning.

    Returns:
        dict with keys 'input', 'send', 'response' → CSS selector strings.
    """
    key = id(config)
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
        role_hints = {
            "input":    "the chat text input / textarea",
            "send":     "the Send / Submit button",
            "response": "the element containing the bot's reply",
        }
        hints = "; ".join(
            f"'{k}' ({role_hints[k]})" for k in still_missing
        )
        raise BrowserAutoDetectError(
            f"Auto-detection could not identify selectors for: {hints} on '{url}'. "
            f"Please open the page in Chrome, right-click each element → "
            f"Inspect → copy the selector, and paste it into the form fields."
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


_SESSIONS: dict[int, _BrowserSession] = {}  # keyed by id(config)


def _get_or_create_session(config: "BrowserConfig") -> _BrowserSession:  # type: ignore[name-defined]
    """Return the cached session for this config, or create a fresh one."""
    key = id(config)
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
    _SESSIONS[key] = session
    return session


def close_session(config: "BrowserConfig") -> None:  # type: ignore[name-defined]
    """Close and discard the cached browser session for this config.
    Called after a session ends so the browser process is cleaned up."""
    key = id(config)
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
        role_hints = {
            "username": "the username / email input",
            "password": "the password input",
            "submit":   "the login submit button",
        }
        hints = "; ".join(f"'{k}' ({role_hints[k]})" for k in missing)
        raise BrowserAuthError(
            f"Auto-detection could not identify login selectors for: {hints} "
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
                    locator.click(force=True, timeout=3000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

    _debug_screenshot(page, "02_after_cookie_dismiss")

    # Fill username
    try:
        page.wait_for_selector(username_sel, state="visible", timeout=timeout_ms)
        page.fill(username_sel, config.username or "", force=True)
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "03_username_fill_failed")
        raise BrowserAuthError(
            f"Browser: username selector '{username_sel}' not found "
            f"on '{config.login_url}': {e}"
        ) from e

    # Fill password — this used to skip straight to fill() with no wait at
    # all, unlike username above. On SPA/React login pages the password
    # input can render a beat after the username field (or not exist yet
    # until a "Next" step completes), so fill() would either silently hit
    # nothing or throw a confusing low-level error. Waiting for it to be
    # visible first, same as username, is the main fix here.
    try:
        page.wait_for_selector(password_sel, state="visible", timeout=timeout_ms)
        page.fill(password_sel, config.password or "", force=True)
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "03_password_fill_failed")
        raise BrowserAuthError(
            f"Browser: password selector '{password_sel}' not found or not "
            f"visible within {config.wait_timeout_seconds}s: {e}. If this AUT's "
            f"login is a two-step flow (email first, password on a separate "
            f"screen after clicking Next/Continue), a single username+password "
            f"selector pair can't handle that — let me know and I'll adjust the "
            f"login flow to click through the intermediate step."
        ) from e

    _debug_screenshot(page, "04_form_filled")

    # Click submit
    try:
        page.click(submit_sel, force=True)
    except Exception as e:  # noqa: BLE001
        _debug_screenshot(page, "05_submit_failed")
        raise BrowserAuthError(
            f"Browser: submit selector '{submit_sel}' not found: {e}"
        ) from e

    # Wait for successful login
    if config.login_success_url_contains:
        try:
            page.wait_for_url(
                f"**{config.login_success_url_contains}**",
                timeout=timeout_ms,
            )
        except Exception as e:  # noqa: BLE001
            raise BrowserAuthError(
                f"Browser: after clicking submit, URL did not contain "
                f"'{config.login_success_url_contains}' within "
                f"{config.wait_timeout_seconds}s. Still on: {page.url!r}. "
                f"Possible wrong credentials or CAPTCHA. Error: {e}"
            ) from e
    elif config.login_success_selector:
        try:
            page.wait_for_selector(config.login_success_selector, timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            raise BrowserAuthError(
                f"Browser: login success element '{config.login_success_selector}' "
                f"did not appear within {config.wait_timeout_seconds}s. "
                f"Possible wrong credentials or CAPTCHA. Error: {e}"
            ) from e
    else:
        # Generic fallback: wait 2s for the page to settle after submit
        page.wait_for_timeout(2000)

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

    # ---- Login (once per session) ----------------------------------------
    if config.requires_login and not session.logged_in:
        login_page = session.context.new_page()
        try:
            _do_login(login_page, config)
            session.logged_in = True
        finally:
            login_page.close()

    # ---- Open chatbot page -----------------------------------------------
    page = session.context.new_page()
    start = time.perf_counter()

    try:
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
                page.wait_for_selector(config.chat_launcher_selector, state="visible", timeout=timeout_ms)
                page.click(config.chat_launcher_selector, force=True)
                page.wait_for_timeout(500)  # let the modal/panel actually mount
            except Exception as e:  # noqa: BLE001
                raise BrowserSelectorError(
                    f"browser: chat launcher selector '{config.chat_launcher_selector}' "
                    f"not found or not clickable on '{config.chatbot_url}': {e}"
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
        else:
            input_sel = config.input_selector
            send_sel = config.send_selector
            response_sel = config.response_selector

        # Wait for input element
        try:
            page.wait_for_selector(input_sel, timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            raise BrowserSelectorError(
                f"browser: input selector '{input_sel}' not found "
                f"on '{config.chatbot_url}' within {config.wait_timeout_seconds}s: {e}"
            ) from e

        # Capture existing response text (for text_change detection)
        existing_response_text = ""
        if config.wait_strategy == "text_change":
            try:
                el = page.query_selector(response_sel)
                existing_response_text = el.inner_text() if el else ""
            except Exception:  # noqa: BLE001
                existing_response_text = ""

        # Click input and type the task
        try:
            page.click(input_sel)
            # Clear any existing text first
            page.fill(input_sel, "")
            page.type(input_sel, task, delay=30)
        except Exception as e:  # noqa: BLE001
            raise BrowserSelectorError(
                f"browser: could not type into input '{input_sel}': {e}"
            ) from e

        # Click send button
        try:
            page.wait_for_selector(send_sel, timeout=timeout_ms)
            page.click(send_sel)
        except Exception as e:  # noqa: BLE001
            raise BrowserSelectorError(
                f"browser: send selector '{send_sel}' not found or "
                f"not clickable: {e}"
            ) from e

        # ---- Wait for response -------------------------------------------
        response_text = ""

        if config.wait_strategy == "new_element":
            # Wait for response_selector to appear (may not exist yet)
            try:
                page.wait_for_selector(response_sel, timeout=timeout_ms)
                el = page.query_selector(response_sel)
                response_text = el.inner_text() if el else ""
            except Exception as e:  # noqa: BLE001
                raise BrowserTimeoutError(
                    f"browser: response selector '{response_sel}' "
                    f"did not appear within {config.wait_timeout_seconds}s: {e}"
                ) from e

        elif config.wait_strategy == "text_change":
            # Poll until inner_text of response_selector changes
            deadline = time.perf_counter() + config.wait_timeout_seconds
            found = False
            while time.perf_counter() < deadline:
                try:
                    el = page.query_selector(response_sel)
                    if el:
                        text = el.inner_text()
                        if text and text != existing_response_text:
                            response_text = text
                            found = True
                            break
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(500)

            if not found:
                raise BrowserTimeoutError(
                    f"browser: response text did not change within "
                    f"{config.wait_timeout_seconds}s (selector: '{response_sel}'). "
                    f"The chatbot may still be generating or the selector is wrong."
                )

        elif config.wait_strategy == "fixed_delay":
            page.wait_for_timeout(int(config.fixed_delay_seconds * 1000))
            try:
                el = page.query_selector(response_sel)
                response_text = el.inner_text() if el else ""
            except Exception as e:  # noqa: BLE001
                raise BrowserSelectorError(
                    f"browser: response selector '{response_sel}' "
                    f"not found after fixed delay: {e}"
                ) from e

        latency_ms = (time.perf_counter() - start) * 1000

    finally:
        page.close()

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
