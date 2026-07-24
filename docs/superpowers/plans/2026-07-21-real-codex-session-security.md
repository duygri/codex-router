# Real Codex Session Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local router usable with the current real Codex file-based session while enforcing fail-closed credential and local API security.

**Architecture:** Keep the existing standard-library gateway, but replace the synthetic-only default with a versioned `real-v1` adapter that reads only the current access token and JWT expiry from `CODEX_HOME/auth.json`. Add a separate constant-time router API-key boundary, safe upstream defaults, and explicit re-login behavior instead of undocumented OAuth refresh.

**Tech Stack:** Python 3.8+, standard library (`json`, `hmac`, `urllib`, `http.server`), `unittest`, SQLite metadata, GitHub Actions.

---

### Task 1: Lock the real auth contract with sanitized tests

**Files:**
- Create: `tests/fixtures/auth/real-v1-session.json`
- Modify: `tests/test_auth.py`
- Modify: `tests/test_public_safety.py`

- [ ] **Step 1: Write failing tests for the real Codex shape**

Add tests that load `{"auth_mode":"chatgpt","tokens":{"access_token":"...","refresh_token":"...","account_id":"..."}}`, derive expiry from a JWT payload, reject missing or malformed `exp`, apply a 60-second clock-skew window, and never expose the refresh token through the returned session or safe status.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `$env:PYTHONPATH="$pwd\src"; python -m unittest tests.test_auth tests.test_public_safety -v`

Expected: FAIL because the current adapter only accepts `schema_version=1` synthetic data and the fixture is not yet present.

- [ ] **Step 3: Add a sanitized real-shape fixture**

Use a locally generated JWT-shaped token with a non-secret header and payload, a fake signature, a fake refresh token, and a non-personal account id. The fixture must contain no real token, email, path, or account identifier.

- [ ] **Step 4: Re-run to confirm the failure is now implementation-only**

Run the same focused command and confirm failures are about unsupported real-v1 behavior, not missing files or malformed test setup.

- [ ] **Step 5: Commit the tests and fixture**

```powershell
git add tests/test_auth.py tests/test_public_safety.py tests/fixtures/auth/real-v1-session.json
git commit -m "test: specify real Codex session profile"
```

### Task 2: Implement the real-v1 auth adapter

**Files:**
- Modify: `src/codex_router/auth.py`
- Modify: `tests/test_auth.py`
- Modify: `tests/test_permissions.py`

- [ ] **Step 1: Implement the smallest real-v1 parser**

Add a profile selector for `synthetic-v1` and `real-v1`. For real-v1, parse only `tokens.access_token`, derive `exp` from the JWT payload, reject tokens with an invalid three-part encoding or invalid numeric expiry, apply 60 seconds of expiry leeway, and keep refresh tokens out of `Session`. Preserve stable double-read and one-way fingerprint behavior.

- [ ] **Step 2: Write and run the failing environment-mode tests**

Before implementation, add tests for explicit `env` mode, rejection when the mode is omitted, non-JWT expiry requirements, malformed JWT `exp` rejection, and a non-empty source fingerprint that permits the gateway path. Run the focused tests and confirm they fail for the expected unsupported-profile behavior.

- [ ] **Step 3: Add explicit environment-token support**

Allow `CODEX_ACCESS_TOKEN` only when `CODEX_ROUTER_AUTH_MODE=env`, with JWT expiry validation or an explicit `CODEX_ROUTER_TOKEN_EXPIRES_AT` for non-JWT tokens. File source precedence is `CODEX_ROUTER_AUTH_FILE`, then `CODEX_HOME/auth.json`, then the platform default. Environment sessions use a one-way in-memory source fingerprint derived from a constant label and token hash; the raw token never enters the fingerprint or logs. Never print or persist the environment token.

- [ ] **Step 4: Implement fail-closed expiry behavior**

Return `EXPIRED` and `REAUTH_REQUIRED` with `codex login` guidance. Do not implement a refresh callback for real-v1 and do not read `refresh_token` for requests.

- [ ] **Step 5: Run focused auth tests and the full suite**

Run: `$env:PYTHONPATH="$pwd\src"; python -m unittest tests.test_auth -v`

Then run: `$env:PYTHONPATH="$pwd\src"; python -m unittest discover -s tests -v`

Expected: all tests pass, with only the existing Windows ACL skip.

- [ ] **Step 6: Commit the adapter**

```powershell
git add src/codex_router/auth.py tests/test_auth.py
git commit -m "feat: read real Codex file sessions safely"
```

- [ ] **Step 7: Add and run file-safety tests before permission code changes**

Add failing tests in `tests/test_permissions.py` for regular-file validation, symlink rejection where supported, POSIX owner-only mode enforcement, stable identity checks, and the Windows ACL diagnostic/fail-closed result. Run the focused permission tests and confirm they fail for missing hardening behavior.

- [ ] **Step 8: Implement credential-file hardening and verify it**

Use descriptor/no-follow flags where the host supports them, compare file identity before and after the read, reject symlinks/reparse-point-like files, and make ACL inspection explicit. Run `python -m unittest tests.test_permissions -v` and the auth tests again; do not weaken the existing Windows skip into a silent pass.

- [ ] **Step 9: Commit the credential-file hardening**

```powershell
git add src/codex_router/auth.py tests/test_auth.py tests/test_permissions.py
git commit -m "feat: harden Codex credential file reads"
```

### Task 3: Add a secure local router API boundary

**Files:**
- Modify: `src/codex_router/config.py`
- Modify: `src/codex_router/server.py`
- Modify: `src/codex_router/gateway.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Write failing tests for router-key authentication**

Cover missing key, wrong key, correct `X-Codex-Router-Key`, constant-time comparison use, refusal of every non-loopback bind even with a key, safe request-ID normalization, upstream `401` mapping, redirects, arbitrary remote-upstream refusal, and the rule that every `/v1/*` route is protected while `/health`, `/status`, and `/` stay safe and unauthenticated.

- [ ] **Step 2: Run focused server tests to verify they fail**

Run: `$env:PYTHONPATH="$pwd\src"; python -m unittest tests.test_server tests.test_gateway -v`

Expected: FAIL because the current server forwards `/v1/*` without a router-owned credential and does not enforce bind, upstream URL, DNS-rebinding, or redirect safety.

- [ ] **Step 3: Implement the minimal key boundary**

Read `CODEX_ROUTER_API_KEY` without logging it, compare with `hmac.compare_digest` against `X-Codex-Router-Key`, return safe `401`/`403` errors, refuse every non-loopback bind even with a key, normalize request IDs before returning them in headers, add `Cache-Control: no-store` to status responses, and ensure the upstream Codex bearer token is never confused with the local router key.

Map an upstream `401` to `GatewayError(401, "auth_expired", ...)` without retrying and preserve the existing no-retry behavior for `429`.

- [ ] **Step 4: Add safe upstream validation**

Default the upstream to `https://api.openai.com/v1`. Allow only the exact OpenAI API host over HTTPS or loopback HTTP/HTTPS fake-upstream hosts. Reject arbitrary remote custom hosts, userinfo, fragments, and non-loopback `http://` URLs with a safe configuration error. There is no insecure override. Disable redirects entirely so the bearer token cannot cross hosts or DNS-rebinding targets.

- [ ] **Step 5: Run focused tests and commit**

Run: `$env:PYTHONPATH="$pwd\src"; python -m unittest tests.test_server tests.test_gateway -v`

```powershell
git add src/codex_router/config.py src/codex_router/server.py src/codex_router/gateway.py tests/test_server.py tests/test_gateway.py
git commit -m "feat: secure the local router boundary"
```

### Task 4: Wire the real profile and safe CLI behavior

**Files:**
- Modify: `src/codex_router/__main__.py`
- Modify: `src/codex_router/dashboard.py`
- Modify: `compatibility/registry.json`
- Create: `compatibility/verification/real-v1.json`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_compatibility.py`
- Create: `tests/test_cli_integration.py`

- [ ] **Step 1: Write failing tests for real-v1 defaults and safe status**

Verify the default adapter is `real-v1`, status reports adapter/profile and auth state without token-like fields, `CODEX_HOME` and explicit auth-file precedence work, `/v1/models` requires `X-Codex-Router-Key`, the environment-token path works end-to-end with its non-empty source fingerprint, reset still leaves the Codex credential store untouched, and unknown-version entries cannot become verified.

- [ ] **Step 1a: Write and run the failing verified-promotion tests**

Before registry implementation, add tests requiring a known Codex version, exact profile/upstream/result/timestamp fields, and a 2xx smoke result before `status: verified`; missing/unknown version or non-2xx remains `unverified`. Run the focused compatibility tests and confirm they fail for the expected missing metadata.

- [ ] **Step 2: Implement CLI/config wiring**

Make `real-v1` the default adapter, honor the documented auth-file precedence including authoritative `CODEX_HOME`, pass the router API key into the server, refuse every non-loopback bind, keep `reset` metadata-only, detect the Codex CLI version for compatibility evidence, and cover both the CLI-created server and `run_server` path in the integration tests.

- [ ] **Step 3: Update compatibility metadata**

Declare `real-v1` as experimental/current-profile support with `refresh_capability: reauth_required`, no silent update, exact upstream/version evidence fields, and an explicit limitation that Codex CLI auth internals may change. Unknown Codex versions remain unverified. Add a reviewed success path: known Codex version plus 2xx `/v1/models` writes the exact secret-free evidence record to `compatibility/verification/real-v1.json` and updates the registry entry to `verified`; the router never performs this repository write itself.

- [ ] **Step 4: Define the sanitized-fixture secret scan**

Use an exact allowlist test for the fake values in `real-v1-session.json`, assert the fixture contains no personal identifiers or real JWT signatures, and scan every other tracked file for token-shaped values. The allowlist test owns the fixture exception; the shell scan must not exempt arbitrary lines by marker.

- [ ] **Step 5: Run CLI smoke checks without exposing credentials**

Run `status` against the local real auth file and assert output contains only safe fields. Run `reset` against a temporary database and compare the auth-file SHA-256 before and after. Then run a no-cost `GET /v1/models` through the local router and capture a machine-readable, secret-free evidence record containing `codex_version`, `adapter_profile`, `upstream_host`, `upstream_path`, HTTP status, safe error code, and UTC timestamp. A missing/unknown Codex version or non-2xx result keeps the registry entry unverified.

- [ ] **Step 6: Commit CLI and registry wiring**

```powershell
git add src/codex_router/__main__.py src/codex_router/dashboard.py compatibility/registry.json compatibility/verification/real-v1.json tests/test_dashboard.py tests/test_compatibility.py tests/test_cli_integration.py
git commit -m "feat: make real-v1 the safe default"
```

### Task 5: Document usage and complete security verification

**Files:**
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `tests/test_public_safety.py`
- Modify: `.github/workflows/compatibility.yml`

- [ ] **Step 1: Add README security and usage guidance**

Document `codex login`, `CODEX_ROUTER_API_KEY`, the default upstream, the local OpenAI-compatible endpoint, expiry requiring re-login, and the explicit no-direct-refresh boundary. State that users should not expose the router beyond loopback.

- [ ] **Step 2: Add public-safety assertions**

Test that README does not claim automatic OAuth refresh, tracked files contain no real token-shaped values, and the registry advertises the real-v1 limitations.

- [ ] **Step 3: Run the full verification suite**

Run:

```powershell
$env:PYTHONPATH="$pwd\src"
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
git ls-files | Where-Object { $_ -ne 'tests/fixtures/auth/real-v1-session.json' } | ForEach-Object { if(Test-Path -LiteralPath $_ -PathType Leaf){ Select-String -LiteralPath $_ -Pattern 'Bearer eyJ|refresh_token.*rt\.|access_token.*eyJ' -SimpleMatch:$false -ErrorAction SilentlyContinue } }
```

Expected: all tests pass except the documented Windows ACL skip, compile/diff checks exit zero, and the secret scan returns no matches.

- [ ] **Step 4: Run a no-cost live smoke check**

If the network and local token are available, make only `GET /v1/models` through the router with `X-Codex-Router-Key`. Record only HTTP status and safe error code. A non-2xx result keeps the profile labeled experimental; do not send a chat/completion request during implementation.

- [ ] **Step 5: Commit documentation and verification updates**

```powershell
git add README.md SECURITY.md tests/test_public_safety.py .github/workflows/compatibility.yml
git commit -m "docs: document real-v1 security and setup"
```

### Task 6: Final branch verification and publish

**Files:**
- No additional source files expected.

- [ ] **Step 1: Inspect the complete diff and status**

Run: `git status --short --branch; git diff main...HEAD --stat; git diff main...HEAD --check`

- [ ] **Step 2: Re-run the complete suite from a clean command**

Run: `$env:PYTHONPATH="$pwd\src"; python -m unittest discover -s tests -v`

- [ ] **Step 3: Push the feature branch**

```powershell
git push -u origin codex/real-v1-security
```

- [ ] **Step 4: Open a draft PR for review**

Use the GitHub publish workflow after push; include the security boundary, the no-refresh limitation, verification results, and the exact user action required (`codex login` plus router API key).
