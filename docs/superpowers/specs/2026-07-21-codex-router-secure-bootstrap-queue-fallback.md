# Codex Router Phase C: Secure Bootstrap, Bounded Admission, and Safe Fallbacks

## Goal

Make the local Codex-only router usable without placing a long-lived router key
in shell history, while preventing unbounded App Server work and adding a
conservative model fallback contract.

## Decisions

### Local router key

- `codex-router init` creates `~/.codex-router/config.json` unless
  `CODEX_ROUTER_CONFIG` overrides the path.
- The file contains only the router API key and is written through a temporary
  file plus atomic replacement.
- Existing files are never silently overwritten.
- Symlinks, reparse points, non-regular files, malformed JSON, and invalid key
  values fail closed.
- POSIX files are required to have no group/world permissions. The dashboard
  reports only whether a key is configured; it never returns the key.
- `CODEX_ROUTER_API_KEY` remains an explicit override for managed/ephemeral
  environments and must be a long, safe token.

### Bounded App Server admission

- One request uses the short-lived App Server process at a time.
- `CODEX_ROUTER_QUEUE_SIZE` limits additional waiting requests (default `2`).
- `CODEX_ROUTER_QUEUE_TIMEOUT` bounds how long a request waits (default
  `30` seconds).
- Full and timed-out admission returns HTTP `429` with distinct safe error
  codes. Queue slots are released on all paths.

### Model fallback

- `CODEX_ROUTER_MODEL_FALLBACKS` is a comma-separated list of model IDs.
- Fallbacks are considered only when the request uses the synthetic `codex`
  alias or omits the model.
- Every configured fallback must be present in the live App Server model
  catalog and pass the same model-ID validation as normal catalog entries.
- A fallback is attempted only for the narrowly classified App Server
  `model_unavailable` error from `thread/start`.
- Authentication, quota/rate-limit, timeout, transport, approval, and protocol
  errors are returned immediately and are never retried with another model.

## Verification

- Unit tests cover key bootstrap/reuse/fail-closed behavior, queue full and
  timeout behavior, model-unavailable classification, fallback success, and
  no-retry auth behavior.
- The full test suite, compile check, diff check, secret scan, and no-cost live
  `model/list` smoke check must pass before publishing the phase.
