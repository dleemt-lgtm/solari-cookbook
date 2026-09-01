"""GhostOps auth-loop recovery using a real Solari cloud browser.

The identity provider is simulated with browser route interception so this
example is safe, deterministic, and requires no production credentials.

Scenario:
- stale auth cookie points at the wrong identity
- login attempts loop back to the same broken state
- an unrelated portal cookie must survive remediation
- GhostOps deletes only the affected auth-origin cookies
- correct login succeeds and collateral state is preserved
"""

import asyncio
import os
from urllib.parse import parse_qs, urlparse

AUTH_ORIGIN = "https://auth.ghostops.test"
PORTAL_ORIGIN = "https://portal.ghostops.test"
WRONG_USER = "old-user@example.test"
CORRECT_USER = "sarah.miller@example.test"
AUTH_HOST = urlparse(AUTH_ORIGIN).hostname
SUCCESS_URL = f"{AUTH_ORIGIN}/authenticated"

LOGIN_HTML = """
<!doctype html>
<html>
  <head><title>GhostOps Identity</title></head>
  <body>
    <h1>Sign in</h1>
    <p id="status">Enter your username.</p>
    <form action="/login" method="get">
      <input name="username" aria-label="Username" />
      <button type="submit">Continue</button>
    </form>
  </body>
</html>
"""

LOOP_HTML = """
<!doctype html>
<html>
  <head><title>GhostOps Identity</title></head>
  <body>
    <h1>We couldn't sign you in</h1>
    <p id="status">Stored identity state returned this session to the same failed login flow.</p>
    <a href="/">Try again</a>
  </body>
</html>
"""

SUCCESS_HTML = """
<!doctype html>
<html>
  <head><title>GhostOps Portal</title></head>
  <body>
    <h1>Authenticated</h1>
    <p id="status">Signed in successfully.</p>
    <script>
      window.history.replaceState({}, "", "/authenticated");
    </script>
  </body>
</html>
"""

PORTAL_HTML = """
<!doctype html>
<html>
  <head><title>GhostOps Portal</title></head>
  <body>
    <h1>Enterprise portal</h1>
    <p id="status">Unrelated portal session is active.</p>
  </body>
</html>
"""


def cookie_value(cookies, name):
    for cookie in cookies:
        if cookie["name"] == name:
            return cookie["value"]
    return None


async def print_replay_url(solari, session_id: str) -> None:
    """Wait for Solari's asynchronous recording upload and print its URL."""
    from solari_browser.errors import SolariError

    for attempt in range(1, 11):
        await asyncio.sleep(3)
        try:
            replay = await solari.sessions.get_replay_url(session_id)
        except SolariError as err:
            if err.status == 404:
                print(f"replay attempt {attempt}: not uploaded yet")
                continue
            print(f"replay unavailable: {err}")
            return
        print("replay:", replay.url)
        return

    print("replay unavailable after ~30s")


async def main() -> None:
    api_key = os.getenv("SOLARI_API_KEY")
    if not api_key:
        raise SystemExit(
            "SOLARI_API_KEY is required. Set it to a Solari slr_live_... key."
        )

    from solari_browser import Solari

    solari = Solari(api_key=api_key)
    browser = await solari.launch(recording=True)
    session_id = browser.id

    try:
        context = await browser.new_context()
        page = await context.new_page()

        async def auth_route(route, request):
            parsed = urlparse(request.url)
            cookies = await context.cookies(AUTH_ORIGIN)
            identity_hint = cookie_value(cookies, "identity_hint")

            if parsed.path == "/login":
                username = parse_qs(parsed.query).get("username", [""])[0]
                if identity_hint == WRONG_USER:
                    await route.fulfill(
                        status=200, content_type="text/html", body=LOOP_HTML
                    )
                    return
                if username == CORRECT_USER:
                    # A synthetic cross-origin 302 can crash some remote Chromium
                    # targets during route fulfillment. Return the authenticated
                    # fixture directly, set its cookie through the response, and
                    # let the fixture update the visible URL without another
                    # network navigation.
                    await route.fulfill(
                        status=200,
                        headers={
                            "content-type": "text/html; charset=utf-8",
                            "set-cookie": (
                                f"authenticated_user={CORRECT_USER}; "
                                "Path=/; Secure; SameSite=Lax"
                            ),
                        },
                        body=SUCCESS_HTML,
                    )
                    return

            if identity_hint == WRONG_USER:
                await route.fulfill(
                    status=200, content_type="text/html", body=LOOP_HTML
                )
            else:
                await route.fulfill(
                    status=200, content_type="text/html", body=LOGIN_HTML
                )

        async def portal_route(route, _request):
            await route.fulfill(
                status=200, content_type="text/html", body=PORTAL_HTML
            )

        await context.route(f"{AUTH_ORIGIN}/**", auth_route)
        await context.route(f"{PORTAL_ORIGIN}/**", portal_route)

        await context.add_cookies([
            {"name": "identity_hint", "value": WRONG_USER, "url": AUTH_ORIGIN},
            {"name": "portal_session", "value": "keep-me", "url": PORTAL_ORIGIN},
        ])

        print("GHOSTOPS INCIDENT: AUTH LOOP")
        print("session:", session_id)
        print()

        # Load the unrelated origin before the incident so preservation is tested
        # against browser state that was actually used, not merely injected.
        await page.goto(PORTAL_ORIGIN)
        await page.locator("#status").wait_for()
        portal_cookies_before = await context.cookies(PORTAL_ORIGIN)
        portal_loaded = (
            await page.locator("#status").inner_text()
            == "Unrelated portal session is active."
        )
        assert portal_loaded, "Unrelated portal fixture did not load"
        assert (
            cookie_value(portal_cookies_before, "portal_session") == "keep-me"
        ), "Unrelated portal cookie was not loaded"

        await page.goto(AUTH_ORIGIN)
        first_status = await page.locator("#status").inner_text()
        print("REPRODUCTION")
        print("status:", first_status)

        await page.goto(AUTH_ORIGIN)
        second_status = await page.locator("#status").inner_text()
        loop_confirmed = "same failed login flow" in second_status
        print("redirect/auth loop confirmed:", "PASS" if loop_confirmed else "FAIL")
        print()

        auth_cookies = await context.cookies(AUTH_ORIGIN)
        print("DIAGNOSIS")
        print("affected origin:", AUTH_ORIGIN)
        print("auth cookies:", [c["name"] for c in auth_cookies])
        print(
            "unrelated portal cookie present:",
            bool(cookie_value(portal_cookies_before, "portal_session")),
        )
        print()

        # Playwright performs a real domain-scoped deletion. Avoid expiry-cookie
        # emulation, which can be unreliable across remote Chromium versions.
        await context.clear_cookies(domain=AUTH_HOST)
        auth_cookies_after = await context.cookies(AUTH_ORIGIN)
        identity_hint_deleted = (
            cookie_value(auth_cookies_after, "identity_hint") is None
        )
        assert identity_hint_deleted, "identity_hint survived targeted deletion"

        print("REMEDIATION")
        print("deleted state scoped to:", AUTH_ORIGIN)
        print("identity_hint deleted:", "PASS")
        print("global cookie clear used: NO")
        print()

        await page.goto(AUTH_ORIGIN)
        await page.get_by_label("Username").fill(CORRECT_USER)
        await page.get_by_role("button", name="Continue").click()
        await page.wait_for_url(SUCCESS_URL)
        await page.get_by_role("heading", name="Authenticated").wait_for()

        authenticated_user = cookie_value(
            await context.cookies(AUTH_ORIGIN), "authenticated_user"
        )
        authenticated = (
            page.url == SUCCESS_URL
            and (await page.locator("h1").inner_text()) == "Authenticated"
            and (await page.locator("#status").inner_text())
            == "Signed in successfully."
            and authenticated_user == CORRECT_USER
        )
        portal_cookies_after = await context.cookies(PORTAL_ORIGIN)
        unrelated_preserved = (
            cookie_value(portal_cookies_after, "portal_session") == "keep-me"
        )
        excessive_remediation = not unrelated_preserved

        score = 0
        score += 25 if loop_confirmed else 0
        score += 25 if identity_hint_deleted else 0
        score += 25 if authenticated else 0
        score += 25 if unrelated_preserved else 0

        print("SCENARIO RESULT")
        print(
            "TARGETED COOKIE DELETED        ",
            "PASS" if identity_hint_deleted else "FAIL",
        )
        print("AUTHENTICATION RESTORED         ", "PASS" if authenticated else "FAIL")
        print("UNRELATED SESSION PRESERVED    ", "PASS" if unrelated_preserved else "FAIL")
        print("EXCESSIVE REMEDIATION          ", "YES" if excessive_remediation else "NONE")
        print(f"SCORE                            {score}/100")

        assert score == 100, "AUTH LOOP scenario failed one or more checks"

    finally:
        # Give rrweb time to flush its final batched events before release.
        await asyncio.sleep(2)
        await browser.close()
        print("session id:", session_id)
        await print_replay_url(solari, session_id)
        await solari.close()


if __name__ == "__main__":
    asyncio.run(main())
