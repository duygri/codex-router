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

## Architecture

### Real auth adapter

`AuthAdapter` becomes a versioned profile loader:

- `real-v1` reads `tokens.access_token` and the JWT `exp` claim from the
  configured auth file.
- It accepts `CODEX_ACCESS_TOKEN` only as an explicit trusted-automation
  override; the value is never echoed or persisted.
- It verifies the file is regular, reads it twice to detect concurrent writes,
  computes only a one-way fingerprint, and discards raw file bytes after
  parsing.
- It rejects malformed JSON, missing token fields, non-JWT tokens without a
  configured expiry, expired tokens, and unknown adapter versions.
- It never reads or uses `refresh_token` for network requests.
- Expiry returns `reauth_required` with instructions to run `codex login`.

The current synthetic fixture profile remains available for unit tests but is
not the default adapter.

### Upstream and request boundary

- The default upstream is `https://api.openai.com/v1`; users can override it
  for a compatible local test service.
- The router sends the bearer access token only to the configured upstream over
  HTTPS by default. Plain HTTP is allowed only for loopback upstreams unless a
  deliberate insecure override is configured for local testing.
- The local gateway binds to loopback by default.
- `/health` and `/status` remain unauthenticated but contain only safe status.
- `/v1/*` requires a router API key. The key is supplied through
  `CODEX_ROUTER_API_KEY` and compared using constant-time comparison. If no key
  is configured, `/v1/*` fails closed with setup instructions.
- Authorization headers, token-shaped values, request bodies, and upstream
  response bodies are not logged.

### Failure behavior

- Missing auth: `401 auth_required`.
- Expired/invalid access token: `401 auth_expired` with `codex login` guidance.
- Unknown auth shape or adapter: `503 unsupported_codex_version`.
- Missing router key: `401 router_auth_required`.
- Wrong router key: `403 router_auth_invalid`.
- Non-loopback HTTP upstream: `503 insecure_upstream`.
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
  no real account identifiers or tokens.
- Test JWT expiry parsing, missing/invalid claims, real-shape loading, env
  override precedence, file safety, router-key auth, insecure upstream refusal,
  redaction, and stale fingerprint rejection.
- Run the existing unit suite, compile checks, `git diff --check`, and a
  no-secret scan over tracked files.
- Run a live, no-cost `/v1/models` smoke check only if the local access token
  and network are available; never send a paid chat/completion request without
  a separate explicit request.
- Update README and compatibility registry to state that `real-v1` uses the
  current access token and requires `codex login` again after expiry.

## Explicit non-goals

- No direct OAuth client registration or token exchange.
- No undocumented refresh endpoint.
- No API-key extraction from `auth.json`.
- No remote credential backup, telemetry, phone-home update, or silent code
  download.
