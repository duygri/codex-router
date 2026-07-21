# Codex Router Phase D: Operational Readiness Design

## Goal

Make the Codex-only router easier to diagnose and operate by separating local
HTTP liveness from Codex App Server readiness, without weakening the existing
loopback and fail-closed security boundaries.

## Context

The router already exposes `/health`, `/status`, and an operations dashboard.
The real adapter starts the locally installed Codex App Server per request and
uses the CLI's authenticated session. A running HTTP process currently does not
prove that the configured Codex executable exists, that App Server can start,
or that a live model catalog is available. Operators therefore discover these
failures only after sending a completion request.

## Non-goals

- No prompt or completion is sent during diagnostics.
- No bearer token, refresh token, request header, or raw App Server event is
  returned or stored.
- `/health` will not invoke Codex and will remain a cheap liveness probe.
- No persistent App Server supervisor is introduced in this phase.
- Tools, approvals, function calling, and multimodal input remain disabled.

## Proposed behavior

### CLI doctor command

Add `codex-router doctor` as an explicit operator command. It runs a bounded,
read-only diagnostic and prints a JSON-safe report with checks for:

1. Router configuration: adapter, loopback bind, key configured, and safe queue
   settings. The key value is never printed.
2. Codex CLI: executable can be started with `--version`; capture only a
   redacted success/version status, never stderr or environment data.
3. App Server initialization: the CLI can start `app-server --listen stdio://`
   and complete only the JSON-RPC `initialize`/`initialized` handshake.
4. Model catalog: App Server `model/list` returns at least one validated model.

The command runs before SQLite is opened, so it does not create or modify the
metadata directory/database. It uses the same strict configuration validation
as `/ready`: adapter must be exactly `real-v1` or `synthetic-v1`, bind host
must be loopback, port must be `1..65535`, queue size must be non-negative,
and queue timeout must be finite and at least `0.1` seconds. Invalid values
produce a configuration failure rather than silently falling back. The same
validation applies to effective `serve --host` and `serve --port` overrides,
and unknown adapters fail closed before gateway construction; they cannot fall
through to synthetic bearer forwarding.

The exact output schema is:

```json
{
  "status": "ready|not_ready|invalid_config",
  "checks": {
    "config": {"ok": true, "code": "ok", "message": "Configuration is valid"},
    "codex_cli": {"ok": true, "code": "ok", "version": "0.145.0-alpha.18", "message": "Codex CLI is available"},
    "app_server": {"ok": true, "code": "ok", "message": "Codex App Server is available"},
    "model_catalog": {"ok": true, "code": "ok", "model_count": 1, "message": "Codex models are available"}
  }
}
```

The `checks` object always contains all four keys. For synthetic-v1,
`codex_cli`, `app_server`, and `model_catalog` are present as
`{"ok": true, "code": "skipped", "message": "Not required for synthetic-v1"}`;
doctor and `/ready` use the same behavior. `version` and `model_count` are
omitted when a check fails or is skipped. `code` is one of the stable values
`ok`, `skipped`, `invalid_config`, `codex_cli_not_found`,
`codex_cli_unavailable`, `app_server_unavailable`, `app_server_timeout`,
`app_server_protocol_error`, `model_catalog_empty`, `model_catalog_invalid`,
`model_catalog_unavailable`, or `readiness_wait_timeout`. Messages are fixed
allowlisted text; subprocess command lines, paths, stderr, raw exceptions, and
model response payloads are never returned. The command exits `0` only for
`ready`, `1` for `not_ready`, and `2` for `invalid_config`.

### Readiness endpoint

Add `GET /ready` on loopback. It returns:

- `200` with the exact `{ "status": "ready", "checks": ... }` schema above when the configured
  real-v1 Codex path is usable;
- `503` with the same safe envelope and `{ "status": "not_ready" }` when a
  check fails;
- `200` with the same schema and three `skipped` checks for synthetic-v1,
  because it has no local App Server dependency. Unknown adapters never reach
  `/ready`: `codex-router doctor` reports `status: "invalid_config"` and exit
  code `2`, while `codex-router serve` reports the safe configuration error,
  exits with code `2`, and never constructs a gateway or binds a socket.

Readiness uses a short-lived, bounded probe and is not authenticated because
the response contains no secrets or user data. A shared `ReadinessProbe`
coordinator serializes probes and caches the safe result for 10 seconds;
concurrent callers wait at most 2 seconds for an in-flight probe, then receive
`503` with `status: "not_ready"` and a synthetic `app_server` check carrying
`code: "readiness_wait_timeout"`, without starting another process. The App
Server check performs one
`initialize` handshake and one `model/list` request in the same probe process.
The dashboard consumes this shared result rather than spawning a separate
probe. `/health` remains process-only and does not call readiness.

### Dashboard

The dashboard adds a compact readiness state and a link-free explanation of
the first failed check. It must use the existing safe text rendering and
responsive dark operations style. It never shows the router key or raw error
details.

## Error handling and security

- Use a dedicated diagnostic result type rather than leaking `AppServerError`
  messages or subprocess exceptions.
- Apply a strict timeout to version and App Server probes.
- Invoke subprocesses with an argv list and `shell=False`; suppress stderr,
  cap stdout to 64 KiB, parse only a strict Codex version token, and never
  return raw subprocess output.
- Always terminate the probe process in a `finally` path.
- Treat missing executable, non-zero version command, handshake failure,
  timeout, malformed JSON, and empty model catalog as safe readiness failures.
- Never retry a failed readiness probe inside the same request.
- Use the existing `ModelCatalog` model-ID validation rules for non-empty
  `model/list` results, but validate the raw list strictly before normalization:
  every item must be an object with exactly one usable string `id` or `model`
  field, and every identifier must pass the existing safe model-ID validator.
  A mixed valid/malformed list is `model_catalog_invalid`; an empty list is
  `model_catalog_empty`; App Server protocol/transport failures map to
  `model_catalog_unavailable`.
- Preserve the existing fixed App Server policy and no-direct-bearer design.

## Testing strategy

- Unit tests for CLI version success/failure, App Server handshake success,
  timeout/malformed response, empty catalog, and process cleanup.
- HTTP tests for `/health` remaining cheap, `/ready` status mapping, safe
  envelope fields, loopback restriction, and synthetic-v1 behavior.
- Coordination tests for 10-second cache reuse, 2-second waiter timeout, and
  cleanup of a failed in-flight probe.
- CLI tests for doctor exit codes and secret-free output.
- Existing full suite, compile check, diff check, and secret scan must remain
  green. The live no-cost `model/list` smoke is manual/maintainer-side only,
  enabled by an explicit local Codex CLI path and existing `codex login`; it is
  never run in CI and never sends a prompt.

## Alternatives considered

1. **Version-only check:** cheaper, but it does not prove App Server startup or
   model discovery. Rejected as insufficient for a real readiness signal.
2. **Persistent App Server supervisor:** lower per-request startup cost, but it
   expands process lifecycle, isolation, crash recovery, and auth exposure
   risks. Deferred until a separate security design.
3. **Make `/health` perform all checks:** familiar to some deployments, but it
   makes liveness expensive and can cause monitoring failures to spawn work.
   Rejected in favor of separate `/ready`.
