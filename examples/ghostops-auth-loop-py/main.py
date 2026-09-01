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

from solari_browser import Solari

AUTH_ORIGIN = "https://auth.ghostops.test"
PORTAL_ORIGIN = "https://portal.ghostops.test"
WRONG_USER = "old-user@example.test"
CORRECT_USER = "sarah.miller@example.test"

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
  </body>
</html>
"""


def cookie_value(cookies, name):
    for cookie in cookies:
        if cookie["name"] == name:
            return cookie["value"]
    return None


async def main() -> None:
    solari = Solari(api_key=os.environ["SOLARI_API_KEY"])
    browser = await solari.launch()

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
                    await route.fulfill(status=200, content_type="text/html", body=LOOP_HTML)
                    return
                if username == CORRECT_USER:
                    await context.add_cookies([
                        {
                            "name": "authenticated_user",
                            "value": CORRECT_USER,
                            "url": AUTH_ORIGIN,
                        }
                    ])
                    # Keep the deterministic simulator on the intercepted request
                    # instead of issuing a redirect to a synthetic hostname. This
                    # avoids DNS being consulted by the remote browser while still
                    # exercising the real Solari browser and cookie state.
                    await route.fulfill(status=200, content_type="text/html", body=SUCCESS_HTML)
                    return

            if identity_hint == WRONG_USER:
                await route.fulfill(status=200, content_type="text/html", body=LOOP_HTML)
            else:
                await route.fulfill(status=200, content_type="text/html", body=LOGIN_HTML)

        await context.route(f"{AUTH_ORIGIN}/**", auth_route)

        await context.add_cookies([
            {"name": "identity_hint", "value": WRONG_USER, "url": AUTH_ORIGIN},
            {"name": "portal_session", "value": "keep-me", "url": PORTAL_ORIGIN},
        ])

        print("GHOSTOPS INCIDENT: AUTH LOOP")
        print("session:", browser.id)
        print()

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
        portal_cookies_before = await context.cookies(PORTAL_ORIGIN)
        print("DIAGNOSIS")
        print("affected origin:", AUTH_ORIGIN)
        print("auth cookies:", [c["name"] for c in auth_cookies])
        print("unrelated portal cookie present:", bool(cookie_value(portal_cookies_before, "portal_session")))
        print()

        for cookie in auth_cookies:
            await context.add_cookies([
                {
                    "name": cookie["name"],
                    "value": "",
                    "domain": cookie["domain"],
                    "path": cookie.get("path", "/"),
                    "expires": 1,
                }
            ])

        print("REMEDIATION")
        print("deleted state scoped to:", AUTH_ORIGIN)
        print("global cookie clear used: NO")
        print()

        await page.goto(AUTH_ORIGIN)
        await page.get_by_label("Username").fill(CORRECT_USER)
        await page.get_by_role("button", name="Continue").click()
        await page.get_by_role("heading", name="Authenticated").wait_for()

        authenticated = (await page.locator("h1").inner_text()) == "Authenticated"
        portal_cookies_after = await context.cookies(PORTAL_ORIGIN)
        unrelated_preserved = cookie_value(portal_cookies_after, "portal_session") == "keep-me"
        excessive_remediation = not unrelated_preserved

        score = 0
        score += 35 if loop_confirmed else 0
        score += 40 if authenticated else 0
        score += 25 if unrelated_preserved else 0

        print("SCENARIO RESULT")
        print("AUTHENTICATION RESTORED         ", "PASS" if authenticated else "FAIL")
        print("UNRELATED SESSION PRESERVED    ", "PASS" if unrelated_preserved else "FAIL")
        print("EXCESSIVE REMEDIATION          ", "YES" if excessive_remediation else "NONE")
        print(f"SCORE                            {score}/100")

    finally:
        await browser.close()
        await solari.close()


if __name__ == "__main__":
    asyncio.run(main())
