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
- OpenAI-compatible `/v1/models` and `/v1/chat/completions` routes.
- `/v1/models` is mapped from Codex App Server `model/list`.
- Text-only chat input and streaming text deltas from Codex App Server.
- Fixed `approvalPolicy=on-request`, `sandbox=read-only`, and ephemeral threads.
- Tool, approval, command-output, and other non-text events are not exposed.
- A separate `X-Codex-Router-Key` boundary for every `/v1/*` request.
- SQLite metadata only: no raw access or refresh tokens.
- Versioned compatibility registry with reviewed evidence and rollback metadata.

## Setup with a real Codex login

Run `codex login` first, then start the router with a local-only API key:

```powershell
$env:PYTHONPATH = "$pwd\src"
$env:CODEX_ROUTER_API_KEY = "replace-with-a-long-random-local-key"
python -m codex_router status
python -m codex_router serve
```

Use the router key only in the local client request header:

```powershell
curl.exe http://127.0.0.1:20128/v1/models -H "X-Codex-Router-Key: replace-with-a-long-random-local-key"
```

The router launches `codex app-server --listen stdio://`; authenticate the
Codex CLI first with `codex login`. The App Server process is short-lived and
isolated per request in the current MVP. Approval and client-side tool requests
fail closed.

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
| `CODEX_ROUTER_CODEX_COMMAND` | `codex` | Trusted local Codex CLI executable; invoked without a shell |
| `CODEX_ROUTER_UPSTREAM_URL` | `https://api.openai.com/v1` | Synthetic-v1 compatibility upstream only; ignored by real-v1 |
| `CODEX_ROUTER_DATABASE` | `~/.codex-router/router.sqlite3` | Non-secret metadata database |
| `CODEX_ROUTER_ADAPTER` | `real-v1` | Pinned adapter identifier |

Real-v1 never forwards bearer credentials to a configurable HTTP upstream.
For synthetic-v1, arbitrary remote custom upstreams, embedded URL credentials,
redirects, and plain HTTP outside loopback are refused. Never put secrets in
source control, command history, request logs, SQLite metadata, fixtures, or
bug reports.

## Compatibility updates

GitHub Actions checks the official release signal on maintainer infrastructure,
validates sanitized fixtures, and runs the test matrix on a schedule. The
router does not phone home or silently download executable code. Adapter updates
are reviewed, pinned, and rollback-capable.

## Security

Read [SECURITY.md](SECURITY.md) before testing with any account. This repository
must never contain a real credential file or an authorization header.
