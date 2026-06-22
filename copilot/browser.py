"""Browser-backed Copilot driver.

A Playwright fallback for the pure-HTTP :class:`copilot.client.Copilot`: it runs
the *exact same protocol* inside a real browser that already holds Cloudflare
clearance and (optionally) a signed-in Microsoft session. Useful if Microsoft
ever escalates the challenge to a Cloudflare Turnstile CAPTCHA, which needs a
browser-solved token.

``BrowserCopilot`` launches a **persistent** Playwright Chromium profile so that
Cloudflare clearance and any sign-in survive restarts. The chat protocol
(``POST /c/api/conversations`` then a ``wss://.../c/api/chat`` WebSocket speaking
``send`` -> ``appendText``* -> ``done``) is executed *in the page* via
``page.evaluate`` so the browser's own ``fetch``/``WebSocket`` carry the cookies,
Cloudflare token, and auth headers.

It exposes the same ``create_completion(prompt, stream=...)`` generator API as
:class:`copilot.client.Copilot`, so it is a drop-in replacement.

PROTOCOL ASSUMPTIONS (verify at runtime against a live session):
  * Conversation create:  POST /c/api/conversations  -> {"id": "..."}
  * Chat socket:          wss://copilot.microsoft.com/c/api/chat?api-version=2
                          (with &accessToken=<token> when signed in)
  * Send frame:           {"event":"send","conversationId":...,
                           "content":[{"type":"text","text":...}],"mode":"chat"}
  * Stream frames:        {"event":"appendText","text":...}, then {"event":"done"}
These mirror the captured protocol in ``client.py``. If Microsoft changes them,
adjust the JS templates below.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Generator, Optional

from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PwTimeout

from .auth import DEFAULT_AUTH_FILE, DEFAULT_PROFILE_DIR

COPILOT_URL = "https://copilot.microsoft.com/"
M365_URL = "https://m365.cloud.microsoft/chat"

# --- in-page JavaScript -----------------------------------------------------

# Create a conversation. Runs in the page so cookies/Cloudflare apply.
_CREATE_CONVERSATION_JS = """
async () => {
  const res = await fetch('/c/api/conversations', {
    method: 'POST',
    credentials: 'include',
    headers: {'content-type': 'application/json'},
  });
  const text = await res.text();
  if (!res.ok) return {ok: false, status: res.status, text: text};
  let data = {};
  try { data = JSON.parse(text); } catch (e) {}
  return {ok: true, id: data.id || data.conversationId || null, raw: text};
}
"""

# Discover the Copilot chat MSAL access token from localStorage. The cache holds
# several tokens for different scopes; the chat WebSocket only accepts the one
# scoped 'ChatAI.ReadWrite' — a wrong-audience token (e.g. the Graph
# User.Read/Files.Read token) makes the WS upgrade 401. We therefore PREFER the
# ChatAI token and only fall back to the first token found if none matches.
# Returns null for anonymous sessions (anonymous chat may still work via cookies).
_FIND_TOKEN_JS = """
() => {
  try {
    let fallback = null;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k);
      if (v && v.indexOf('"credentialType":"AccessToken"') !== -1) {
        try {
          const o = JSON.parse(v);
          if (o && o.secret) {
            // Match the chat scope (e.g. '<resource>/ChatAI.ReadWrite'); take the
            // first non-matching token only as a last-resort fallback.
            if (o.target && o.target.indexOf('ChatAI') !== -1) return o.secret;
            if (!fallback) fallback = o.secret;
          }
        } catch (e) {}
      }
    }
    return fallback;
  } catch (e) {}
  return null;
}
"""

# Open the chat WebSocket and wire handlers that push into a window-scoped
# buffer. Returns immediately; messages accumulate while Python polls.
_START_STREAM_JS = """
([conversationId, accessToken, prompt]) => {
  const state = {queue: [], done: false, error: null, started: false};
  window.__copilot = state;
  let url = 'wss://copilot.microsoft.com/c/api/chat?api-version=2';
  if (accessToken) url += '&accessToken=' + encodeURIComponent(accessToken);
  let ws;
  try { ws = new WebSocket(url); } catch (e) { state.error = 'ws-init: ' + e; state.done = true; return false; }
  window.__copilotWs = ws;
  ws.onopen = () => {
    ws.send(JSON.stringify({
      event: 'send',
      conversationId: conversationId,
      content: [{type: 'text', text: prompt}],
      mode: 'chat'
    }));
  };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    const e = msg.event;
    if (e === 'appendText') { state.started = true; if (msg.text) state.queue.push(msg.text); }
    else if (e === 'done') { state.done = true; try { ws.close(); } catch (x) {} }
    else if (e === 'error') { state.error = JSON.stringify(msg); state.done = true; try { ws.close(); } catch (x) {} }
  };
  ws.onerror = () => { state.error = state.error || 'websocket error'; state.done = true; };
  ws.onclose = () => { state.done = true; };
  return true;
}
"""

# Drain the buffer and report status in one round-trip.
_POLL_JS = """
() => {
  const s = window.__copilot || {queue: [], done: true, error: 'not started', started: false};
  const q = s.queue;
  s.queue = [];
  return {q: q, done: s.done, error: s.error, started: s.started};
}
"""


class BrowserCopilot:
    """Drives Microsoft Copilot through a real Playwright browser.

    Parameters
    ----------
    profile_dir:
        Directory for the persistent Chromium profile (cookies, Cloudflare
        clearance, sign-in). Reused across runs.
    headless:
        Run without a visible window. Use ``False`` (or :meth:`login`) for the
        first interactive sign-in, then ``True`` afterwards.
    """

    label = "Microsoft Copilot (browser)"
    default_model = "Copilot"

    def __init__(
        self,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        headless: bool = True,
        nav_timeout: int = 60,
        proxy: Optional[str] = None,
        mode: str = "consumer",
    ):
        self.profile_dir = str(Path(profile_dir).resolve())
        self.headless = headless
        self.nav_timeout = nav_timeout
        self.proxy = proxy
        self._mode = mode

        self._pw = None
        self._context = None
        self._page = None

    # -- lifecycle ----------------------------------------------------------

    def start(self, headless: Optional[bool] = None) -> "BrowserCopilot":
        """Launch the persistent browser context and open Copilot."""
        if self._context is not None:
            return self
        if headless is not None:
            self.headless = headless
        try:
            self._pw = sync_playwright().start()
            launch_kwargs = dict(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            if self.proxy:
                launch_kwargs["proxy"] = self._parse_proxy(self.proxy)
            
            launch_kwargs.setdefault("args", [])
            launch_kwargs["args"] = list(launch_kwargs["args"]) + [
                "--ignore-certificate-errors",
                "--test-type",
            ]
            launch_kwargs["ignore_https_errors"] = True

            self._context = self._pw.chromium.launch_persistent_context(
                self.profile_dir,
                **launch_kwargs,
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(self.nav_timeout * 1000)
            target = M365_URL if self._mode == "m365" else COPILOT_URL
            self._page.goto(target, wait_until="domcontentloaded")
            if self._mode == "m365":
                self._page.wait_for_load_state("load", timeout=self.nav_timeout * 1000)
            else:
                self._page.wait_for_load_state("networkidle", timeout=self.nav_timeout * 1000)
        except PlaywrightError as exc:
            self.close()
            raise ConnectionError(f"Failed to start browser: {exc}") from exc
        return self

    @staticmethod
    def _parse_proxy(proxy: str) -> dict:
        """Turn a ``scheme://user:pass@host:port`` string into Playwright form."""
        from urllib.parse import urlparse

        u = urlparse(proxy)
        server = f"{u.scheme}://{u.hostname}:{u.port}" if u.port else f"{u.scheme}://{u.hostname}"
        cfg = {"server": server}
        if u.username:
            cfg["username"] = u.username
        if u.password:
            cfg["password"] = u.password
        return cfg

    def region_blocked(self) -> bool:
        """True if Copilot is showing the 'Not available in your region' notice."""
        if self._mode == "m365":
            return False
        if self._page is None:
            return False
        try:
            text = self._page.evaluate("() => document.body ? document.body.innerText : ''")
        except PlaywrightError:
            return False
        return "available in your region" in (text or "").lower()

    def close(self) -> None:
        for attr, closer in (("_context", lambda c: c.close()), ("_pw", lambda p: p.stop())):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    closer(obj)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._page = None

    def __enter__(self) -> "BrowserCopilot":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- auth ---------------------------------------------------------------

    def login(self, path: str = DEFAULT_AUTH_FILE) -> dict:
        """Open a visible window for interactive Microsoft sign-in.

        Blocks until you press Enter in the console. The session is persisted in
        ``profile_dir`` (and snapshotted to ``path``), so subsequent headless
        runs reuse it. Returns the captured auth dict.
        """
        self.close()
        self.start(headless=False)
        url_label = "m365.cloud.microsoft/chat" if self._mode == "m365" else "copilot.microsoft.com"
        print(
            f"\nA browser window is open at {url_label}.\n"
            "Sign in (or just solve any Cloudflare check for anonymous use),\n"
            "then return here and press Enter to save the session..."
        )
        try:
            input()
        except EOFError:
            pass
        # Snapshot fresh auth so the headless curl_cffi path works immediately.
        auth: dict = {}
        try:
            auth = self.export_auth(path=path, stamp=time.time())
            print(f"Auth snapshot saved to {path}")
        except Exception as exc:
            print(f"(could not snapshot auth: {exc})")
        self.close()
        print(f"Session saved to {self.profile_dir}")
        return auth

    def access_token(self) -> Optional[str]:
        """Return the page's MSAL access token, or ``None`` if anonymous."""
        self._ensure_started()
        try:
            return self._page.evaluate(_FIND_TOKEN_JS)
        except PlaywrightError:
            return None

    def cookies(self) -> Dict[str, str]:
        """Return the signed-in Microsoft cookies as a name->value dict."""
        self._ensure_started()
        try:
            raw = self._context.cookies()
        except PlaywrightError:
            return {}
        return {c["name"]: c["value"] for c in raw
                if any(d in c.get("domain", "") for d in ("microsoft.com", "microsoftonline.com", "live.com", "msn.com"))}

    def export_auth(self, path: str = DEFAULT_AUTH_FILE, stamp: Optional[float] = None) -> dict:
        """Snapshot the signed-in cookies + access token to ``path`` as JSON.

        ``stamp`` is the epoch seconds to record as ``saved_at`` (pass
        ``time.time()`` from the caller). Returns the auth dict.
        """
        auth = {
            "cookies": self.cookies(),
            "access_token": self.access_token(),
            "saved_at": stamp if stamp is not None else 0,
        }
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(auth, indent=2), encoding="utf-8")
        return auth

    # -- chat ---------------------------------------------------------------

    def create_completion(
        self,
        prompt: str,
        stream: bool = False,
        timeout: int = 900,
        **kwargs,
    ) -> Generator[str, None, None]:
        """Stream a Copilot reply to ``prompt``. Mirrors ``Copilot.create_completion``.

        Yields text chunks as they arrive. ``stream`` is accepted for API
        compatibility; chunks are always produced incrementally.
        """
        self._ensure_started()

        conversation_id = kwargs.pop("conversation_id", None)

        if self._mode == "m365":
            yield from self._m365_chat(prompt, timeout)
            return

        if self.region_blocked():
            raise RuntimeError(
                "Microsoft Copilot is not available in your region. "
                "Route the browser through a proxy/VPN in a supported region, e.g.:\n"
                "    BrowserCopilot(proxy='http://user:pass@host:port')\n"
                "or 'socks5://host:port'. See README for details."
            )

        conv = self._page.evaluate(_CREATE_CONVERSATION_JS)
        if not conv.get("ok"):
            status = conv.get("status")
            body = (conv.get("text") or "")[:500]
            if status in (401, 403):
                raise RuntimeError(
                    f"Conversation create returned HTTP {status}. "
                    f"Run login() / `python -m copilot login` to sign in. Body: {body}"
                )
            raise RuntimeError(f"Conversation create failed (HTTP {status}): {body}")

        conversation_id = conv.get("id")
        if not conversation_id:
            raise RuntimeError(f"No conversation id in response: {conv.get('raw')!r}")

        token = self._page.evaluate(_FIND_TOKEN_JS)

        started_ok = self._page.evaluate(_START_STREAM_JS, [conversation_id, token, prompt])
        if started_ok is False:
            state = self._page.evaluate(_POLL_JS)
            raise ConnectionError(f"WebSocket failed to start: {state.get('error')}")

        yield from self._pump(timeout)

    # -- internals ----------------------------------------------------------

    def _pump(self, timeout: int) -> Generator[str, None, None]:
        deadline = time.time() + timeout
        any_text = False
        while True:
            state = self._page.evaluate(_POLL_JS)
            for chunk in state.get("q") or []:
                if chunk:
                    any_text = True
                    yield chunk
            if state.get("error"):
                raise RuntimeError(f"Copilot error: {state['error']}")
            if state.get("done") and not state.get("q"):
                break
            if time.time() > deadline:
                raise TimeoutError(f"No 'done' within {timeout}s")
            time.sleep(0.08)

        if not any_text and not state.get("started"):
            raise RuntimeError("Invalid response: stream produced no text")

    # -- M365 DOM chat -----------------------------------------------------

    def _m365_chat(self, prompt: str, timeout: int) -> Generator[str, None, None]:
        """Send a prompt via M365 Copilot's web UI (DOM-based)."""
        page = self._page

        # Ensure we are on the M365 chat page
        current = page.url
        if not current.startswith(M365_URL):
            page.goto(M365_URL, wait_until="domcontentloaded")

        # Click "New chat" to start fresh
        try:
            new_btn = page.locator('button:has-text("New chat")')
            if new_btn.is_visible(timeout=3000):
                new_btn.click()
                time.sleep(1)
        except (PwTimeout, Exception):
            pass

        # Type the prompt into the contenteditable input
        try:
            input_el = page.locator("#m365-chat-editor-target-element")
            input_el.wait_for(state="visible", timeout=10000)
        except PwTimeout as exc:
            raise RuntimeError(f"M365 chat input not found: {exc}")

        input_el.click()
        page.keyboard.type(prompt, delay=0.02)
        time.sleep(0.3)

        # Click Send
        try:
            send_btn = page.locator('button[aria-label="Send"]')
            send_btn.wait_for(state="visible", timeout=5000)
        except PwTimeout as exc:
            raise RuntimeError(f"M365 send button not found: {exc}")
        send_btn.click()

        # Wait longer for Copilot to produce a response - it often takes 10+ seconds
        time.sleep(2)

        # Poll for the complete response with more patience
        deadline = time.time() + max(timeout, 60)  # Ensure minimum 60s for Copilot
        last_text = ""
        stable_count = 0
        max_stable_for_completion = 6  # Must be unchanged for 6+ polls (~3 seconds) to consider done
        
        # Filter out placeholder/intermediate states
        LOADING_STATES = {
            "Gathering", "Generating", "Checking that", "Making it happen", 
            "Putting it together", "Sorting it out", "Searching", "Taking a look",
            "Thinking", "Looking", "Fetching", "Analyzing", "Compiling",
            "Organizing", "Calculating", "Processing", "Building", "Reviewing",
            "Working on", "Researching", "Checking", "Collecting", "Planning",
            "Investigating", "Summarizing", "Preparing", "Setting up",
            "Getting things ready", "Coming up with", "Putting together",
            "Let me", "I'll", "I will", "One moment", "Just a moment",
        }
        
        poll_attempt = 0
        while time.time() < deadline:
            try:
                # Try multiple selectors since M365 UI might vary
                containers = page.locator('[id^="chatMessageContainer"]')
                count = containers.count()
                
                text = None
                if count > 0:
                    # Try to get the last message container
                    last = containers.nth(count - 1)
                    try:
                        raw = last.inner_text(timeout=2000)
                        if "Copilot said:" in raw:
                            text = raw.split("Copilot said:")[1].strip()
                    except Exception:
                        pass
                
                # Fallback: try to find any div with substantial text
                if not text:
                    try:
                        all_divs = page.locator('div[role="region"]')
                        if all_divs.count() > 0:
                            for i in range(all_divs.count() - 1, max(-1, all_divs.count() - 5), -1):
                                potential = all_divs.nth(i).inner_text(timeout=1000)
                                if potential and len(potential) > 10:
                                    text = potential
                                    break
                    except Exception:
                        pass
                
                if text:
                    # Check if this is real content or just a loading message
                    text_lower = text.lower()
                    is_loading = any(state.lower() in text_lower for state in LOADING_STATES)
                    
                    if not is_loading and len(text) > 10:
                        # We have real content!
                        if text == last_text:
                            stable_count += 1
                            if stable_count >= max_stable_for_completion:
                                yield text
                                return
                        else:
                            stable_count = 0
                            last_text = text
                    elif is_loading:
                        # Reset counters when we see loading state
                        stable_count = 0
                        last_text = ""
            except Exception:
                pass
            
            poll_attempt += 1
            time.sleep(0.5)

        # If we have accumulated substantial text, return it
        if last_text and len(last_text) > 10:
            yield last_text
            return
            
        raise TimeoutError(f"M365 Copilot did not respond adequately within {timeout}s")

    def _ensure_started(self) -> None:
        if self._context is None or self._page is None:
            self.start()
