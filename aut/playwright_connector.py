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

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from aut.connector import AUTConnectorError, AUTResponse
from progress import emit_event


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


class BrowserTransientError(AUTConnectorError):
    """An unexpected (non-selector, non-timeout) browser/Playwright failure,
    e.g. the page or browser was closed mid-call. Raw Playwright exceptions
    are wrapped in this so callers only ever see AUTConnectorError
    subclasses (and so the retry wrapper in aut/connector.py can cover them)."""


# Selector-detection LLM calls get their own short, fail-fast timeout and a
# hard wall-clock budget for the whole auto_detect_selectors() sequence —
# previously neither existed: the LLM call itself had no timeout (falling
# back to whatever the provider SDK defaults to, commonly minutes), and
# nothing capped how long the up-to-4-step chained sequence could run in
# total. A slow/rate-limited response on any one step used to be
# indistinguishable, from the caller's side, from a genuine hang.
SELECTOR_DETECT_TIMEOUT_SECONDS = 20.0
SELECTOR_DETECT_MAX_TOKENS = 300
AUTO_DETECT_BUDGET_SECONDS = 55.0


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
    # Generic patterns
    "[data-testid*='bot-message']",
    "[data-testid*='assistant']",
    "[data-testid*='response']",
    "[data-testid*='answer']",
    ".assistant-message",
    ".bot-message",
    ".chat-message.bot",
    ".chat-message.ai",
    ".chat-bubble",
    ".message-bubble",
    "[class*='bot-message']",
    "[class*='ai-message']",
    "[role='article']",
    # ChatGPT (chatgpt.com)
    "[data-message-author-role='assistant']",
    ".markdown.prose",
    # Claude (claude.ai)
    "[data-is-streaming='false']",
    ".font-claude-message",
    # Perplexity
    ".prose",
    # Grok / X
    "[class*='message-bubble']",
    # Copilot
    "[class*='ac-container']",
]

# Sentinel stored in the selector cache when response-container detection
# fails entirely. When call_browser_aut() sees this sentinel for response_sel
# it activates the "page-transcript" fallback: type + Enter, wait for the page
# to settle, then read the full visible page text and slice out everything that
# appears after the user's own question text to isolate the bot's reply.
_RESPONSE_SEL_FALLBACK = "__page_transcript__"

# Cache: config.session_key → {"input": sel, "send": sel, "response": sel}
# Keyed by the UUID-based BrowserConfig.session_key (see that field's
# docstring in aut/connector.py) rather than id(config) — id() is a memory
# address CPython reuses after garbage collection, which previously let a
# later, unrelated BrowserConfig silently inherit an earlier run's cached
# selectors for a completely different site.
_SELECTOR_CACHE: dict[str, dict[str, Optional[str]]] = {}

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

# Keywords that reveal a generic page container or an input/send control
# rather than an actual bot reply message bubble.
_NOT_CHAT_RESPONSE_CLUES = (
    "card-body",        # Bootstrap generic card — present from page load
    "card",
    "dashboard",
    "sidebar",
    "navbar",
    "header",
    "footer",
    "modal",
    "input",            # never an input box!
    "textarea",
    "textbox",
    "send",             # never a send button!
    "submit",
    "button",
    "composer",
    "compose",
)


def _is_chat_input_selector(sel: str) -> bool:
    """Return False if the selector looks like a dropdown / filter, not a chat input."""
    s = sel.lower()
    return not any(clue in s for clue in _NOT_CHAT_INPUT_CLUES)


def _is_chat_response_selector(sel: str) -> bool:
    """Return False if the selector looks like a generic page section, not a message container."""
    s = sel.lower()
    return not any(clue in s for clue in _NOT_CHAT_RESPONSE_CLUES)


# Keywords that betray a selector as something other than the actual
# 'submit this message' button — a regenerate/attach/mic/like button, or
# an unrelated submit button elsewhere on the page (login, search,
# newsletter signup). SEND previously had no equivalent filter at all,
# unlike INPUT and RESPONSE above.
_NOT_CHAT_SEND_CLUES = (
    "regenerate",
    "delete",
    "remove",
    "clear",
    "copy",
    "thumb",
    "like",
    "dislike",
    "attach",
    "upload",
    "mic",
    "microphone",
    "voice",
    "emoji",
    "stop",
    "cancel",
    "close",
    "menu",
    "search",
    "filter",
    "login",
    "signin",
    "sign-in",
    "subscribe",
    "newsletter",
)


def _is_chat_send_selector(sel: str) -> bool:
    """Return False if the selector looks like it targets something other
    than the chat's actual send/submit button."""
    s = sel.lower()
    return not any(clue in s for clue in _NOT_CHAT_SEND_CLUES)


# Launcher candidates — floating "open chat" buttons that some widgets
# require clicking before ANY of input/send/response exist in the DOM.
_LAUNCHER_CANDIDATES = [
    "[data-testid*='launcher']",
    "[data-testid*='chat-toggle']",
    "[data-testid*='chat-button']",
    "[aria-label*='open chat' i]",
    "[aria-label*='chat assistant' i]",
    "[aria-label*='chat' i]",
    "[class*='chat-launcher']",
    "[class*='chat-widget-button']",
    "[class*='chat-bubble']",
    "[class*='launcher']",
    "[id*='chat-launcher']",
    "[id*='chat-widget-button']",
    # Common AI assistant / chatbot floating button patterns
    ".ai-assistant-btn",
    "[class*='ai-assistant-btn']",
    "[class*='ai-assistant'][class*='btn']",
    "[class*='ai-assistant'][class*='button']",
    "[class*='chatbot-btn']",
    "[class*='chatbot-button']",
    "[class*='chat-btn']",
    "[class*='chat-button']",
    "[class*='assistant-btn']",
    "[class*='assistant-button']",
    "[class*='chat-toggle']",
    "[class*='chat-open']",
    "[class*='open-chat']",
    "[id*='ai-assistant']",
    "[id*='chatbot-btn']",
    "[id*='chat-btn']",
]


def _clean_selector(raw: str) -> str:
    """Strip common LLM formatting artifacts (backticks, wrapping quotes,
    markdown bold, trailing punctuation) before a selector is ever handed
    to Playwright."""
    s = raw.strip()
    s = s.strip("`").strip("*").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s.rstrip(".,;").strip()


_SELECTOR_LINE_RE = re.compile(
    r"^\s*(INPUT|SEND|RESPONSE|LAUNCHER|USERNAME|PASSWORD|SUBMIT)[_ ]?SELECTOR\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _parse_selector_lines(answer: str) -> dict[str, str]:
    """Robustly parse 'ROLE_SELECTOR: value' lines out of an LLM answer.
    Tolerant of extra whitespace around the colon, lowercase role names,
    and 'ROLE SELECTOR' (space instead of underscore)."""
    out: dict[str, str] = {}
    for line in answer.strip().splitlines():
        m = _SELECTOR_LINE_RE.match(line)
        if not m:
            continue
        role = m.group(1).lower()
        val = _clean_selector(m.group(2))
        if val and val.lower() not in ("none", "null", ""):
            out[role] = val
    return out


def _has_top_level_comma(sel: str) -> bool:
    """True if `sel` contains a comma OUTSIDE of [...] attribute brackets
    and outside of quoted strings — i.e. it's a genuine CSS selector LIST
    ('a, b') rather than a single selector whose own syntax happens to
    contain a comma (e.g. an attribute value like [data-foo="a,b"]).

    An LLM-returned selector list is a real, previously-unguarded failure
    mode: nothing forbade the model from hedging with 'textarea,
    input[placeholder*="message" i]', and _selector_exists() accepted it
    outright (a comma-list matching 1+ elements TOTAL across ALL its
    alternatives passes page.locator(sel).count() >= 1 just as happily as
    a genuine single-element selector). The final `>> nth=0` suffix
    _ensure_visible_sel applies later then picks whichever alternative
    happens to come first in DOCUMENT ORDER — not necessarily the one the
    model actually meant — so 'exists' silently stopped meaning 'resolves
    to the right element'.
    """
    depth = 0
    in_quote: Optional[str] = None
    for ch in sel:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return True
    return False


def _selector_exists(page: Any, sel: str) -> bool:
    """Best-effort check that `sel` currently resolves to at least one
    element in the live DOM. An LLM-sourced selector previously had NO
    such check — a hallucinated string was trusted outright and only
    failed much later, at click time, with a confusing error."""
    try:
        return page.locator(sel).count() >= 1
    except Exception:  # noqa: BLE001
        return False


def _cached_selectors_still_valid(page: Any, cached: dict[str, str]) -> bool:
    """Cheap re-validation of a previously-cached selector set against the
    CURRENT live DOM, before trusting it for another round.

    A selector cached from an earlier round can go stale if the chat
    widget's DOM changes mid-session (an SPA re-render after a client-side
    route change, an A/B-tested markup swap, a modal that gets torn down
    and rebuilt with new attributes). Previously the cache was never
    invalidated or re-checked: a stale entry sailed straight through
    auto_detect_selectors() and only failed much later, downstream, after
    _wait_for_selector_with_frames() burned the FULL wait_timeout_seconds
    waiting on a selector that was never going to appear — and (before the
    retry fix in aut/connector.py::call_aut_with_retry) that failure took
    down the whole session rather than just that one round.

    Only 'input' and 'send' (the two interaction targets) and 'response'
    are checked — 'launcher' is deliberately excluded: it's a one-time
    toggle, and a widget commonly hides or repurposes that element once
    the panel is already open, so its absence on a later round is expected
    behavior, not staleness. This only asks "does the selector resolve to
    at least one element" (via the same _selector_exists check LLM
    candidates are validated with), never "does it currently have text" —
    a momentarily-empty response container between rounds is normal.
    """
    for role in ("input", "send", "response"):
        sel = cached.get(role)
        if not sel:
            continue
        if not _selector_exists(page, sel):
            return False
    return True


def _find_scoped_send_candidate(page: Any, input_sel: str, candidates: list[str]) -> Optional[str]:
    """Search SEND candidates only within a nearby ancestor of the input
    element, instead of the whole page. Marks that ancestor with a
    throwaway data attribute via a JS walk (climbs up to 5 levels,
    stopping early at the nearest <form>), scopes the Playwright search to
    it, then always removes the marker in a finally block. A candidate is
    only accepted if it ALSO resolves to exactly one element against the
    WHOLE page — downstream code (call_browser_aut) re-queries the
    returned string as a plain, unscoped page.locator(sel), so a selector
    that's unique inside the container but ambiguous globally would break
    later. This is what actually stops an unrelated submit button
    elsewhere on the page (login/search/newsletter form) from winning the
    'send' role, rather than only rejecting it after the fact."""
    try:
        marked = page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                let node = el;
                for (let i = 0; i < 5; i++) {
                    if (!node.parentElement) break;
                    node = node.parentElement;
                    if (node.tagName === 'FORM') break;
                }
                node.setAttribute('data-evalmind-scope', 'send-search');
                return true;
            }""",
            input_sel,
        )
    except Exception:  # noqa: BLE001
        marked = False

    if not marked:
        return None

    try:
        container = page.locator("[data-evalmind-scope='send-search']").first
        for sel in candidates:
            try:
                scoped = container.locator(sel)
                scoped_count = scoped.count()
                if scoped_count == 0:
                    continue
                if scoped_count == 1:
                    if not scoped.first.is_visible():
                        continue
                else:
                    # 2+ matches within the scoped container — same
                    # visible-only re-check as _find_first_matching, rather
                    # than discarding the candidate outright (a hidden
                    # duplicate inside the same compose row is common).
                    visible_scoped = container.locator(f"{sel} >> visible=true")
                    if visible_scoped.count() != 1:
                        continue
                if page.locator(sel).count() == 1:
                    return sel
                # If sel is ambiguous globally (e.g. other buttons exist on the dashboard),
                # try scoping it specifically to the chat widget wrapper.
                for wrapper in (".ai-assistant-wrapper", "[class*='assistant']", "[class*='chat']"):
                    scoped_sel = f"{wrapper} {sel}"
                    try:
                        if page.locator(scoped_sel).count() == 1:
                            return scoped_sel
                    except Exception:
                        continue
                continue
            except Exception:  # noqa: BLE001
                continue
        return None
    finally:
        try:
            page.evaluate("""() => {
                const n = document.querySelector('[data-evalmind-scope="send-search"]');
                if (n) n.removeAttribute('data-evalmind-scope');
            }""")
        except Exception:  # noqa: BLE001
            pass


def _stripped_body_html(page: Any, max_chars: int = 10000) -> str:
    """Full-page HTML with script/style/svg/media stripped, for the
    LAUNCHER/INPUT/RESPONSE LLM fallbacks, which need to see wherever in
    the page their target actually lives.
    
    Capped at 10,000 chars (~2,500 tokens) to strictly stay within low-tier
    provider token-per-minute quotas (such as Groq's 7,000 ITPM limit).
    """
    try:
        html = page.evaluate('''() => {
            let clone = document.body.cloneNode(true);
            clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(el => el.remove());
            return clone.innerHTML;
        }''')
        return html[:max_chars] if html else ""
    except Exception:  # noqa: BLE001
        return ""


def _get_input_container_html(page: Any, input_sel: str, max_chars: int = 6000) -> str:
    """Return the outerHTML of a small ancestor of the input element — the
    smallest container that plausibly holds the whole message-compose row
    (input + send button). Used to scope the SEND LLM fallback to a tiny,
    directly-relevant fragment instead of the entire page: a focused
    question over a few hundred bytes of genuinely relevant HTML is both
    far more reliable and far cheaper than asking over a 30k-char page
    dump. Climbs the same 5-levels/stop-at-<form> path as
    _find_scoped_send_candidate. Falls back to the full stripped body on
    any error."""
    try:
        html = page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                let node = el;
                for (let i = 0; i < 5; i++) {
                    if (!node.parentElement) break;
                    node = node.parentElement;
                    if (node.tagName === 'FORM') break;
                }
                const clone = node.cloneNode(true);
                clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(e => e.remove());
                return clone.outerHTML;
            }""",
            input_sel,
        )
        if html:
            return html[:max_chars]
    except Exception:  # noqa: BLE001
        pass
    return _stripped_body_html(page, max_chars=max_chars)


def _get_chat_panel_html(page: Any, input_sel: str, max_chars: int = 8000) -> str:
    """Return the stripped innerHTML of the chat panel/wrapper that contains
    input_sel. Scoping to this container keeps token size under ~2,000 tokens
    (well below provider RPM/ITPM limits) and avoids confusing the model with
    unrelated dashboard content.
    """
    try:
        html = page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                let node = el;
                for (let i = 0; i < 10; i++) {
                    if (!node.parentElement) break;
                    node = node.parentElement;
                    const cls = (node.className || '').toString().toLowerCase();
                    const id = (node.id || '').toLowerCase();
                    if (
                        cls.includes('assistant') ||
                        cls.includes('chat') ||
                        cls.includes('widget') ||
                        cls.includes('modal') ||
                        cls.includes('dialog') ||
                        id.includes('chat') ||
                        id.includes('assistant')
                    ) {
                        break;
                    }
                }
                const clone = node.cloneNode(true);
                clone.querySelectorAll('script, style, svg, path, img, video, iframe, noscript').forEach(e => e.remove());
                return clone.innerHTML;
            }""",
            input_sel,
        )
        if html and len(html.strip()) > 50:
            return html[:max_chars]
    except Exception:  # noqa: BLE001
        pass
    return _stripped_body_html(page, max_chars=max_chars)


def _get_llm_or_raise() -> Any:
    """Thin wrapper so a missing API key surfaces one clear, actionable
    error immediately instead of being silently swallowed step-by-step as
    'no selector found' with no explanation of why.

    Uses role="selector_detect" (its own model slot — see
    config/llm_config.py's VALID_ROLES — falling back to the provider's
    plain model if that role has no override configured), with a short
    fail-fast timeout and a small max_tokens cap: the expected answer is
    one short line, and this call must never be the thing that hangs an
    entire browser session.
    """
    from config.llm_config import get_llm, MissingAPIKeyError
    try:
        return get_llm(
            role="selector_detect",
            timeout=SELECTOR_DETECT_TIMEOUT_SECONDS,
            max_tokens=SELECTOR_DETECT_MAX_TOKENS,
        )
    except MissingAPIKeyError as e:
        raise BrowserAutoDetectError(
            f"LLM fallback cannot run: no API key is configured. "
            f"Set LLM_PROVIDER and the matching *_API_KEY in your .env file. "
            f"Error: {e}\n\n"
            f"WORKAROUND: Open the chatbot page in Chrome DevTools, right-click "
            f"each element → Inspect → Copy selector, then paste them into the "
            f"form's input_selector / send_selector / response_selector fields."
        ) from e


def _llm_ask_selector(llm: Any, prompt: str, role: str) -> Optional[str]:
    """Ask the LLM a SINGLE-PURPOSE question for exactly one selector role
    and return the parsed, comma-list-rejected candidate — or None.

    Deliberately does NOT touch the Playwright `page` object anywhere in
    this function: it's the page-independent half of what used to be one
    monolithic _llm_find_one_selector(), split out specifically so it's
    safe to run on a background thread (see _start_response_llm_job below)
    concurrently with another step that DOES need page access — Playwright's
    synchronous API is not safe to touch from two threads at once, but a
    plain LLM HTTP call + string parsing has no such restriction. The
    caller is responsible for the remaining page-touching validation
    (a semantic validator + _selector_exists) on whichever thread is
    allowed to touch `page` — see _llm_find_one_selector for the
    synchronous, single-thread version of that full sequence.
    """
    _RETRYABLE = ("503", "529", "429", "rate limit", "overload", "unavailable", "high demand")
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            answer = llm.call(messages=[{"role": "user", "content": prompt}])
            break
        except Exception as e:  # noqa: BLE001
            err_str = str(e).lower()
            is_retryable = any(tok in err_str for tok in _RETRYABLE)
            if is_retryable and attempt < max_attempts:
                wait = 5.0 * attempt
                print(f"[browser debug] LLM call for '{role}' failed (attempt {attempt}/{max_attempts}, retrying in {wait:.0f}s): {e}")
                time.sleep(wait)
            else:
                print(f"[browser debug] LLM call for '{role}' failed: {e}")
                return None
    else:
        return None

    if not isinstance(answer, str):
        answer = str(answer)
    print(f"[browser debug] LLM {role.upper()} RAW ANSWER:\n{answer[:1000]}")

    parsed = _parse_selector_lines(answer)
    candidate = parsed.get(role)
    if not candidate:
        print(f"[browser debug] LLM did not return a usable {role.upper()}_SELECTOR line")
        return None
    if _has_top_level_comma(candidate):
        print(
            f"[browser debug] LLM {role.upper()}_SELECTOR '{candidate}' rejected — "
            f"it's a comma-separated selector LIST, not a single selector "
            f"(ambiguous which alternative it actually means)"
        )
        return None
    return candidate


def _validate_llm_selector(candidate: Optional[str], role: str, page: Any, validator) -> Optional[str]:
    """The page-touching half of the old _llm_find_one_selector: given a
    candidate already parsed and comma-checked by _llm_ask_selector (on
    whichever thread produced it), run the semantic validator and the live-
    DOM existence check — both of which need `page` — on the CALLING
    thread. Must only ever be invoked from the single thread that's allowed
    to touch `page` (the main auto-detection thread), never from inside a
    background job's worker function."""
    if candidate is None:
        return None
    if not validator(candidate):
        print(f"[browser debug] LLM {role.upper()}_SELECTOR '{candidate}' rejected — fails semantic check for role '{role}'")
        return None
    if not _selector_exists(page, candidate):
        print(f"[browser debug] LLM {role.upper()}_SELECTOR '{candidate}' rejected — does not match any element in the live DOM (likely hallucinated)")
        return None
    return candidate


def _llm_find_one_selector(llm: Any, prompt: str, role: str, page: Any, validator) -> Optional[str]:
    """Ask the LLM a SINGLE-PURPOSE question for exactly one selector
    role, parse + validate the answer, and return it or None. Every
    sequential detection step below is its own focused question — this is
    the direct fix for the old design asking for 3-4 roles in one shot
    against a page where most of them didn't even exist yet (launcher-
    gated widgets) or weren't relevant (LAUNCHER on non-gated ones).

    Synchronous convenience wrapper around _llm_ask_selector() +
    _validate_llm_selector() for the three roles (launcher/input/send)
    that are never run concurrently with anything else. RESPONSE detection
    uses the two halves directly instead — see _start_response_llm_job.
    """
    candidate = _llm_ask_selector(llm, prompt, role)
    return _validate_llm_selector(candidate, role, page, validator)


@dataclass
class _ResponseDetectJob:
    """A RESPONSE-selector LLM lookup running on a background thread,
    started as soon as INPUT is known — RESPONSE doesn't depend on INPUT's
    resolved value or on SEND at all, only on the DOM already being in its
    final, post-launcher-click state, which is already true by the time
    INPUT is resolved. The worker thread (see _start_response_llm_job)
    calls ONLY _llm_ask_selector() — the page-independent half — so it
    never touches Playwright's `page` object while the main thread goes on
    to run SEND detection, which does need page access.

    Call join() from the main thread, after SEND detection is done, to get
    the raw (comma-checked but not yet page-validated) candidate or None.
    The caller must still run _validate_llm_selector() against the live
    page afterwards, on the main thread — exactly the same validation any
    other LLM candidate in this file gets, just deferred past the join.
    """

    thread: threading.Thread
    _result: list  # single-element box populated by the worker: [candidate_or_None]

    def join(self, timeout: Optional[float] = None) -> Optional[str]:
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            # The LLM call still hasn't returned even after SEND detection
            # finished and any extra grace period elapsed — extremely
            # unlikely given SELECTOR_DETECT_TIMEOUT_SECONDS, but don't
            # block the caller forever waiting on a daemon thread.
            print("[browser debug] RESPONSE background LLM job still running — not waiting further")
            return None
        return self._result[0] if self._result else None


def _start_response_llm_job(llm: Any, html: str, url: str) -> _ResponseDetectJob:
    """Schedule the RESPONSE LLM lookup on a background thread so it runs
    concurrently with SEND detection instead of strictly after it. `html`
    must already be captured by the CALLER on the main thread (a
    page.evaluate() call) — the worker below performs ONLY the LLM HTTP
    call and string parsing via _llm_ask_selector(), no Playwright access
    of any kind."""
    prompt = f"""You are a web automation expert. Below is the stripped HTML of a chatbot UI at {url}.

Find the CSS selector for the element that holds the BOT's reply messages (the latest one). Use :last-child or :last-of-type if it's a list. Do not pick a generic dashboard card, sidebar, or navbar.

For standard chatbots (ChatGPT, Claude, Perplexity, Copilot, Grok, etc.), the bot's response is typically inside a container class like `.markdown`, `.prose`, `.message[data-author='assistant']`, `.agent-turn`, or similar. You MUST target the text content of the BOT's message (not the user's message, and not the entire chat history container). If messages are in a list, target the last bot message specifically.

CRITICAL: Do NOT select .chat-input, input, textarea, composer, or send button. The selector MUST target a chat message bubble or bot reply element.

Give exactly ONE CSS selector — never a comma-separated list of alternatives.

Respond with EXACTLY one line:
RESPONSE_SELECTOR: <selector>

HTML:
{html}"""

    box: list = []

    def _worker() -> None:
        try:
            candidate = _llm_ask_selector(llm, prompt, "response")
        except Exception as e:  # noqa: BLE001 - a background thread must never raise uncaught
            print(f"[browser debug] RESPONSE background LLM job raised: {e}")
            candidate = None
        box.append(candidate)

    t = threading.Thread(target=_worker, daemon=True, name="response-selector-detect")
    t.start()
    return _ResponseDetectJob(thread=t, _result=box)


def _detect_launcher_only(page: Any, url: str) -> Optional[str]:
    """STEP: look for a floating 'open chat' button. Heuristics first,
    then a single-purpose LLM call if those miss. Returning None is the
    NORMAL, non-error outcome for a widget that's already inline on the
    page with no launcher at all."""
    heuristic = _find_first_matching(page, _LAUNCHER_CANDIDATES)
    if heuristic:
        return heuristic

    llm = _get_llm_or_raise()
    html = _stripped_body_html(page, max_chars=20000)
    prompt = f"""You are a web automation expert. Below is the stripped HTML of a page at {url}.

Is there a floating button, icon, or bubble whose job is to OPEN a chat/assistant panel (as opposed to a chat input that's already visible on the page)?

These launcher buttons are usually small, fixed-position elements (often bottom-right corner of the screen) and are commonly identified by wording such as: "chat", "chatbot", "AI chatbot", "AI assistant", "assistant", "support", "help", "ask us", "talk to us", "contact us", "live chat", "message us" -- look for these words, or close variants, in the element's class name, id, aria-label, title, alt text, or visible label. A speech-bubble / message-bubble icon with no visible text but one of these words in its aria-label/title/data-* attribute also counts.

Common class name patterns to look for: `ai-assistant-btn`, `chat-btn`, `chatbot-btn`, `chat-button`, `assistant-btn`, `ai-assistant-button`, `chat-toggle`, `chat-launcher`, `chat-bubble`, `launcher`.

IMPORTANT: If you can see any element in the HTML with a class or id containing 'ai-assistant', 'chatbot', 'chat-btn', 'chat-button', or 'launcher' — that is almost certainly the launcher button. Select it.

If the chat is already open/visible on the page and no such button is needed, answer None.

Give exactly ONE CSS selector — never a comma-separated list of alternatives.

Respond with EXACTLY one line:
LAUNCHER_SELECTOR: <selector or None>

HTML:
{html}"""
    return _llm_find_one_selector(llm, prompt, "launcher", page, lambda _sel: True)


def _detect_input_only(page: Any, url: str) -> Optional[str]:
    """STEP: single-purpose LLM fallback for the chat text input, used
    only after the heuristic list AND (if applicable) a launcher click
    have both already been tried."""
    llm = _get_llm_or_raise()
    html = _stripped_body_html(page)
    prompt = f"""You are a web automation expert. Below is the stripped HTML of a chatbot UI at {url}.

Find the CSS selector for the TEXT INPUT / TEXTAREA where a user TYPES their chat message -- the same kind of box used at the bottom of modern AI chat apps like Claude.ai or ChatGPT: a single message-composer field (a <textarea>, an auto-growing text box, or a contenteditable div acting like one) that sits near the bottom of the chat panel, typically right next to or just above a send button, often with placeholder text like "Message...", "Ask anything", "Type a message", "Type your message...", or similar chat-style wording.

Common targets for mainstream chatbots include `textarea`, elements with `contenteditable='true'` (like `.ProseMirror`), or fields with IDs/classes containing `prompt`, `composer`, `chat-input`, or `message`.

It must be an editable field for composing a NEW outgoing message -- not a dropdown, a site-wide search bar, a filter box, or an input belonging to some unrelated form elsewhere on the page (login, newsletter signup, etc.).

Give exactly ONE CSS selector — never a comma-separated list of alternatives.

Respond with EXACTLY one line:
INPUT_SELECTOR: <selector>

HTML:
{html}"""
    return _llm_find_one_selector(llm, prompt, "input", page, _is_chat_input_selector)


def _detect_send_only(page: Any, url: str, input_sel: str) -> Optional[str]:
    """STEP: detect the send button AFTER input is already known, scoped
    to input's own container. Both the heuristic search and (if needed)
    the HTML shown to the LLM are limited to that small fragment — not
    the whole page."""
    scoped = _find_scoped_send_candidate(page, input_sel, _SEND_CANDIDATES)
    if scoped and _is_chat_send_selector(scoped):
        return scoped

    llm = _get_llm_or_raise()
    html = _get_input_container_html(page, input_sel)
    prompt = f"""You are a web automation expert. Below is a small HTML fragment containing the chat text input for a page at {url} (its selector is '{input_sel}').

Find the CSS selector for the SEND / SUBMIT button that posts this message. It should be inside or very near this fragment. Do not pick a regenerate, attach, mic, or emoji button. Often this is a `<button>` with an `aria-label='Send message'`, an icon like a paper airplane or up-arrow, or a button with a `data-testid='send-button'`.

Give exactly ONE CSS selector — never a comma-separated list of alternatives.

Respond with EXACTLY one line:
SEND_SELECTOR: <selector>

HTML fragment:
{html}"""
    return _llm_find_one_selector(llm, prompt, "send", page, _is_chat_send_selector)


def _detect_response_only(page: Any, url: str) -> Optional[str]:
    """STEP: single-purpose LLM fallback for the bot-response container,
    run last, against the final (post-launcher, if any) DOM."""
    llm = _get_llm_or_raise()
    html = _stripped_body_html(page, max_chars=8000)
    prompt = f"""You are a web automation expert. Below is the stripped HTML of a chatbot UI at {url}.

Find the CSS selector for the element that holds the BOT's reply messages (the latest one). Use :last-child or :last-of-type if it's a list. Do not pick a generic dashboard card, sidebar, or navbar.

For standard chatbots (ChatGPT, Claude, Perplexity, Copilot, Grok, etc.), the bot's response is typically inside a container class like `.markdown`, `.prose`, `.message[data-author='assistant']`, `.agent-turn`, or similar. You MUST target the text content of the BOT's message (not the user's message, and not the entire chat history container). If messages are in a list, target the last bot message specifically.

CRITICAL: Do NOT select .chat-input, input, textarea, composer, or send button. The selector MUST target a chat message bubble or bot reply element.

Give exactly ONE CSS selector — never a comma-separated list of alternatives.

Respond with EXACTLY one line:
RESPONSE_SELECTOR: <selector>

HTML:
{html}"""
    return _llm_find_one_selector(llm, prompt, "response", page, _is_chat_response_selector)


def _find_first_matching(page: Any, candidates: list[str]) -> Optional[str]:
    """Return the first selector in candidates that resolves to EXACTLY ONE
    VISIBLE element.

    Previously this used page.query_selector(), which returns the first DOM
    match with no multiplicity check — a selector could "pass" detection
    here and then fail later when the exact same string is handed to
    page.fill()/page.click(), which resolve selectors through Playwright's
    strict mode (raises if 2+ elements match). That mismatch — one loose
    resolution rule for detection, a stricter one for actual use — was a
    real source of "the field is right there in the screenshot but the fill
    failed" failures. Using locator().count() == 1 here means "detected as
    usable" and "actually usable by fill()/click()" are the same check, so
    a selector matching 2+ RAW DOM elements is never guessed at.

    A raw count of 2+ is NOT an automatic skip, though: real chat widgets
    very commonly render a hidden duplicate alongside the real field (a
    mobile-layout variant, a visually-hidden shadow/autosize textarea, a
    second unrelated element sharing a loose attribute selector).
    Discarding the selector outright the moment ANY duplicate exists — even
    when exactly one of those matches is actually visible — used to push
    detection to fall through to the slow, LLM-dependent fallback far more
    often than the DOM genuinely required. So when the raw count is 2+,
    this re-counts against `sel >> visible=true` specifically (the same
    idiom _ensure_visible_sel below already applies to a selector AFTER
    detection succeeds) and accepts the selector if exactly one VISIBLE
    match remains — "detected as usable" still means "the same check
    fill()/click() will see", just against the visible-only count rather
    than the raw one.
    """
    for sel in candidates:
        try:
            locator = page.locator(sel)
            count = locator.count()
            if count == 0:
                continue
            if count == 1:
                if locator.first.is_visible():
                    return sel
                continue
            # 2+ raw DOM matches — re-check against visible-only elements
            # before giving up on this candidate.
            visible_locator = page.locator(f"{sel} >> visible=true")
            if visible_locator.count() == 1:
                return sel
        except Exception:  # noqa: BLE001
            continue
    return None


def _detect_response_from_live_dom(page: Any) -> Optional[str]:
    """Inspect the live DOM for an existing bot message bubble (greeting or history).
    Returns a robust CSS selector targeting message bubbles, or None.
    """
    try:
        selector = page.evaluate("""() => {
            // Find greeting text or AI badge
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            let targetEl = null;
            while ((node = walker.nextNode())) {
                const val = (node.nodeValue || '').trim();
                if (
                    val.includes("fleet management assistant") ||
                    val.includes("Navigatto AI, your") ||
                    val.includes("fleet operations") ||
                    val.includes("fleet analytics") ||
                    (val === "AI" && node.parentElement?.offsetWidth > 0 && node.parentElement?.offsetWidth < 60)
                ) {
                    targetEl = node.parentElement;
                    break;
                }
            }
            if (!targetEl) return null;

            // If we found the AI avatar badge ("AI"), look for its sibling or adjacent message bubble
            if (targetEl.textContent.trim() === "AI" || targetEl.innerText?.trim() === "AI") {
                let sibling = targetEl.nextElementSibling;
                while (sibling) {
                    if (sibling.innerText && sibling.innerText.length > 5) {
                        targetEl = sibling;
                        break;
                    }
                    sibling = sibling.nextElementSibling;
                }
            }

            // Climb up to find a message container
            let curr = targetEl;
            for (let i = 0; i < 6; i++) {
                if (!curr || curr === document.body) break;
                const cls = (curr.className || '').toString();
                const classes = cls.split(' ').map(c => c.trim()).filter(Boolean);
                for (const c of classes) {
                    const lc = c.toLowerCase();
                    if (
                        (lc.includes('message') || lc.includes('bubble') || lc.includes('reply') || lc.includes('body')) &&
                        !lc.includes('input') && !lc.includes('send') && !lc.includes('avatar') && !lc.includes('wrapper')
                    ) {
                        const sel = `.${c}`;
                        try {
                            const count = document.querySelectorAll(sel).length;
                            if (count >= 1 && count <= 50) return sel;
                        } catch(e) {}
                    }
                }
                curr = curr.parentElement;
            }
            return null;
        }""")
        if selector and _is_chat_response_selector(selector):
            print(f"[browser debug] Live DOM detected bot response selector: '{selector}'")
            return selector
    except Exception as e:
        print(f"[browser debug] Live DOM response detection failed: {e}")
    return None


def _find_first_response_matching(page: Any, candidates: list[str]) -> Optional[str]:
    """Return the first candidate that matches at least one visible element.
    Chat message lists naturally contain multiple messages (greetings, history),
    so count >= 1 is valid (downstream code always uses .last to read the newest).
    """
    for sel in candidates:
        try:
            visible_locator = page.locator(f"{sel} >> visible=true")
            if visible_locator.count() >= 1:
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
1. The text input / textarea where the user types their message (often `textarea`, `.ProseMirror`, or `#prompt-textarea`).
2. The send / submit button (often a `<button>` with an arrow/paper-plane icon or `aria-label='Send message'`).
3. The element that contains the bot's response (for generic chatbots, often `.markdown`, `.prose`, `.message[data-author='assistant']`, or `.agent-turn`). Target the text content bubble specifically.

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
    on_event: Optional[Any] = None,
) -> dict[str, Optional[str]]:
    """Auto-detect launcher / input / send / response selectors for a chat
    UI — as a strict SEQUENCE, not one combined ask.

    Order, and why it's in this order:
      1. INPUT    — try to find it directly, against the page as it loaded.
      2. LAUNCHER — only looked for if step 1 found nothing. Some widgets
                    mount NOTHING (no input, no send, no response) until a
                    floating icon is clicked; if input isn't there yet,
                    that's the likely explanation, so we look for and
                    click whatever opens the panel, then retry INPUT
                    against the now-open DOM.
      3. SEND     — detected AFTER input is known, and scoped to input's
                    own container: the heuristic search only looks inside
                    that container, and if an LLM call is needed it's
                    only ever shown that small fragment, not the whole
                    page.
      4. RESPONSE — heuristic scan runs right after INPUT is known (it
                    doesn't depend on INPUT's value or on SEND at all).
                    If that heuristic misses, the LLM fallback is kicked
                    off on a BACKGROUND THREAD at that point and runs
                    CONCURRENTLY with step 3 (SEND) below, instead of
                    waiting for SEND to finish first — the two LLM calls
                    that used to always run strictly one after another now
                    overlap. The main thread joins that background job
                    right after SEND detection completes. See
                    _start_response_llm_job / _ResponseDetectJob for how
                    this stays safe with Playwright's sync API (the
                    background thread never touches `page`).

    This replaces the previous design, which asked ONE LLM call to find
    input/send/response/launcher all AT ONCE from the CLOSED-panel HTML.
    For a launcher-gated widget none of input/send/response exist in that
    HTML yet, so the model was guessing at elements that genuinely weren't
    there; for a non-gated widget it was still forced to answer a
    LAUNCHER question that didn't apply; and SEND in particular had no
    scoping at all, so a stray unrelated submit button anywhere on the
    page could win the role. Doing this as an ordered sequence — where
    each step only runs once the previous step's real DOM state is known,
    and SEND is scoped to INPUT's own container — removes all three
    problems at the source instead of patching around them afterwards.

    A hard wall-clock budget (AUTO_DETECT_BUDGET_SECONDS) covers the WHOLE
    sequence: each LLM call already has its own short fail-fast timeout
    (see _get_llm_or_raise), but a slow provider response on one step used
    to be indistinguishable, from the caller's side, from a genuine hang.
    Exceeding the budget raises a clean BrowserAutoDetectError naming which
    step it was in, instead of running long in a way nothing bounds.

    A previously-cached selector set for this session is re-validated
    against the LIVE page (see _cached_selectors_still_valid) before being
    trusted — a stale cache entry (DOM changed mid-session) is evicted and
    detection re-run, rather than being returned as-is and only failing
    much later, downstream, after burning the full wait_timeout_seconds.

    Args:
        page:       an open Playwright Page already at the chatbot URL.
        url:        the chatbot URL (used in error messages for context).
        config:     BrowserConfig instance (used as cache key via its
                    stable session_key, not id() — see that field's
                    docstring in aut/connector.py).
        timeout_ms: how long to wait for JS to render before scanning.
        on_event:   optional progress callback (progress.OnEvent). Fires
                    "selector_detection_step" at the start of each major
                    step so a live UI can show real activity ("checking
                    for a launcher button…") instead of going silent for
                    however long detection takes. None (the default) is a
                    no-op.

    Returns:
        dict with keys 'input', 'send', 'response' (and 'launcher' if one
        was needed) → CSS selector strings.
    """
    key = config.session_key
    cached = _SELECTOR_CACHE.get(key)
    if cached is not None:
        if _cached_selectors_still_valid(page, cached):
            return cached
        print(
            "[browser debug] Cached selectors for this session no longer "
            "resolve on the live page (likely a DOM change since an earlier "
            "round) — evicting cache and re-running detection."
        )
        del _SELECTOR_CACHE[key]

    deadline = time.perf_counter() + AUTO_DETECT_BUDGET_SECONDS

    def _check_budget(step_label: str) -> None:
        if time.perf_counter() > deadline:
            raise BrowserAutoDetectError(
                f"Auto-detection exceeded its {AUTO_DETECT_BUDGET_SECONDS:.0f}s "
                f"wall-clock budget while working on '{step_label}' for '{url}'. "
                f"This is usually a slow or rate-limited LLM provider response, "
                f"not a genuinely missing element. SOLUTION: provide "
                f"input_selector/send_selector/response_selector manually to "
                f"skip auto-detection entirely, or retry the run."
            )

    # Give dynamic / React / Vue UIs a moment to render before scanning.
    page.wait_for_timeout(timeout_ms)

    detected: dict[str, str] = {}

    # ---- Step 1 of 4: INPUT, as the page loaded ---------------------------
    emit_event(on_event, "selector_detection_step", {"step": "input", "message": "Looking for the chat input..."})
    input_sel = _find_first_matching(page, _INPUT_CANDIDATES)
    _check_budget("input detection")

    # ---- Step 2 of 4: LAUNCHER, only if input wasn't already there --------
    if not input_sel:
        print("[browser debug] No chat input visible yet — checking for a launcher button...")
        emit_event(on_event, "selector_detection_step", {"step": "launcher", "message": "Checking for a launcher button..."})
        launcher_sel = _detect_launcher_only(page, url)
        _check_budget("launcher detection")
        if launcher_sel:
            detected["launcher"] = launcher_sel
            try:
                page.locator(launcher_sel).first.click()
                page.wait_for_timeout(3000)  # let the panel actually mount
                print(f"[browser debug] Clicked launcher '{launcher_sel}', re-scanning for input...")
            except Exception as launcher_err:  # noqa: BLE001
                print(f"[browser debug] Launcher click failed: {launcher_err}")
            input_sel = _find_first_matching(page, _INPUT_CANDIDATES)
        else:
            print("[browser debug] No launcher found — trying INPUT via LLM against the page as-is...")
        if not input_sel:
            emit_event(on_event, "selector_detection_step", {"step": "input_llm", "message": "Asking the model to find the input..."})
            input_sel = _detect_input_only(page, url)
            _check_budget("input detection (LLM)")

    if not input_sel:
        raise BrowserAutoDetectError(
            f"Auto-detection could not identify the chat text input on '{url}' "
            f"(checked for a launcher button first, in case the widget was "
            f"gated behind one). "
            f"SOLUTION: Open the chatbot in Chrome → right-click the text input → "
            f"Inspect → copy the selector and provide it as input_selector."
        )
    detected["input"] = input_sel

    # ---- RESPONSE: kick off in the background as soon as INPUT is known ---
    # RESPONSE doesn't depend on INPUT's resolved VALUE or on SEND at all --
    # only on the DOM already being in its final, post-launcher-click state,
    # which is already true here (the launcher step above, if it ran,
    # already happened before input_sel was resolved). Try the cheap
    # heuristic scan first (page access, main thread, fast, no LLM); only if
    # THAT misses do we snapshot the HTML now and hand the LLM lookup off to
    # a background thread (_start_response_llm_job -- see its docstring for
    # why this is safe: the worker function never touches `page`) so it runs
    # CONCURRENTLY with SEND detection below instead of strictly after it.
    # This is what actually cuts the worst-case chain length: the two LLM
    # round-trips that used to always run one after another (SEND's
    # fallback, then RESPONSE's) now overlap instead of stacking.
    emit_event(on_event, "selector_detection_step", {"step": "response", "message": "Looking for the response container..."})
    response_sel = _detect_response_from_live_dom(page)
    if not response_sel:
        response_sel = _find_first_response_matching(page, _RESPONSE_CANDIDATES)
    response_job: Optional[_ResponseDetectJob] = None
    if not response_sel:
        response_html = _get_chat_panel_html(page, input_sel, max_chars=8000)
        response_llm = _get_llm_or_raise()
        response_job = _start_response_llm_job(response_llm, response_html, url)
        print("[browser debug] RESPONSE heuristic missed -- LLM lookup started in the background, continuing with SEND detection...")
    _check_budget("response detection (heuristic)")

    # ---- Step 3 of 4: SEND, scoped to input's own container ---------------
    # Runs concurrently with the RESPONSE background job above, if one was
    # started -- SEND is the one step in this window that genuinely needs
    # `page` access, so it stays on the main thread exactly as before.
    #
    # SEND is treated as OPTIONAL, not required: a lot of real chat UIs
    # submit on Enter with no dedicated button at all, or use an icon-only
    # button auto-detection can't reliably pin down (no aria-label/testid,
    # only mounts once text is typed, etc). A miss here used to raise
    # BrowserAutoDetectError and fail the whole round even though INPUT and
    # RESPONSE were both found fine. Now a miss is just recorded as
    # detected["send"] = None, and call_browser_aut() falls back to
    # pressing Enter in the focused input instead of clicking a button.
    emit_event(on_event, "selector_detection_step", {"step": "send", "message": "Looking for the send button..."})
    send_sel = _detect_send_only(page, url, input_sel)
    _check_budget("send detection")
    if not send_sel:
        print(
            f"[browser debug] No send button found near input '{input_sel}' on "
            f"'{url}' -- will fall back to pressing Enter in the input field "
            f"instead of clicking a button."
        )
    detected["send"] = send_sel

    # ---- Step 4 of 4: RESPONSE -- join the background job, if one was started
    if response_job is not None:
        remaining_budget = max(0.0, deadline - time.perf_counter())
        # A small grace period beyond the remaining wall-clock budget so a
        # job that's ALMOST done (well within its own
        # SELECTOR_DETECT_TIMEOUT_SECONDS) isn't cut off a fraction of a
        # second early only to have _check_budget raise anyway right after
        # with a less specific message than the job's own result would give.
        candidate = response_job.join(timeout=remaining_budget + 2.0)
        response_sel = _validate_llm_selector(candidate, "response", page, _is_chat_response_selector)
    _check_budget("response detection")
    if not response_sel:
        print(
            f"[browser debug] Could not identify response container on '{url}' — "
            f"activating page-transcript fallback mode. "
            f"The connector will type the task, press Enter, wait for the page to "
            f"settle, then scrape the full visible text and slice out everything "
            f"after the user's own question to recover the bot's reply."
        )
        response_sel = _RESPONSE_SEL_FALLBACK
    detected["response"] = response_sel

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
    pw: Any = None  # the sync_playwright() driver; MUST be stopped in close_session()

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
    try:
        browser = pw.chromium.launch(
            headless=config.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception:
        # A driver left running keeps an asyncio loop alive on this thread, which
        # turns every later sync_playwright().start() into a misleading
        # "Sync API inside the asyncio loop" error instead of the real one.
        _stop_playwright_quietly(pw)
        raise
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
    session = _BrowserSession(browser=browser, context=context, pw=pw)
    
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
    # Without this the Playwright driver (and its asyncio loop) outlives the
    # session, and the NEXT run on the same worker thread fails instantly with
    # "It looks like you are using Playwright Sync API inside the asyncio loop".
    _stop_playwright_quietly(session.pw)


def _stop_playwright_quietly(pw: Any) -> None:
    """Stop a sync_playwright() driver, never raising."""
    if pw is None:
        return
    try:
        pw.stop()
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
    "input[name='userName']",
    "input[name='loginId']",
    "input[name='userId']",
    "input[type='email']",
    "input[id*='username' i]",
    "input[id*='email' i]",
    "input[id*='user' i]",
    "input[id*='login' i]",
    "input[placeholder*='email' i]",
    "input[placeholder*='username' i]",
    "input[placeholder*='user' i]",
    "input[placeholder*='login' i]",
    "input[placeholder*='enter your email' i]",
    "input[autocomplete='username']",
    "input[autocomplete='email']",
    "[data-testid*='email' i]",
    "[data-testid*='username' i]",
    "[data-testid*='login' i]",
    # Catch-all: first visible text input inside a form
    "form input[type='text']:first-of-type",
]

_LOGIN_PASSWORD_CANDIDATES = [
    "input[type='password']",   # always the most reliable — standard HTML
    "input[name='password']",
    "input[name='passwd']",
    "input[name='pass']",
    "input[id*='password' i]",
    "input[placeholder*='password' i]",
    "input[placeholder*='enter your password' i]",
    "input[autocomplete='current-password']",
    "[data-testid*='password' i]",
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
    "button[id*='sign-in' i]",
    "button[class*='login' i]",
    "button[class*='signin' i]",
    "button[class*='sign-in' i]",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "button:has-text('Login')",
    "button:has-text('Continue')",
    "button:has-text('Submit')",
    "[data-testid*='login' i]",
    "[data-testid*='signin' i]",
    "[data-testid*='submit' i]",
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
            clean_html = _stripped_body_html(page, max_chars=15000)
            llm = _get_llm_or_raise()

            role_desc = {
                "username": "the text input for the username, email address, or login ID",
                "password": "the password input field",
                "submit": "the login / sign-in submit button",
            }
            missing_desc = "\n".join(
                f"- '{r}': {role_desc[r]}" for r in missing
            )
            prompt = f"""You are a web automation expert finding CSS selectors for Playwright.
Below is the stripped HTML of a login page at {login_url}.
We need CSS selectors for these login form elements:
{missing_desc}

Identify the BEST, MOST UNIQUE CSS selector for each.
Give exactly ONE CSS selector per role — never a comma-separated list of alternatives.

Respond in EXACTLY this format (one line per role, only for the ones listed above):
USERNAME_SELECTOR: <selector>
PASSWORD_SELECTOR: <selector>
SUBMIT_SELECTOR: <selector>

HTML:
{clean_html}"""

            _RETRYABLE = ("503", "529", "429", "rate limit", "overload", "unavailable", "high demand")
            answer = None
            for attempt in range(1, 4):
                try:
                    answer = llm.call(messages=[{"role": "user", "content": prompt}])
                    break
                except Exception as llm_err:  # noqa: BLE001
                    err_str = str(llm_err).lower()
                    if any(tok in err_str for tok in _RETRYABLE) and attempt < 3:
                        wait = 5.0 * attempt
                        print(f"[browser debug] Login LLM call failed (attempt {attempt}/3, retrying in {wait:.0f}s): {llm_err}")
                        time.sleep(wait)
                    else:
                        raise

            if answer is not None:
                if not isinstance(answer, str):
                    answer = str(answer)
                print(f"[browser debug] Login LLM RAW ANSWER:\n{answer[:1000]}")

                parsed = _parse_selector_lines(answer)
                for role in list(missing):
                    candidate = parsed.get(role)
                    if not candidate:
                        continue
                    if _has_top_level_comma(candidate):
                        print(f"[browser debug] Login LLM {role.upper()}_SELECTOR '{candidate}' rejected — comma-separated list")
                        continue
                    if not _selector_exists(page, candidate):
                        print(f"[browser debug] Login LLM {role.upper()}_SELECTOR '{candidate}' rejected — not found in live DOM")
                        continue
                    detected[role] = candidate

                missing = [k for k in ("username", "password", "submit") if k not in detected]
        except BrowserAutoDetectError as e:
            # _get_llm_or_raise surfaces a missing API key as
            # BrowserAutoDetectError — re-wrap as BrowserAuthError since
            # we're in the login context.
            raise BrowserAuthError(str(e)) from e
        except Exception as e:  # noqa: BLE001
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
    # Never mutate the page-transcript fallback sentinel — it must remain
    # an exact string match for _RESPONSE_SEL_FALLBACK throughout the call.
    if sel == _RESPONSE_SEL_FALLBACK:
        return sel
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
# Send/receive helpers used by call_browser_aut()
# ==========================================================================
_PLACEHOLDER_TEXTS = frozenset({
    "typing", "thinking", "generating", "loading", "processing", "writing",
    "analyzing", "analysing", "searching", "working", "please wait",
    "one moment", "just a moment",
})


def _norm_ws(text: Optional[str]) -> str:
    """Collapse every whitespace run (newlines included) to one space."""
    return " ".join((text or "").split())


def _is_placeholder_text(text: Optional[str]) -> bool:
    """True for empty text and for transient 'bot is busy' bubbles such as
    "Typing..." / "Bot is thinking…" — never a finished reply."""
    t = _norm_ws(text).lower().strip(" .…·•*_-")
    if not t:
        return True
        
    # Strip UI metadata (timestamps, AI labels) so we can cleanly check the core message
    cleaned = _clean_ui_metadata(t)
    
    if cleaned in _PLACEHOLDER_TEXTS:
        return True
        
    # Also ignore the specific custom loading spinner for the Navigatto AUT
    if "analyzing your fleet data" in cleaned:
        return True
        
    return cleaned.endswith(("is typing", "is thinking", "is writing", "is generating"))


def _is_echo_of_task(text: Optional[str], task: str) -> bool:
    """True if `text` is just the user's own message echoed back in a bubble
    (a response selector such as '.message' matches user AND bot bubbles).
    Exact match always counts; for longer tasks a short trailing suffix
    (timestamp / 'You') is tolerated too."""
    t, k = _norm_ws(text), _norm_ws(task)
    if not t or not k:
        return False
    if t == k:
        return True
    return len(k) >= 30 and k in t and len(t) - len(k) <= 25


def _strip_task(text: str, task: str) -> str:
    """If the text contains the user's task (e.g. it's a newly appended chunk
    in a generic chat container containing both the task and the response),
    strip the task out to return just the bot's response."""
    if not text or not task:
        return text
    
    # Try to find the task allowing for arbitrary whitespace formatting in the DOM
    norm_task = " ".join(task.split())
    if not norm_task:
        return text
        
    escaped_words = [re.escape(w) for w in norm_task.split()]
    pattern = r'\s*'.join(escaped_words)
    
    # Search for the first occurrence of the task. Because this is only called
    # on the newly appended text block, the first occurrence is almost certainly
    # the user's chat bubble, not the bot repeating it later.
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return text[match.end():].strip()
    return text


def _clean_ui_metadata(text: str) -> str:
    """Strip common chat UI artifacts (timestamps, AI/Bot tags) that confuse the generator."""
    if not text:
        return text
    # Remove timestamps like "2:34 PM", "14:34", "10:00 AM"
    cleaned = re.sub(r'\b\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?\b', '', text, flags=re.IGNORECASE)
    # Remove isolated speaker tags at the very start or end
    cleaned = re.sub(r'^(?:\s*(?:AI|Bot|System|U|You)\s*)+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(?:\s*(?:AI|Bot|System|U|You)\s*)+$', '', cleaned, flags=re.IGNORECASE)
    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" |-\n")
    return cleaned


def _extract_response_from_page_transcript(
    page: Any,
    task: str,
    wait_s: float = 20.0,
    pre_send_baseline: str = "",
) -> str:
    """Page-transcript fallback: used when no response-container selector could be found.

    Strategy:
      1. Use `pre_send_baseline` (captured BEFORE the task was typed/sent) as the
         reliable baseline. This is the entire conversation history up to this point.
      2. Wait up to `wait_s` seconds for the page text to grow BEYOND that baseline
         and then stop changing (bot has finished streaming).
      3. Return everything after the baseline, cleaned of UI metadata.

    This works for any chatbot where the conversation renders as visible page text,
    regardless of how much existing history is already on the page.
    """
    def _full_page_text() -> str:
        try:
            return page.evaluate("() => document.body.innerText") or ""
        except Exception:  # noqa: BLE001
            return ""

    baseline = pre_send_baseline or _full_page_text()
    baseline_len = len(baseline)

    # Poll until the page text grows beyond the baseline AND stabilises
    deadline = time.perf_counter() + wait_s
    stability_s = 1.5
    last_text = baseline
    last_change = time.perf_counter()

    while time.perf_counter() < deadline:
        page.wait_for_timeout(500)
        current = _full_page_text()
        if current != last_text:
            last_text = current
            last_change = time.perf_counter()
        elif (
            time.perf_counter() - last_change >= stability_s
            and len(current) > baseline_len
        ):
            # Page grew beyond baseline AND has been stable — bot is done
            break

    final_text = last_text

    # Primary strategy: slice everything after the pre-send baseline length
    if len(final_text) > baseline_len:
        response_raw = final_text[baseline_len:]
    else:
        # Fallback: try to find the task anchor and take everything after it
        task_snippet = task.strip()[:80]
        idx = final_text.find(task_snippet)
        if idx != -1:
            response_raw = final_text[idx + len(task_snippet):]
        else:
            response_raw = ""

    response_raw = response_raw.strip()
    response_raw = _clean_ui_metadata(response_raw)
    print(
        f"[browser debug] page-transcript fallback: extracted {len(response_raw)} chars "
        f"(baseline={baseline_len}, final={len(final_text)})."
    )
    return response_raw

def _read_last_response(page: Any, sel: str) -> tuple[int, str]:
    """(match_count, inner_text of the LAST match) for a response selector.
    Falls back to child frames when the main page has no match."""
    loc = page.locator(sel)
    count = loc.count()
    if count > 0:
        try:
            return count, loc.last.inner_text(timeout=2000) or ""
        except Exception:  # noqa: BLE001
            return count, ""
    el = _query_in_frames(page, sel)
    if el is not None:
        try:
            return 1, el.inner_text() or ""
        except Exception:  # noqa: BLE001
            return 1, ""
    return 0, ""


def _mark_last_response_node(page: Any, sel: str) -> None:
    """Remember the current last response node so _last_node_is_new() can tell
    a freshly-appended (or replaced) node from the old one. Only touches the
    DOM when a match exists — locator.evaluate() on a missing element would
    otherwise auto-wait ~30s."""
    try:
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.last.evaluate("el => { window._evalmind_last_node = el; }", timeout=2000)
        else:
            page.evaluate("() => { window._evalmind_last_node = null; }")
    except Exception:  # noqa: BLE001
        pass


def _last_node_is_new(page: Any, sel: str) -> bool:
    try:
        loc = page.locator(sel)
        if loc.count() == 0:
            return False
        return bool(loc.last.evaluate("el => el !== window._evalmind_last_node", timeout=1000))
    except Exception:  # noqa: BLE001
        return False


def _wait_for_response_text(
    page: Any,
    response_sel: str,
    task: str,
    before_count: int,
    before_text: str,
    *,
    require_new_node: bool,
    timeout_s: float,
    stability_s: float = 1.0,
    poll_ms: int = 250,
) -> Optional[str]:
    """Poll until a NEW, finished bot reply is on the page; return its text,
    or None on timeout.

    "New" means the number of matches grew, or (new_element) the last node is
    a different DOM node, or (text_change) the last node's text differs from
    before the send. Counting matches is what makes a reply that is textually
    identical to the previous one still detectable. Candidates that are just
    the user's own echoed message or a "Typing..." placeholder are ignored,
    and a candidate must stay unchanged for `stability_s` (a still-streaming
    reply keeps resetting the clock)."""
    # Safety guard: this function must never be called with the page-transcript
    # sentinel — that would make Playwright try to query "__page_transcript__"
    # as a real CSS selector, which always fails. The caller (call_browser_aut)
    # should have routed to _extract_response_from_page_transcript instead.
    if response_sel == _RESPONSE_SEL_FALLBACK:
        raise ValueError(
            "_wait_for_response_text called with _RESPONSE_SEL_FALLBACK sentinel — "
            "this is a bug; the caller should use _extract_response_from_page_transcript instead."
        )
    deadline = time.perf_counter() + timeout_s

    last_seen: Optional[str] = None
    stable_since: Optional[float] = None
    while time.perf_counter() < deadline:
        try:
            count, raw = _read_last_response(page, response_sel)
            text = (raw or "").strip()
            is_new = False
            if count > 0:
                is_new = count > before_count
                if not is_new and require_new_node:
                    is_new = _last_node_is_new(page, response_sel)
                if not is_new and not require_new_node:
                    is_new = text != before_text
                    
            if is_new:
                clean_text = text
                if count == before_count and before_text:
                    if clean_text.startswith(before_text):
                        clean_text = clean_text[len(before_text):].strip()
                    else:
                        idx = clean_text.rfind(task.strip()[:20])
                        if idx != -1:
                            clean_text = clean_text[idx:].strip()
                            
                    clean_text = _strip_task(clean_text, task)

                if not _is_placeholder_text(clean_text) and not _is_echo_of_task(clean_text, task):
                    now = time.perf_counter()
                    if clean_text != last_seen:
                        last_seen, stable_since = clean_text, now
                    elif stable_since is not None and (now - stable_since) >= stability_s:
                        return _clean_ui_metadata(clean_text)
                else:
                    last_seen, stable_since = None, None
            else:
                last_seen, stable_since = None, None
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(poll_ms)
    return None


def _type_task(page: Any, input_locator: Any, task: str) -> str:
    """Type `task` into the focused, already-cleared input and return the exact
    text typed (used by the send-verification check).

    A bare newline makes keyboard.type() press Enter, which SENDS the message,
    so a multi-line task (the Generator's higher levels use emails/logs) used
    to go out as several separate chat messages. Multi-line text is now typed
    line by line with Shift+Enter between lines (newline, don't send). A
    single-line <input> has no newline (Shift+Enter would still submit), so
    there the lines are joined with spaces instead."""
    normalized = task.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        page.keyboard.type(normalized, delay=30)
        return normalized
    try:
        tag = str(input_locator.evaluate("el => el.tagName", timeout=2000)).upper()
    except Exception:  # noqa: BLE001
        tag = ""
    if tag == "INPUT":
        typed = _norm_ws(normalized)
        page.keyboard.type(typed, delay=30)
        return typed
    lines = normalized.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=30)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")
    return normalized


def _visible_now(page: Any, sel: str) -> bool:
    """One-shot, no-wait: is there a visible match for `sel` (page or child frame)?"""
    try:
        if page.locator(_ensure_visible_sel(sel)).count() > 0:
            return True
        return _find_in_frames(page, _ensure_visible_sel(sel)) is not None
    except Exception:  # noqa: BLE001
        return False


def _chat_already_open(page: Any, config: "BrowserConfig") -> bool:  # type: ignore[name-defined]
    """True if the chat input is already visible, i.e. the launcher must NOT be
    clicked again. Clicking every round breaks widgets whose launcher hides
    once open (the wait for it times out) or toggles (the click closes the
    chat). Only an explicit or already-detected input selector can vouch for
    this; with neither, the launcher is clicked as before."""
    candidates = []
    if config.input_selector and config.input_selector.strip():
        candidates.append(config.input_selector.strip())
    cached_input = (_SELECTOR_CACHE.get(config.session_key) or {}).get("input")
    if cached_input:
        candidates.append(cached_input)
    return any(_visible_now(page, sel) for sel in candidates)


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
        # Smart generic fallback: wait for URL change (most login forms
        # redirect) or settle after 5s for SPAs that don't change URL.
        pre_submit_url = page.url
        page.wait_for_timeout(5000)
        if page.url != pre_submit_url:
            print(f"[browser debug] Login likely succeeded (URL changed to: {page.url!r})")
        else:
            print(
                "[browser debug] Login: no success signal configured and URL "
                "did not change after submit. Proceeding optimistically — "
                "if the login actually failed, selector detection on the "
                "chatbot page will surface the real error."
            )

    _debug_screenshot(page, "06_login_success")



# ==========================================================================
# Main connector function
# ==========================================================================
def call_browser_aut(task: str, config: "BrowserConfig", on_event: Optional[Any] = None) -> AUTResponse:  # type: ignore[name-defined]
    """Open (or reuse) a browser, interact with the chatbot UI, and return
    the response text.

    This is the implementation called by aut/connector.py's _call_browser().
    It is kept here (separate file) to keep playwright's import isolated —
    the rest of the system never touches playwright directly.

    on_event, if given, is forwarded to auto_detect_selectors() so a live
    UI can show real progress during selector auto-detection instead of
    going silent for however long it takes. None (the default) is a no-op
    — every existing caller (including both browser-fixture test scripts)
    is unaffected.
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
    message_sent = False  # flipped once the send is verified; see the except below

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

            # If we're already on the same host as the target chatbot, trust the
            # SPA's own routing and DO NOT force a hard reload. This covers:
            #  - Chatbots that create a new conversation URL (e.g. ChatGPT goes from
            #    chatgpt.com → chatgpt.com/c/<id>) — we must stay on that thread.
            #  - SPAs that routed us to a sub-path after login.
            # Only navigate away if we're on the login page (to avoid getting stuck
            # there if auth failed silently).
            if curr_p.netloc == tgt_p.netloc:
                on_login_page = log_p and curr_p.path == log_p.path
                if not on_login_page:
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
        if config.chat_launcher_selector and not _chat_already_open(page, config):
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
            detected = auto_detect_selectors(page, config.chatbot_url, config, on_event=on_event)
            input_sel = config.input_selector.strip() or detected["input"]
            send_sel = config.send_selector.strip() or detected.get("send")
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
        #
        # send_sel can legitimately be None/blank here -- no send button was
        # detected (or none was configured) and the send step below falls
        # back to pressing Enter in the input instead. Only wrap it with
        # the visible-element idiom when there's an actual selector string;
        # calling that on None/"" would crash on .lower().
        input_sel = _ensure_visible_sel(input_sel)
        send_sel = _ensure_visible_sel(send_sel) if (send_sel and send_sel.strip()) else None
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

        # Snapshot the response area BEFORE sending: how many matches exist, the
        # last one's text, and (new_element) which DOM node it is. "New reply" is
        # judged against this in _wait_for_response_text(). No-wait, frame-aware.
        # Skip when using the page-transcript fallback — there is no real selector.
        before_count, before_text = 0, ""
        if response_sel != _RESPONSE_SEL_FALLBACK:
            try:
                before_count, _snap_text = _read_last_response(page, response_sel)
                before_text = _snap_text.strip()
                _mark_last_response_node(page, response_sel)
            except Exception:  # noqa: BLE001
                pass

        # For the page-transcript fallback, capture a full-page-text baseline
        # BEFORE typing so we can reliably slice off only the new bot reply.
        page_transcript_baseline: str = ""
        if response_sel == _RESPONSE_SEL_FALLBACK:
            try:
                page_transcript_baseline = page.evaluate("() => document.body.innerText") or ""
            except Exception:  # noqa: BLE001
                page_transcript_baseline = ""

        # Click input and type the task.
        try:
            input_locator.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            typed_text = _type_task(page, input_locator, task)
        except Exception as e:  # noqa: BLE001
            _debug_screenshot(page, "09_type_failed")
            raise BrowserSelectorError(
                f"[{_classify_error(e)}] browser: could not type into input "
                f"'{input_sel}'{_selector_diagnostic(page, input_sel)}: {e}"
            ) from e

        # Click send button -- or, if no send selector was ever found/given,
        # or the one we have doesn't resolve/click, fall back to pressing
        # Enter in the already-focused input. Most real chat UIs submit on
        # Enter regardless of whether they also render a visible send
        # button, which covers exactly the cases auto-detection struggles
        # with (icon-only buttons with no useful aria-label/testid, a
        # button that only mounts once text is typed, etc).
        send_method = "enter"
        if send_sel:
            if _selector_exists(page, send_sel):
                try:
                    send_locator = _wait_for_selector_with_frames(page, send_sel, timeout_ms)
                    send_locator.click()
                    send_method = "click"
                except Exception as e:  # noqa: BLE001
                    print(
                        f"[browser debug] send selector '{send_sel}' was not "
                        f"clickable ({_classify_error(e)}) -- falling back to "
                        f"pressing Enter in the input '{input_sel}' instead: {e}"
                    )
            else:
                print(
                    f"[browser debug] send selector '{send_sel}' matches 0 "
                    f"elements on the page -- skipping the wait and pressing "
                    f"Enter in the input '{input_sel}' instead."
                )
        if send_method == "enter":
            try:
                input_locator.click()  # re-focus the input in case a failed send click moved focus
                page.keyboard.press("Enter")
            except Exception as e:  # noqa: BLE001
                raise BrowserSelectorError(
                    f"[{_classify_error(e)}] browser: "
                    + (
                        f"send selector '{send_sel}' was not usable and "
                        if send_sel
                        else "no send button was found or configured and "
                    )
                    + f"pressing Enter in input '{input_sel}' also failed"
                    f"{_selector_diagnostic(page, input_sel)}: {e}"
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
            if _norm_ws(typed_text) not in _norm_ws(_current_input_text()):
                cleared = True
                break
            page.wait_for_timeout(150)

        if not cleared:
            if send_method == "click":
                raise BrowserSelectorError(
                    f"browser: clicked send selector '{send_sel}' but input "
                    f"'{input_sel}' still contains the typed task 3s later. This "
                    f"usually means send_sel resolved to the wrong element (a "
                    f"heuristic like 'form button:last-of-type' can match a "
                    f"toolbar/regenerate button instead of Send) rather than a "
                    f"slow-to-respond chatbot. Provide an explicit send_selector "
                    f"if this one was auto-detected."
                )
            raise BrowserSelectorError(
                f"browser: pressed Enter in input '{input_sel}' but it still "
                f"contains the typed task 3s later. This chat UI likely "
                f"requires clicking an actual send button rather than "
                f"submitting on Enter -- provide an explicit send_selector "
                f"instead of relying on auto-detection/the Enter fallback."
            )

        # From here on the message is out: an error after this point must NOT be
        # retried by re-typing it (call_aut_with_retry checks message_sent).
        message_sent = True

        # ---- Wait for response -------------------------------------------
        response_text = ""

        if response_sel == _RESPONSE_SEL_FALLBACK:
            # Page-transcript fallback: no response container was detected.
            # Read the entire visible page text, wait for it to grow and
            # stabilise, then slice out everything after the user's question.
            print("[browser debug] Using page-transcript fallback to extract bot response.")
            response_text = _extract_response_from_page_transcript(
                page, task,
                wait_s=config.wait_timeout_seconds,
                pre_send_baseline=page_transcript_baseline,
            )

        elif config.wait_strategy in ("new_element", "text_change"):
            # Both strategies share one detector (see _wait_for_response_text):
            #   new_element -- a strictly NEW node (or one more match) must appear;
            #   text_change -- additionally accepts the last node's text changing.
            # Either way the candidate must not be the user's own echoed message
            # or a "Typing..." placeholder, and must stay unchanged briefly.
            require_new_node = config.wait_strategy == "new_element"
            found_text = _wait_for_response_text(
                page,
                response_sel,
                task,
                before_count,
                before_text,
                require_new_node=require_new_node,
                timeout_s=config.wait_timeout_seconds,
            )
            if found_text is None:
                _debug_screenshot(page, "10_response_wait_failed")
                if require_new_node:
                    raise BrowserTimeoutError(
                        f"browser: response selector '{response_sel}' did not appear within "
                        f"{config.wait_timeout_seconds}s (no new, finished bot reply was seen)"
                        f"{_selector_diagnostic(page, response_sel)}. Still on: {page.url!r}."
                    )
                raise BrowserTimeoutError(
                    f"browser: response text did not change within "
                    f"{config.wait_timeout_seconds}s (selector: '{response_sel}')"
                    f"{_selector_diagnostic(page, response_sel)}. Still on: {page.url!r}. "
                    f"The chatbot may still be generating or the selector is wrong."
                )
            response_text = found_text

        elif config.wait_strategy == "fixed_delay":
            page.wait_for_timeout(int(config.fixed_delay_seconds * 1000))
            try:
                el = page.query_selector(response_sel) or _query_in_frames(page, response_sel)
                response_text = el.inner_text() if el else ""
                if response_text:
                    # Same logic as _wait_for_response_text: if the whole container was read
                    current_count = page.locator(response_sel).count() if not _query_in_frames(page, response_sel) else 1
                    if current_count == before_count and before_text:
                        if response_text.startswith(before_text):
                            response_text = response_text[len(before_text):].strip()
                        else:
                            idx = response_text.rfind(task.strip()[:20])
                            if idx != -1:
                                response_text = response_text[idx:].strip()
                        response_text = _strip_task(response_text, task)
                    response_text = _clean_ui_metadata(response_text)
            except Exception as e:  # noqa: BLE001
                _debug_screenshot(page, "10_response_wait_failed")
                raise BrowserSelectorError(
                    f"[{_classify_error(e)}] browser: response selector '{response_sel}' "
                    f"not found after fixed delay{_selector_diagnostic(page, response_sel)}: {e}"
                ) from e

        latency_ms = (time.perf_counter() - start) * 1000

    except Exception as _err:  # noqa: BLE001
        # Tag every failure with whether the message had already been sent, so
        # call_aut_with_retry() never re-types (duplicates) an already-sent
        # question; wrap raw Playwright errors so callers only ever see
        # AUTConnectorError subclasses (and can retry them when it is safe).
        if not isinstance(_err, AUTConnectorError):
            _wrapped = BrowserTransientError(
                f"[{_classify_error(_err)}] browser: unexpected error while talking to "
                f"'{config.chatbot_url}': {_err}"
            )
            _wrapped.message_sent = message_sent  # type: ignore[attr-defined]
            if _classify_error(_err) == "TargetClosedError":
                close_session(config)  # dead browser: let the next attempt start a fresh one
            raise _wrapped from _err
        _err.message_sent = message_sent  # type: ignore[attr-defined]
        raise

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
