# Codex Router Core Design

**Goal:** Make the Codex-only gateway feel like the useful core of 9router while preserving the App Server security boundary.

## Scope

Phase A adds a local operations dashboard, a dynamic Codex model catalog with safe aliases, and secret-free request usage metadata. It does not add multi-provider routing, direct bearer forwarding, remote dashboard access, prompt logging, or client-controlled sandbox/approval policies.

## Architecture

The Codex CLI remains the authentication owner. `Gateway` talks to `AppServerBridge`; a small `ModelCatalog` normalizes `model/list` results and resolves aliases before `thread/start`. A `UsageTracker` stores only aggregate counters and safe model identifiers in `MetadataStore`. The HTTP server exposes dashboard data only on loopback and keeps `/v1/*` protected by `X-Codex-Router-Key`.

The dashboard is server-rendered HTML with progressive enhancement. It has a dark operations layout, semantic status colors, responsive cards, model rows, and usage metrics. It does not contain or request the router API key. Model data is read from a local safe dashboard endpoint and failures render an explicit degraded state. Visual tokens and interaction rules are defined separately in `docs/superpowers/specs/2026-07-21-codex-router-dashboard-ui-design.md`.

## Security invariants

- The listener accepts only loopback hosts; any non-loopback bind fails before serving.
- Every `/v1/*` request requires a constant-time comparison against `X-Codex-Router-Key`.
- The real-v1 path never constructs an HTTP `Authorization: Bearer` request and never reads a bearer token for transport.
- Execution-bearing App Server requests always set `approvalPolicy=on-request`, `sandbox=read-only`, and `ephemeral=true`; client payloads cannot override them. The `initialize`, `initialized`, and `model/list` protocol messages do not carry execution policy fields.
- `/dashboard/data` is loopback-only safe metadata. It contains no router key, credentials, prompt text, response text, raw event payload, or exception detail.
- Model IDs and all values rendered into HTML are validated/escaped; model IDs are never inserted as executable JavaScript.

## Dashboard contract

- `/` returns `200 text/html; charset=utf-8` and renders the dashboard shell and safe initial status.
- `/dashboard/data` returns `200 application/json` with the canonical envelope `{status, models, usage, capabilities, error}` and `Cache-Control: no-store`; `error` is always present and nullable.
- `status` is an object `{state, auth, session, transport, approval_policy, sandbox, message}` where `state` is `ok` or `degraded`; values are safe strings and `message` is nullable.
- `models` contains `{id, alias, owned_by, available}` entries. `id` and `owned_by` are non-empty validated strings; `alias` is nullable or a validated string; `available` is boolean. The first live model receives alias `codex`; other models have `alias: null`.
- `usage` contains only cumulative aggregates: integer `total_requests`, `completed_requests`, `failed_requests`, `cancelled_requests`, `active_requests`, nullable ISO-8601 UTC `last_request_at`, and an array `by_model` of `{model, requests}`. It has the same valid typed shape in both states, with zero/empty/null fallbacks.
- `capabilities` contains boolean `chat_completions`, boolean `responses`, boolean `streaming`, string `approval_policy`, string `sandbox`, and boolean `tools`; Phase A sets `responses=false` and `tools=false`.
- `error` is nullable and, when present, is `{code, message}` with safe values. Model discovery failure with a non-empty cache sets `state=degraded`, preserves cached models, and sets a recovery message. Failure with no cache returns an empty model list and the same typed usage/capability fallback. A successful refresh returns `state=ok` and clears the error.
- Dashboard errors use the existing safe `{error: {code, message}}` shape and never include stack traces or upstream payloads.

## Phase A API compatibility

| Surface | Request | Result | Failure behavior |
| --- | --- | --- | --- |
| `GET /v1/models` | Router key required | OpenAI model-list JSON from App Server `model/list` | 401/403 key errors; 429 busy; 502/503/504 safe App Server errors |
| `POST /v1/chat/completions` | Router key; text `system/user/assistant`; `model` or `codex` alias; `stream` boolean | OpenAI-compatible JSON or SSE text deltas | 400 validation; 401/403 key; 429 busy; safe App Server errors |
| `GET /dashboard/data` | Loopback only; no key because response is safe metadata | Dashboard JSON contract above | 200 degraded shape if model discovery is unavailable |

Phase A does not claim Responses API support yet. `/v1/models` advertises the live model IDs plus a synthetic alias entry `{id:"codex", object:"model", created:0, owned_by:"codex-router"}`; the alias resolves to the first live model. Live entries normalize App Server `id` first, then `model`, with `object:"model"`, `created:0`, and `owned_by:"codex"`; duplicate IDs are emitted once in App Server order. If the catalog is stale, `/v1/models` serves the cached normalized list and adds `X-Codex-Router-Catalog: stale`; if no catalog exists, it returns safe 503. `tools`, function calling, response-format overrides, client sandbox/approval fields, multipart input, and non-text message content are rejected with 400.

## Model aliases

Aliases are local convenience names only. The catalog refreshes from `model/list` on first use and after a 60-second TTL; the App Server's order is preserved. `codex` resolves to the first available model. Explicit model IDs must match the current catalog; unknown IDs and aliases fail with 400, and an empty/unavailable catalog fails with safe 503. Alias names cannot collide with model IDs; model IDs are preferred if a future alias collides. If a refresh fails after a non-empty catalog exists, the stale catalog remains usable for `/v1/models`, explicit model validation, and alias resolution; the dashboard reports `degraded` and the models response is marked stale. A later successful refresh replaces the cache and clears stale state. Alias resolution never changes approval or sandbox policy and never executes a command.

## Usage and privacy

The tracker records only aggregate request start/completion/error/cancellation counts, active requests, model ID counts, and the latest request timestamp. A request is active after admission and terminal only when a response completes, errors, is interrupted, or the client disconnects; failures before admission do not increment counters. Counters are cumulative across restart, stored as one validated aggregate metadata document, and have no automatic retention because they contain no content. Concurrent updates are serialized. It never records messages, response text, stream flags, status codes, authorization headers, access tokens, refresh tokens, or raw App Server event payloads. SQLite metadata validation remains the final safety boundary.

## App Server message policy

- `thread/start` is the only execution-policy-bearing setup message and always receives the fixed `approvalPolicy`, `sandbox`, and `ephemeral` values.
- `turn/start` receives only the validated `threadId` and text input; it cannot receive client tools, permissions, or policy overrides.
- `turn/interrupt` receives only the server-owned `threadId` and `turnId` during cleanup.
- `initialize`, `initialized`, and `model/list` carry no execution policy and expose no credentials.

## UI acceptance

The dashboard must use bundled/system fonts or a local fallback (no required network font), keep all interactive controls keyboard accessible with visible focus, use semantic text in addition to color, support 375px through desktop widths without horizontal scrolling, and honor `prefers-reduced-motion`. It uses no external JavaScript dependency; the current Python stdlib package remains installable offline. Visual styling is specified separately.

## Testing

Unit tests cover alias resolution, catalog ordering/TTL/empty behavior, aggregate usage privacy and concurrency, dashboard JSON shape/status headers, HTML escaping/accessibility markers, and the security invariants above. Server tests cover dashboard data degraded behavior, API-key enforcement, loopback binding, bearer non-forwarding, and fixed App Server policy. Existing App Server security and compatibility tests remain required.
