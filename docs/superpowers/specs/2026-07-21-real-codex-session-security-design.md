# Real Codex Session Adapter and Security Design

## Status

Approved direction: implement a real session reader for the current Codex CLI
file-based credential shape, with a fail-closed security boundary. Direct OAuth
refresh is explicitly out of scope.

## Goal

Make `codex-router` usable with a real local Codex login while preserving a
local-only, secret-safe threat model.

## Verified boundary

The current local Codex session store is `CODEX_HOME/auth.json` (default
`~/.codex/auth.json`) and contains a `tokens` object with `access_token`,
`refresh_token`, and `account_id` fields. The exact private refresh protocol is
not a published third-party contract. The router may read the current access
token in memory, but it must not call an undocumented refresh endpoint or write
the credential file.

The official Codex documentation supports `CODEX_HOME`, file-based auth, `codex
login`, `codex login status`, and `CODEX_ACCESS_TOKEN` for trusted automation.
It does not establish a stable public JSON schema or refresh endpoint for
third-party clients.

The real-v1 compatibility claim is conditional: the local fixture shape is not
enough. A profile is marked usable only after a no-cost `GET /v1/models` smoke
request succeeds against the configured upstream with the access token. The
compatibility registry records the exact detected Codex CLI version, adapter
profile, upstream host/path, HTTP result, and date of the smoke check. An
unknown Codex version cannot be promoted to verified compatibility. A known
Codex version with a 2xx smoke result is recorded as a verified entry only
after the exact secret-free evidence is persisted and reviewed; the router
never self-modifies its own registry.

## Architecture

### Real auth adapter

`AuthAdapter` becomes a versioned profile loader:

- `real-v1` reads `tokens.access_token` and the JWT `exp` claim from the
  configured auth file.
- File source precedence is explicit: `CODEX_ROUTER_AUTH_FILE` wins, then an
  explicitly set `CODEX_HOME/auth.json`, then the platform home default. An
  explicitly set `CODEX_HOME` is authoritative: a missing auth file fails
  closed and never falls back to another home. Environment-token mode is opt-in
  only through `CODEX_ROUTER_AUTH_MODE=env`; in that mode `CODEX_ACCESS_TOKEN`
  is required and the file is not read.
- A non-JWT environment token is accepted only with an explicit
  `CODEX_ROUTER_TOKEN_EXPIRES_AT` ISO-8601 value. JWT expiry is required for a
  JWT-shaped token: missing, non-numeric, malformed, or invalid `exp` is
  rejected and cannot be overridden by configured expiry. A 60-second
  clock-skew window treats a valid token as expired before its exact `exp`
  time.
- It verifies the file is regular, reads it twice to detect concurrent writes,
  computes only a one-way fingerprint, and discards raw file bytes after
  parsing.
- It opens files with no-follow semantics where the host supports them,
  verifies path/file identity before and after reading, rejects symlinks and
  reparse-point-like paths, and fails closed when required ACL inspection is
  unavailable. POSIX mode checks and Windows ACL checks are covered separately.
- It rejects malformed JSON, missing token fields, non-JWT tokens without a
  configured expiry, expired tokens, and unknown adapter versions.
- It never reads or uses `refresh_token` for network requests.
- Expiry returns `reauth_required` with instructions to run `codex login`.

The current synthetic fixture profile remains available for unit tests but is
not the default adapter.

### Upstream and request boundary

- The default upstream is `https://api.openai.com/v1`; users can override it
  for a compatible local test service.
- The router sends the bearer access token only to `https://api.openai.com` or
  a loopback upstream used in local tests. Arbitrary remote custom upstreams
  are refused, which prevents a configured DNS-rebinding target from becoming
  a credential exfiltration endpoint. Plain HTTP is allowed only for loopback
  tests; there is no insecure override in the shipped tool.
- Upstream URLs cannot contain userinfo, fragments, or embedded credentials;
  redirects are disabled rather than followed. TLS hostname verification
  remains enabled for the OpenAI host.
- The local gateway binds to loopback only; every non-loopback bind is refused,
  even when a router key is configured.
- `/health` and `/status` remain unauthenticated but contain only safe status.
- `/v1/*` requires a router API key. The key is supplied through
  `CODEX_ROUTER_API_KEY` and compared using constant-time comparison against
  the dedicated `X-Codex-Router-Key` header. If no key is configured, `/v1/*`
  fails closed with setup instructions. This key never authorizes a
  non-loopback bind; all non-loopback binds are refused.
- Authorization headers, token-shaped values, request bodies, and upstream
  response bodies are not logged.
- Request IDs are normalized to a small safe character set before being copied
  into response headers. Status responses use `Cache-Control: no-store` and
  contain no credential-shaped fields.

### Failure behavior

- Missing auth: `401 auth_required`.
- Expired/invalid access token: `401 auth_expired` with `codex login` guidance.
- Unknown auth shape or adapter: `503 unsupported_codex_version`.
- Missing router key: `401 router_auth_required`.
- Wrong router key: `403 router_auth_invalid`.
- Non-loopback HTTP upstream: `503 insecure_upstream`.
- Upstream `401`: `401 auth_expired` without retrying.
- Changed credential fingerprint: reject before forwarding and require a fresh
  request.

## Security requirements

- No raw credential value in source, fixtures, SQLite, HTML, JSON status,
  exception messages, or CI output.
- Do not modify, delete, or refresh the user's Codex credential store.
- Refuse symlinked/non-regular auth files where the host permits inspection.
- On POSIX, enforce owner-only permission bits for the auth file. On Windows,
  expose a safe diagnostic when ACL inspection is unavailable and never weaken
  the file ACL.
- Use atomic, stable reads and one-way fingerprints for change detection.
- Use `hmac.compare_digest` for router API-key comparison.
- Do not retry authentication failures or upstream `429` responses.
- Keep all error messages actionable but secret-free.

## Testing and acceptance

- Add sanitized real-shape fixtures containing only non-secret JWT-shaped data;
  no real account identifiers or tokens. Tests use an exact allowlist for the
  fixture's fake values and separately scan all other tracked content.
- Test JWT expiry parsing, missing/invalid claims, real-shape loading, env
  override precedence, expiry clock skew, file safety, symlink/race/ACL
  behavior, router-key auth, bind security, insecure upstream refusal,
  redirect blocking, upstream `401` mapping, redaction, and stale fingerprint
  rejection.
- Run the existing unit suite, compile checks, `git diff --check`, and a
  no-secret scan over tracked files.
- Run a live, no-cost `/v1/models` smoke check only if the local access token
  and network are available; never send a paid chat/completion request without
  a separate explicit request. If the smoke check cannot be completed, keep
  the profile labeled experimental rather than claiming real usability.
- Update README and compatibility registry to state that `real-v1` uses the
  current access token and requires `codex login` again after expiry.

## Explicit non-goals

- No direct OAuth client registration or token exchange.
- No undocumented refresh endpoint.
- No API-key extraction from `auth.json`.
- No remote credential backup, telemetry, phone-home update, or silent code
  download.
