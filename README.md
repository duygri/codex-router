# codex-router

Local-first, Codex-only gateway with an OpenAI-compatible HTTP surface.

## Current status

This project is experimental. `real-v1` starts the official Codex App Server
through the locally installed Codex CLI and uses the CLI's own authenticated
session. The router does not read or forward a Codex bearer token for real
requests. When the CLI session expires, run `codex login` again. The router
never writes the Codex credential file, invents an OAuth client, or bypasses
quotas and provider controls.

The compatibility registry is promoted to `verified` only after a known Codex
CLI/App Server version passes a reviewed, no-cost `model/list` smoke check.
Until then, the adapter remains `experimental-unverified` even when local
`status` reports a healthy CLI session.

Reusing a subscription-backed Codex session may be subject to OpenAI or account
terms. You are responsible for confirming that your use complies with
applicable terms and account policies.

## What it provides

- Loopback-only HTTP server on `127.0.0.1:20128` by default.
- `/health`, `/status`, and a local status page at `/`.
- `/ready` for a bounded Codex CLI/App Server readiness report.
- OpenAI-compatible `/v1/models` and `/v1/chat/completions` routes.
- Text-only `/v1/responses` compatibility for clients that use the Responses API.
- `/v1/models` is mapped from Codex App Server `model/list`.
- Text-only chat input and streaming text deltas from Codex App Server.
- Local `codex` model alias plus normalized live model catalog.
- Local operations dashboard with aggregate usage counters and capability status.
- App Server token usage totals when Codex reports them; prompt and event payloads are never stored.
- Fixed `approvalPolicy=on-request`, `sandbox=read-only`, and ephemeral threads.
- Tool, approval, command-output, and other non-text events are not exposed.
- A separate `X-Codex-Router-Key` boundary for every `/v1/*` request.
- SQLite metadata only: no raw access or refresh tokens.
- Versioned compatibility registry with reviewed evidence and rollback metadata.

## Setup with a real Codex login

Run `codex login` first, then create a local-only router key and start the router:

```powershell
$env:PYTHONPATH = "$pwd\src"
python -m codex_router init
python -m codex_router status
python -m codex_router doctor
python -m codex_router serve
```

The default key file is `~/.codex-router/config.json`, outside the repository
and SQLite database. The `init` command creates it atomically with restrictive
permissions and never prints the key. To copy the key explicitly, run
`python -m codex_router key --show`; otherwise `python -m codex_router key`
only reports whether it is configured. `CODEX_ROUTER_CONFIG` can point to a
different private config file, and `CODEX_ROUTER_API_KEY` can explicitly
override the file for ephemeral/managed environments.

Use the router key only in the local client request header:

```powershell
curl.exe http://127.0.0.1:20128/v1/models -H "X-Codex-Router-Key: replace-with-a-long-random-local-key"
```

Text-only Responses API clients can use the same local boundary:

```powershell
curl.exe http://127.0.0.1:20128/v1/responses `
  -H "X-Codex-Router-Key: replace-with-a-long-random-local-key" `
  -H "Content-Type: application/json" `
  -d '{"model":"codex","input":"Say hello","stream":false}'
```

Tools, function calls, and multimodal input are intentionally rejected until
there is a reviewed Codex App Server contract for safely exposing them.

Open `http://127.0.0.1:20128/` for the local operations dashboard. It shows
model availability, aggregate request counters, and fixed security capabilities;
it never asks for or displays the router key. `model: "codex"` resolves to the
first model reported by the local Codex App Server. Model discovery is cached
briefly; a stale cache is marked degraded rather than silently hidden.

The router launches `codex app-server --listen stdio://`; authenticate the
Codex CLI first with `codex login`. The App Server process is short-lived and
isolated per request in the current MVP. Approval and client-side tool requests
fail closed.

`codex-router doctor` performs an independent, uncached diagnostic before
opening SQLite. It checks the local CLI version, App Server initialization and
model discovery without sending a prompt. `GET /ready` uses the in-process
serialized probe: it caches both ready and not-ready results for 10 seconds,
allows a caller to wait at most 2 seconds for an in-flight probe, and bounds
CLI/App Server checks to 2/3 seconds. A waiter timeout is not cached.

Python 3.8 or newer is required. Install the local package when pip supports
the checkout path:

```powershell
python -m pip install -e .
```

If an older Windows pip cannot handle a non-ASCII working-directory path, run
directly from the checkout instead:

```powershell
$env:PYTHONPATH = "$pwd\src"
python -m codex_router status
```

Useful commands:

```text
codex-router serve [--host HOST] [--port PORT]
codex-router status
codex-router reset
codex-router init
codex-router key [--show]
codex-router doctor
```

`reset` clears router-owned SQLite metadata and in-memory state. It never
deletes or modifies the Codex CLI credential store.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_HOME` | `~/.codex` | Authoritative Codex state directory when set |
| `CODEX_ROUTER_HOST` | `127.0.0.1` | Loopback bind only; non-loopback binds are refused |
| `CODEX_ROUTER_PORT` | `20128` | Local port |
| `CODEX_ROUTER_AUTH_FILE` | `$CODEX_HOME/auth.json` | Legacy/status compatibility path; real-v1 requests use the Codex CLI process |
| `CODEX_ROUTER_AUTH_MODE` | `file` | Local session status mode; `env` is for synthetic/fixture compatibility only |
| `CODEX_ACCESS_TOKEN` | unset | Synthetic/fixture compatibility input; never forwarded by real-v1 |
| `CODEX_ROUTER_TOKEN_EXPIRES_AT` | unset | Required ISO expiry for non-JWT synthetic tokens |
| `CODEX_ROUTER_API_KEY` | unset | Required for `/v1/*`; use `X-Codex-Router-Key` |
| `CODEX_ROUTER_CONFIG` | `~/.codex-router/config.json` | Private local JSON file containing the router key |
| `CODEX_ROUTER_CODEX_COMMAND` | `codex` | Trusted local Codex CLI executable; invoked without a shell |
| `CODEX_ROUTER_UPSTREAM_URL` | `https://api.openai.com/v1` | Synthetic-v1 compatibility upstream only; ignored by real-v1 |
| `CODEX_ROUTER_DATABASE` | `~/.codex-router/router.sqlite3` | Non-secret metadata database |
| `CODEX_ROUTER_ADAPTER` | `real-v1` | Pinned adapter identifier |
| `CODEX_ROUTER_QUEUE_SIZE` | `2` | Maximum requests waiting behind the active App Server request |
| `CODEX_ROUTER_QUEUE_TIMEOUT` | `30` seconds | Maximum wait before returning a bounded-queue error |
| `CODEX_ROUTER_MODEL_FALLBACKS` | unset | Comma-separated live model IDs used only for the `codex` alias |

`doctor` and `/ready` return only a fixed four-check JSON envelope. Invalid
configuration uses `invalid_config`; synthetic-v1 marks Codex-specific checks
as `skipped`. App Server model-list identifiers must be safe and agree when
both `id` and `model` are present; only known non-secret metadata is accepted.
Malformed mixed catalogs fail closed. Diagnostic output is bounded and raw
subprocess output is never returned.

Real-v1 never forwards bearer credentials to a configurable HTTP upstream.
For synthetic-v1, arbitrary remote custom upstreams, embedded URL credentials,
redirects, and plain HTTP outside loopback are refused. Never put secrets in
source control, command history, request logs, SQLite metadata, fixtures, or
bug reports.

Usage data is aggregate-only: request totals, terminal counts, active count,
last request time, per-model counts, and optional numeric token totals reported
by App Server. Prompt text, response text, event payloads, headers, and
credentials are never stored in SQLite metadata. Responses support is
text-only; tools and multimodal inputs remain disabled.

The optional model fallback list is resolved against the live Codex model
catalog. A fallback is attempted only when App Server classifies the requested
model as unavailable; authentication failures, quota/rate limits, timeouts,
transport failures, and protocol errors are returned without retrying another
model. The bounded queue likewise fails closed with a 429 when it is full or
the wait deadline expires.

## Compatibility updates

GitHub Actions checks the official release signal on maintainer infrastructure,
validates sanitized fixtures, and runs the test matrix on a schedule. The
router does not phone home or silently download executable code. Adapter updates
are reviewed, pinned, and rollback-capable.

## Security

Read [SECURITY.md](SECURITY.md) before testing with any account. This repository
must never contain a real credential file or an authorization header.
