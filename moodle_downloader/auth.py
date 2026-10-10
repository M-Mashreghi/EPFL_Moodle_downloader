"""Getting a Moodle web-service token for an EPFL (SSO) account.

EPFL accounts log in through the EPFL single sign-on page, so Moodle's plain
username/password token endpoint usually refuses them. Instead we do what the
official Moodle mobile app does: open Moodle's "launch app" page in a real
browser (Edge, already on every Windows PC), sign in with the saved
credentials, and catch the redirect to our own URL scheme, which carries the
token.
"""
import base64
import hashlib
import os
import random
import re
import time

import requests

from .config import SITE

SCHEME = "epflmoodledl"
TOKEN_RE = re.compile(re.escape(SCHEME) + r"://token=([A-Za-z0-9+/=_%-]+)")


class LoginError(Exception):
    pass


def token_via_password(username: str, password: str):
    """Moodle's direct token endpoint. Works only for non-SSO accounts."""
    try:
        r = requests.post(
            f"{SITE}/login/token.php",
            data={"username": username, "password": password, "service": "moodle_mobile_app"},
            timeout=30,
        )
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    return data.get("token")


def decode_launch_token(raw: str, passport: str) -> str:
    """The launch redirect carries base64("signature:::token[:::privatetoken]")."""
    raw = requests.utils.unquote(raw)
    raw += "=" * (-len(raw) % 4)
    decoded = base64.b64decode(raw).decode("utf-8", "replace")
    parts = decoded.split(":::")
    if len(parts) < 2:
        raise LoginError("Moodle returned an unexpected token format.")
    signature, token = parts[0], parts[1]
    expected = {hashlib.md5((SITE + passport).encode()).hexdigest(),
                hashlib.md5((SITE + "/" + passport).encode()).hexdigest()}
    if signature not in expected:
        # Not fatal: some sites sign with a slightly different wwwroot. The
        # token is still checked against the API right after this.
        pass
    return token


def _visible(page, selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        return loc.count() > 0 and loc.is_visible()
    except Exception:
        return False


def _fill_if_empty(page, selector: str, value: str) -> bool:
    loc = page.locator(selector).first
    try:
        if loc.input_value() != value:
            loc.fill(value)
            return True
    except Exception:
        pass
    return False


def _click_first(page, selectors) -> bool:
    for sel in selectors:
        if _visible(page, sel):
            try:
                page.locator(sel).first.click(timeout=3000)
                return True
            except Exception:
                continue
    return False


SUBMIT = ["#idSIButton9", "#loginbutton", "button[type=submit]", "input[type=submit]", "#kc-login"]


def _login_step(page, username: str, password: str, state: dict) -> None:
    """Fill whatever login form is on screen right now (EPFL Tequila,
    Microsoft Entra ID, or Moodle's own page). Safe to call repeatedly."""
    url = page.url

    # Moodle's own login page: follow the EPFL single sign-on button.
    if url.startswith(SITE) and "/login/" in url:
        if _click_first(page, ["a[href*='auth/tequila']", "a[href*='auth/oauth2']",
                               "a[href*='auth/saml']", "a[href*='auth/shibboleth']",
                               "a.login-identityprovider-btn"]):
            return

    # Microsoft "Stay signed in?" page.
    if _visible(page, "#KmsiCheckboxField") or _visible(page, "#KmsiDescription"):
        _click_first(page, ["#idSIButton9"])
        return

    user_sel = next((s for s in ["input[name=loginfmt]", "input#username", "input[name=username]",
                                 "input[type=email]"] if _visible(page, s)), None)
    pass_sel = next((s for s in ["input[name=passwd]", "input#password", "input[name=password]",
                                 "input[type=password]"] if _visible(page, s)), None)

    if user_sel and pass_sel:
        _fill_if_empty(page, user_sel, username)
        _fill_if_empty(page, pass_sel, password)
        key = ("both", url)
        if state.get(key, 0) < 2:
            state[key] = state.get(key, 0) + 1
            _click_first(page, SUBMIT)
        return
    if user_sel:
        _fill_if_empty(page, user_sel, username)
        key = ("user", url)
        if state.get(key, 0) < 2:
            state[key] = state.get(key, 0) + 1
            _click_first(page, SUBMIT)
        return
    if pass_sel:
        _fill_if_empty(page, pass_sel, password)
        key = ("pass", url)
        if state.get(key, 0) < 2:
            state[key] = state.get(key, 0) + 1
            _click_first(page, SUBMIT)
        return

    # Moodle may ask to confirm opening the app; the link itself has the token.
    _click_first(page, [f"a[href^='{SCHEME}://']", "a[href*='launch.php'][href*='confirmed']"])


def _launch_browser(p, headless: bool):
    errors = []
    custom = os.environ.get("MOODLE_DL_BROWSER")
    if custom:
        return p.chromium.launch(executable_path=custom, headless=headless)
    for channel in ("msedge", "chrome", None):
        try:
            if channel:
                return p.chromium.launch(channel=channel, headless=headless)
            return p.chromium.launch(headless=headless)
        except Exception as e:  # browser not installed
            errors.append(f"{channel or 'chromium'}: {e}")
    raise LoginError("Could not start a browser (Edge or Chrome).\n" + "\n".join(errors))


def token_via_browser(username: str, password: str, headless: bool = True,
                      timeout: int = 120, log=print) -> str:
    from playwright.sync_api import sync_playwright

    passport = str(random.randint(10**8, 10**9))
    launch_url = (f"{SITE}/admin/tool/mobile/launch.php?service=moodle_mobile_app"
                  f"&passport={passport}&urlscheme={SCHEME}")
    found = {}

    def check(text):
        if text and "raw" not in found:
            m = TOKEN_RE.search(text)
            if m:
                found["raw"] = m.group(1)

    with sync_playwright() as p:
        browser = _launch_browser(p, headless)
        try:
            ctx = browser.new_context()
            page = ctx.new_page()
            page.on("request", lambda r: check(r.url))
            page.on("response", lambda r: check(r.headers.get("location")))
            page.on("framenavigated", lambda f: check(f.url))
            try:
                page.goto(launch_url, timeout=60000)
            except Exception:
                pass  # navigating to the custom scheme aborts the page load

            state = {}
            deadline = time.time() + timeout
            while "raw" not in found and time.time() < deadline:
                try:
                    _login_step(page, username, password, state)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(700)
                    check(page.content())
                except Exception:
                    time.sleep(0.7)
                if not headless and page.is_closed():
                    break
        finally:
            browser.close()

    if "raw" not in found:
        raise LoginError("Login did not finish. Check your username and password, "
                         "or run with --show-browser to see what happens.")
    return decode_launch_token(found["raw"], passport)
