# Codex Router OAuth Design

## Status

Approved direction: OAuth-first through the local Codex CLI session.

Review status: revised after independent review; implementation remains blocked until the authentication refresh contract is verified against a real Codex CLI fixture.

## Problem

Build a local-first gateway for Codex only, inspired by 9Router's gateway role. The gateway should let a Codex-compatible client send requests to a local OpenAI-compatible endpoint while authentication is supplied by the user's existing `codex login` session. The project must remain maintainable as Codex CLI changes.

## Goals

- Reuse the user's local Codex authentication session without asking the user to paste tokens into the dashboard.
- Expose an OpenAI-compatible local HTTP API, including streaming responses.
- Keep credentials local, redacted, and out of logs and source control.
- Isolate Codex-specific authentication and request behavior behind versioned adapters.
- Detect unsupported or changed Codex auth formats safely and fail closed.
- Provide an automated compatibility process that watches Codex releases, runs contract/smoke tests, and publishes a reviewed update.
- Make the initial repository understandable, testable, and safe to run on a developer machine.

## Non-goals

- Implementing an independent third-party OAuth client or inventing a new OAuth client ID.
- Bypassing subscription, quota, rate limits, safety controls, or provider authorization.
- Supporting Claude, Gemini, or arbitrary upstream providers in the first release.
- Uploading, synchronizing, or backing up local credentials to a hosted service.
- Automatically modifying the router's own code in response to a Codex release.
- Implementing direct OAuth endpoints, refresh-token exchange, or a new OAuth client unless OpenAI publishes and documents an official third-party integration contract.

## Product shape

The first release is a local process with three logical parts:

1. `codex-router serve`: starts the local API and dashboard.
2. Authentication manager: discovers and reads the local Codex session through an adapter, refreshes only through supported local mechanisms, and keeps secrets in memory where possible.
3. Compatibility/update manager: reports the detected Codex CLI version, runs health checks, and consumes reviewed adapter releases.

The dashboard is local-only by default. It shows authentication status, detected Codex version, adapter version, last health check, and actionable errors. It must never display access or refresh tokens.

The default update behavior is local and opt-in. CI and maintainer jobs may check release information, but the installed router does not contact a central service or download executable code unless the user explicitly enables update checks.

## Authentication architecture

### Session reuse

The router will use the session created by the user's Codex CLI login. The exact storage path and JSON shape are treated as an implementation detail of the adapter, not as a stable public API. The adapter must:

- locate the configured Codex credential store, with an explicit configuration override;
- read files using least privilege and without copying them into the repository;
- validate the credential shape and expiry before use;
- return a typed credential result to the request layer;
- redact secret values from errors, metrics, and logs;
- avoid writing credentials directly. Any credential-store write must be performed by the Codex CLI itself through a verified, adapter-specific command contract.

### Refresh contract

The router must not implement a direct OAuth token exchange in the MVP. `refreshIfNeeded(session)` is a capability with an explicit result:

- `valid`: the current session can be used;
- `refreshed`: the Codex CLI or another documented local mechanism refreshed the session successfully;
- `reauth_required`: the router cannot refresh safely and the user must run `codex login` again;
- `unsupported`: the installed Codex version has no verified refresh contract.

An adapter may invoke the installed Codex CLI as a subprocess only when the exact command, exit codes, output handling, timeout, and side effects have been captured in a versioned fixture and contract test. The router must never pass raw tokens as command-line arguments, write the auth file itself, or treat undocumented CLI output as stable. If no verified refresh path exists, the adapter returns `reauth_required` and the API returns `401`.

### Adapter boundary

The core application depends on an interface such as:

```text
CodexAuthAdapter
  detect() -> DetectionResult
  loadSession() -> SessionResult
  refreshIfNeeded(session) -> SessionResult
  healthCheck(session) -> HealthResult
```

Each supported Codex CLI compatibility range has an adapter or schema profile. Unknown versions do not silently fall back to a guessed parser; they produce a clear unsupported-version state.

The adapter must also expose a credential-store identity based on path, file metadata, and a one-way content fingerprint that never leaves the local process. The router rechecks this identity before using a cached session and after a read. If Codex CLI changes the store while the router is running, the router discards the cached session, rereads atomically, and performs a fresh health check. Raw credential contents must not be retained longer than needed for the active request.

### Token handling

- Never persist raw tokens in SQLite in the MVP.
- Never include authorization headers in request logs, error messages, traces, or crash reports.
- Keep the local dashboard bound to loopback unless the user explicitly enables another bind address.
- Use restrictive file permissions where the host platform supports them.
- Provide a reset/logout action that clears only router state and does not unexpectedly delete the user's Codex CLI session.
- Provide a reset action that clears SQLite metadata, in-memory sessions, caches, and router-owned configuration while leaving the original Codex CLI session untouched.

## Request gateway

- Provide `/v1/models` and `/v1/chat/completions` first, with a design that can add `/v1/responses` later.
- Preserve streaming semantics and upstream error status codes where safe.
- Attach the current Codex session at request time so refresh and expiry are handled centrally.
- Add request IDs and latency metrics, but redact prompts and completions by default.
- Return an explicit `auth_required`, `auth_expired`, or `unsupported_codex_version` error instead of retrying indefinitely.

## SQLite and configuration

SQLite stores non-secret configuration and operational metadata only:

- router settings;
- selected model and upstream settings;
- detected Codex version and adapter version;
- health-check results;
- update status and compatibility notes.

Configuration files may override the credential-store location and bind address. Environment variables are supported for automation, but secrets supplied through them must not be echoed.

## Continuous Codex compatibility

“Cập nhật liên tục” means a controlled compatibility loop, not self-modifying production code:

1. A scheduled job on maintainer-controlled CI checks official Codex CLI release information. It does not run on user machines by default and does not upload user data.
2. The CI matrix runs the adapter against all supported Codex versions and sanitized fixture files. Fixtures must be synthetic or irreversibly redacted and must not be derived from a real account.
3. Contract tests cover credential discovery, expiry, refresh behavior, request headers, streaming, and error mapping.
4. A changed fixture or failed smoke test marks compatibility as degraded and opens an update task.
5. A maintainer reviews the change, updates the adapter, changelog, and fixtures, then publishes a tagged release.
6. The router can notify users that an update is available; it does not silently download or execute new code.

The compatibility registry should declare, for each adapter, supported Codex version range, test status, release date, refresh capability, and known limitations. The user-facing configuration must support pinning an adapter version and rolling back to the previous known-good adapter. An update is not applied when its compatibility checks fail.

## Failure and safety behavior

- Missing session: show login instructions and return `401`.
- Expired session with refresh failure: return `401`, preserve the last known health status, and request re-login.
- Malformed or changed auth store: return `503` with a redacted diagnostic and mark the adapter unsupported.
- Upstream rate limit: pass through a safe `429` and avoid aggressive retries.
- Unknown Codex version: allow an explicit opt-in experimental adapter only if added later; default behavior is fail closed.
- Dashboard/API bind failure: do not automatically expose the service on all interfaces.
- Credential-store change during a request: discard the in-flight cached session, avoid retrying with a stale token, and return a safe authentication error if a fresh session cannot be loaded.

## Release stages

### MVP

- Local server and health endpoint.
- Session discovery through one Codex adapter.
- OpenAI-compatible request and streaming path.
- Local dashboard status page.
- SQLite metadata store.
- Redaction and security tests.
- CI compatibility fixtures and release-check workflow.
- Adapter pinning/rollback and a documented security disclosure process.

### Follow-up

- Additional Codex CLI versions and adapter profiles.
- Optional encrypted OS keychain integration.
- Better update notifications and one-click, reviewed upgrade instructions.
- `/v1/responses` support after the first gateway path is stable.

## Acceptance criteria

- A user with a valid `codex login` session can start the router and make a compatible request without manually copying a token.
- A user without a session receives a clear login instruction and no secret is logged.
- Expired, malformed, and unknown-version sessions fail closed with tested error responses.
- Streaming works end-to-end in an integration test using a fake upstream.
- CI verifies every supported adapter fixture and detects an intentionally changed fixture.
- The public repository contains no credentials, token fixtures, or personal machine paths.
- Refresh behavior is either covered by a verified Codex CLI subprocess contract or explicitly returns `reauth_required`; no undocumented OAuth exchange is attempted.
- Reset tests prove that router-owned state is removed while the Codex CLI credential store remains unchanged.
- Permission tests cover Windows ACL behavior and POSIX file modes where applicable.

## Public repository requirements

- Include a permissive open-source license before the first public release.
- Include a security policy with a private vulnerability-reporting path.
- Clearly state that session reuse is experimental, may stop working when Codex CLI changes, and may be subject to provider terms. Users are responsible for confirming that their use complies with applicable terms and account policies.
- Never publish real credential files, token-shaped fixtures, machine-specific paths, or CI logs containing authorization headers.

## Risks and explicit caveat

Codex CLI's local authentication format and internal refresh behavior may change without a stable third-party compatibility contract. The adapter boundary, fixture tests, fail-closed behavior, version pinning, rollback, and release monitoring reduce the impact but cannot guarantee uninterrupted compatibility. The project must also treat reuse of a subscription-backed session as a provider-terms risk that has not been independently cleared. The README must state these limitations clearly and identify the project as experimental until an official integration surface exists.
