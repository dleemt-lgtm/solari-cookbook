"""GhostOps auth-loop recovery using a real Solari cloud browser.

The identity provider is simulated with Playwright route interception so this
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

        # Route interception turns two reserved .test origins into our tiny,
        # deterministic enterprise simulator while the browser itself runs on
        # Solari infrastructure.
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
                    await route.fulfill(status=302, headers={"location": f"{PORTAL_ORIGIN}/home"}, body="")
                    return

            if identity_hint == WRONG_USER:
                await route.fulfill(status=200, content_type="text/html", body=LOOP_HTML)
            else:
                await route.fulfill(status=200, content_type="text/html", body=LOGIN_HTML)

        async def portal_route(route, request):
            cookies = await context.cookies(AUTH_ORIGIN)
            authenticated_user = cookie_value(cookies, "authenticated_user")
            if authenticated_user == CORRECT_USER:
                await route.fulfill(status=200, content_type="text/html", body=SUCCESS_HTML)
            else:
                await route.fulfill(status=302, headers={"location": AUTH_ORIGIN}, body="")

        await page.route(f"{AUTH_ORIGIN}/**", auth_route)
        await page.route(f"{PORTAL_ORIGIN}/**", portal_route)

        # Seed the incident. The auth origin contains stale identity state.
        # The portal cookie represents unrelated browser state that must remain.
        await context.add_cookies([
            {"name": "identity_hint", "value": WRONG_USER, "url": AUTH_ORIGIN},
            {"name": "portal_session", "value": "keep-me", "url": PORTAL_ORIGIN},
        ])

        print("GHOSTOPS INCIDENT: AUTH LOOP")
        print("session:", browser.id)
        print()

        # 1) Reproduce.
        await page.goto(AUTH_ORIGIN)
        first_status = await page.locator("#status").inner_text()
        print("REPRODUCTION")
        print("status:", first_status)

        await page.goto(AUTH_ORIGIN)
        second_status = await page.locator("#status").inner_text()
        loop_confirmed = "same failed login flow" in second_status
        print("redirect/auth loop confirmed:", "PASS" if loop_confirmed else "FAIL")
        print()

        # 2) Inspect state and choose the smallest effective remediation.
        auth_cookies = await context.cookies(AUTH_ORIGIN)
        portal_cookies_before = await context.cookies(PORTAL_ORIGIN)
        print("DIAGNOSIS")
        print("affected origin:", AUTH_ORIGIN)
        print("auth cookies:", [c["name"] for c in auth_cookies])
        print("unrelated portal cookie present:", bool(cookie_value(portal_cookies_before, "portal_session")))
        print()

        # 3) Targeted remediation: expire cookies only for the affected origin.
        # We intentionally do NOT call context.clear_cookies(), because that
        # would destroy unrelated sessions and should score as collateral damage.
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

        # 4) Retry with the correct identity.
        await page.goto(AUTH_ORIGIN)
        await page.get_by_label("Username").fill(CORRECT_USER)
        await page.get_by_role("button", name="Continue").click()
        await page.wait_for_url(f"{PORTAL_ORIGIN}/home")

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
