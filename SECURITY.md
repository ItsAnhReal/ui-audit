# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: [open a security advisory](https://github.com/ItsAnhReal/ui-audit/security/advisories/new) (*Security → Report a vulnerability*). Do not open a public issue. You will get an answer within a week; once a fix is released, the advisory is published with credit unless you prefer otherwise.

Fixes go into the latest release only.

## Scope

Of most interest:

- **The local app (`ui-audit ui`)**: it must bind 127.0.0.1 only, answer only to `127.0.0.1` and `localhost` host names (against DNS rebinding), require its per-start token on every API call, and serve screenshots only with its SameSite=Strict cookie. Any way for another website, or another user on the machine, to read runs or start audits through it is in scope.
- **The GitHub Action and `ui-audit ci`**: the token that posts the pull request comment must stay away from `install`, `start` and the audit, which run the pull request's code. A way for a pull request to read or use that token is in scope.

Out of scope: what the audited app itself does when `ui-audit` loads it (it runs in a normal browser, with the session you gave it), and sessions saved by `ui-audit login`, which work like a password by design.
