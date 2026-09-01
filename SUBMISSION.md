# GhostOps: minimum-change browser incident response

GhostOps is an enterprise incident-response agent concept built around a simple
rule: **agents should experiment on ghosts, not production**.

This cookbook submission implements its first vertical slice, AUTH LOOP, using
a real Solari cloud browser.

## The incident

A user accidentally enters the wrong username at an enterprise identity
provider. Persisted identity state traps every later attempt in the same failed
flow, preventing the user from returning to a clean username prompt.

The common support instruction—clear every browser cookie—can restore access,
but it also destroys unrelated sessions. The minimum effective remediation is
to remove only state scoped to the affected authentication origin.

## What the agent proves

1. Reproduce the stale-identity loop twice.
2. Inspect the affected origin's cookie state.
3. Confirm an unrelated, previously used portal session exists.
4. Delete only the affected domain's authentication cookies.
5. Enter the correct identity and verify authentication.
6. Confirm the unrelated portal session survived.
7. Score both resolution and collateral damage.
8. Record the Solari session and publish its replay URL in the run log.

## Safe by design

The submission does not automate a production service or use production
credentials. It intercepts two reserved `.test` origins to provide
deterministic identity and portal fixtures. All browser execution—navigation,
DOM interaction, cookie inspection and deletion, recording, and replay—occurs
inside an actual Solari cloud browser.

This separation makes the use case publicly reproducible while preserving the
technical behavior that matters: precise browser-state remediation.

## Evidence

- [Runnable Python scenario](examples/ghostops-auth-loop-py/main.py)
- [Successful live Solari workflow](https://github.com/dleemt-lgtm/solari-cookbook/actions/runs/33528831930)
- [Scenario documentation](examples/ghostops-auth-loop-py/README.md)

The verified result is:

```text
TARGETED COOKIE DELETED         PASS
AUTHENTICATION RESTORED         PASS
UNRELATED SESSION PRESERVED     PASS
EXCESSIVE REMEDIATION           NONE
SCORE                           100/100
```

## Built with AI

Codex acted as the implementer. Grok acted as the reviewer. Review feedback,
live Solari failures, and remote Chromium behavior were folded back into the
implementation until the public run passed end to end.

That development loop is part of the submission: use AI aggressively, verify
against the real platform, and ship the evidence.
