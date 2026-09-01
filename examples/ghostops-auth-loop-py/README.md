# GhostOps: targeted auth-loop recovery

A small GhostOps scenario showing an enterprise support agent recovering from a
browser authentication loop **without clearing unrelated browser state**.

This scenario is based on a real support pattern: a user enters the wrong
username at an identity provider, the browser persists identity/session state,
and subsequent attempts remain trapped in the same flow. The correct fix is to
remove only the affected site's authentication state and retry with the correct
identity.

For safety and reproducibility, this example does **not** automate Thomson
Reuters or any production identity provider. It uses two intercepted test
origins:

- `auth.ghostops.test` — simulated identity provider
- `portal.ghostops.test` — unrelated session state that must survive remediation

The browser itself is a real Solari cloud browser.

## What it demonstrates

1. Seed a browser with stale identity state and an unrelated session cookie.
2. Reproduce the authentication loop.
3. Diagnose persisted site-scoped auth state.
4. Delete only cookies scoped to the affected auth origin and assert the stale
   identity cookie is gone.
5. Retry with the correct username.
6. Verify authentication succeeds at the expected success URL with the expected
   page status.
7. Verify unrelated, previously loaded browser state was preserved.
8. Print the Solari session ID and replay URL for audit evidence.
9. Score the remediation for correctness and collateral damage.

## Run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...
python main.py
```

Expected final result:

```text
TARGETED COOKIE DELETED         PASS
AUTHENTICATION RESTORED          PASS
UNRELATED SESSION PRESERVED     PASS
EXCESSIVE REMEDIATION           NONE
SCORE                           100/100
```

## Why GhostOps cares

A naive support bot can solve this by clearing every cookie in the browser. A
competent enterprise agent should make the smallest effective change. This
scenario therefore evaluates not only whether the incident was resolved, but
whether unrelated user state survived the remediation.
